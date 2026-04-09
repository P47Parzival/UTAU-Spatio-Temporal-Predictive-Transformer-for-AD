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
live_buffer = deque(maxlen=100) # Holds exactly 1 window
data_condition = asyncio.Condition()

class TelemetryData(BaseModel):
    timestamp_ms: int
    sensors: list[float]

def init_model():
    print("Loading STP-TranAD Model...")
    folder = f'checkpoints/{MODEL_NAME}_{DATASET}/'
    ckpt_path = os.path.join(folder, 'model.ckpt')
    
    # Load dataset to extract metadata (feats) and simulate live inputs
    test_arr = np.load(f'processed/{DATASET}/machine-1-1_test.npy')
    labels_arr = np.load(f'processed/{DATASET}/machine-1-1_labels.npy')
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
    for _ in range(100):
        live_buffer.append([0.0] * feats_dim)

@app.post("/ingest")
async def ingest_telemetry(payload: TelemetryData):
    # Live ingestion simulacrum (e.g., from Kafka)
    async with data_condition:
        live_buffer.append(payload.sensors)
        data_condition.notify_all()
    return {"status": "ingested"}

@app.post("/calibrate")
async def trigger_online_learning():
    """Concept Drift handler: dynamically shifts the baseline threshold using physical feedback."""
    if len(live_buffer) < 100:
        return {"status": "buffering"}
    
    print("[DRIFT DETECTED] Calibrating model to accept new variance...")
    model.train() # Enable decoders for backprop
    
    window = torch.DoubleTensor(list(live_buffer)).unsqueeze(0).permute(1, 0, 2).to(device)
    
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
                # Snap the current 100-frame window securely
                current_window = list(live_buffer)
            
            if len(current_window) < model.n_window:
                continue

            window_tensor = torch.DoubleTensor(current_window).unsqueeze(0).permute(1, 0, 2).to(device)
            
            with torch.no_grad():
                x1, x2, forecast = model(window_tensor)
            
            # Ground truth metric calculations
            elem = window_tensor[-1, :, :].view(1, 1, feats_dim)
            recon_loss = l(x2, elem)[0].detach().cpu().numpy()[0]
            
            overall_loss = float(np.mean(recon_loss))
            
            # Predict precisely 1 step into the forecast
            pred_future = forecast[:, 0, :].detach().cpu().numpy()[0]
            actual_sensors = current_window[-1]
            
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
