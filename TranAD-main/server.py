import asyncio
import json
import numpy as np
import torch
import torch.nn as nn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from collections import deque
import os
import gc

from src.models import STP_TranAD

app = FastAPI(title="STP-TranAD Streaming Inference Engine")

# CORS for React Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global State & Buffers
active_connections: list[WebSocket] = []
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
MODEL_NAME = 'STP_TranAD'
DATASET = 'SMD'
model = None
optimizer = None
# Keep one extra frame so we can forecast current from previous model.n_window points.
live_buffer = deque(maxlen=101)
data_condition = asyncio.Condition()
model_lock = asyncio.Lock() # Safeguards streaming thread against dimension swapping crashes

class TelemetryData(BaseModel):
    timestamp_ms: int
    sensors: list[float]
    
class SwapRequest(BaseModel):
    dataset: str

def init_model(target_ds=None):
    if target_ds is None:
        target_ds = DATASET
    print(f"Loading STP-TranAD Model for {target_ds}...")
    folder = f'checkpoints/{MODEL_NAME}_{target_ds}/'
    ckpt_path = os.path.join(folder, 'model.ckpt')
    
    # Identify target dynamic files
    if target_ds == 'SMD':
        test_arr = np.load(f'processed/{target_ds}/machine-1-1_test.npy')
    elif target_ds == 'MSL':
        test_arr = np.load(f'processed/{target_ds}/C-1_test.npy')
    else: # SMAP
        test_arr = np.load(f'processed/{target_ds}/A-1_test.npy')
        
    feats = test_arr.shape[1]
    
    # Initialize Model fundamentally equivalent to Training initialization
    m = STP_TranAD(feats).double().to(device)
    opt = torch.optim.AdamW(m.parameters(), lr=1e-5, weight_decay=1e-5)
    
    if os.path.exists(ckpt_path):
        checkpoint = torch.load(ckpt_path, map_location=device, weights_only=False)
        m.load_state_dict(checkpoint['model_state_dict'])
        opt.load_state_dict(checkpoint['optimizer_state_dict'])
        print(f"Pre-trained checkpoint loaded successfully from {ckpt_path}.")
    else:
        print("WARNING: Checkpoint not found. Running with uninitialized random weights.")
    m.eval()
    return m, opt, feats

@app.on_event("startup")
async def startup_event():
    global model, optimizer, feats_dim
    model, optimizer, feats_dim = init_model()
    
    # Pre-fill buffer with mean zero-state to prevent startup crashes
    for _ in range(101):
        live_buffer.append([0.0] * feats_dim)

@app.post("/ingest")
async def ingest_telemetry(payload: TelemetryData):
    async with model_lock:
        if len(payload.sensors) != feats_dim:
            return {"status": "dropped", "reason": "dimension mismatch during swap"}
            
        async with data_condition:
            live_buffer.append(payload.sensors)
            data_condition.notify_all()
    return {"status": "ingested"}

@app.get("/status")
async def get_status():
    return {"active_dataset": DATASET, "dimensions": feats_dim}

@app.post("/change_dataset")
async def trigger_dataset_swap(req: SwapRequest):
    global DATASET, model, optimizer, feats_dim
    if req.dataset not in ['SMD', 'MSL', 'SMAP']:
        return {"error": "Invalid Dataset"}

    async with model_lock:
        print(f"--- INITIATING HOT-SWAP TO {req.dataset} ---")
        DATASET = req.dataset
        
        # Flush VRAM gracefully
        del model
        del optimizer
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            
        model, optimizer, feats_dim = init_model(target_ds=req.dataset)
        
        # Flush baseline frames to buffer
        live_buffer.clear()
        for _ in range(101):
            live_buffer.append([0.0] * feats_dim)
            
    return {"status": "success", "new_dataset": DATASET, "new_dim": feats_dim}

@app.post("/calibrate")
async def trigger_online_learning():
    """Concept Drift handler: dynamically shifts the baseline threshold using physical feedback."""
    if len(live_buffer) < model.n_window + 1:
        return {"status": "buffering"}
    
    print("[DRIFT DETECTED] Calibrating model to accept new variance...")
    model.train() # Enable decoders for backprop
    
    # Use previous model window (exclude newest point) to stay consistent with training setup.
    window = torch.DoubleTensor(list(live_buffer)[:-1]).unsqueeze(0).permute(1, 0, 2).to(device)
    
    # One small epoch to absorb the new pattern
    optimizer.zero_grad()
    x1, x2, forecast = model(window)
    # Simple MSE to accept the recent state as healthy
    local_bs = window.shape[1]
    elem = window[-1, :, :].view(1, local_bs, feats_dim)
    l = nn.MSELoss()
    loss = l(x2, elem)
    loss.backward()
    optimizer.step()
    
    model.eval()
    return {"status": "calibrated"}

@app.websocket("/ws/stream")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    print("UI Client Connected to Dynamic Stream")
    
    try:
        l = nn.MSELoss(reduction='none')
        current_tick = 0
        
        while True:
            # Wait for dynamic data to arrive in ingestion buffer
            async with data_condition:
                await data_condition.wait()
                # Snap the current buffered sequence securely
                current_window = list(live_buffer)
            
            if len(current_window) < model.n_window + 1:
                continue

            # Causal one-step prediction: history -> current actual.
            history_window = current_window[:-1]
            actual_sensors = current_window[-1]
            window_tensor = torch.DoubleTensor(history_window).unsqueeze(0).permute(1, 0, 2).to(device)
            
            async with model_lock:
                with torch.no_grad():
                    x1, x2, forecast = model(window_tensor)
                
                # Ground truth metric calculations
                elem = window_tensor[-1, :, :].view(1, 1, feats_dim)
                recon_loss = l(x2, elem)[0].detach().cpu().numpy()[0]
                
                overall_loss = float(np.mean(recon_loss))
                
                # Use true predictive head output (horizon step 0) for dashboard forecast curves.
                # forecast shape: (H, Batch, Feats)
                pred_future = forecast[0, 0, :].detach().cpu().numpy()
                
            # Dynamically compile the dictionary of all sensors based on reality
            sensors_actual = {}
            sensors_forecast = {}
            for i in range(feats_dim):
                sensors_actual[f"s{i}_actual"] = float(actual_sensors[i])
                sensors_forecast[f"s{i}_forecast"] = float(pred_future[i])

            payload = {
                "tick": current_tick,
                "system_loss": overall_loss,
                "is_anomalous": overall_loss > 0.05, 
                "threshold": 0.05, 
                "dimensions": feats_dim, # Tell React how many DOM elements to spawn
                "sensors": sensors_actual,
                "forecast": sensors_forecast
            }
            
            await websocket.send_text(json.dumps(payload))
            current_tick += 1
            
    except WebSocketDisconnect:
        active_connections.remove(websocket)
        print("UI Client Disconnected")

@app.get("/")
def read_root():
    return {"status": "STP-TranAD Engine is running", "ready": model is not None}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
