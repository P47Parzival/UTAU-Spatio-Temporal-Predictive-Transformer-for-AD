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
import time
import math

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

# Ingestion controls
INGEST_MAX_BACKWARD_MS = int(os.getenv("INGEST_MAX_BACKWARD_MS", "2000"))
INGEST_MAX_CLOCK_SKEW_MS = int(os.getenv("INGEST_MAX_CLOCK_SKEW_MS", "60000"))
INGEST_MIN_STATS_WINDOW = int(os.getenv("INGEST_MIN_STATS_WINDOW", "20"))
INGEST_OUTLIER_ZSCORE = float(os.getenv("INGEST_OUTLIER_ZSCORE", "12.0"))
INGEST_DEGRADED_DROPOUT_RATIO = float(os.getenv("INGEST_DEGRADED_DROPOUT_RATIO", "0.2"))

# Phase 2 scoring controls
FUSED_WEIGHT_RECON = float(os.getenv("FUSED_WEIGHT_RECON", "0.55"))
FUSED_WEIGHT_FORECAST = float(os.getenv("FUSED_WEIGHT_FORECAST", "0.30"))
FUSED_WEIGHT_CORR = float(os.getenv("FUSED_WEIGHT_CORR", "0.15"))
FUSED_THRESHOLD_DEFAULT = float(os.getenv("FUSED_THRESHOLD_DEFAULT", "1.5"))
FUSED_THRESHOLD_PERCENTILE = float(os.getenv("FUSED_THRESHOLD_PERCENTILE", "97.5"))
FUSED_THRESHOLD_WARMUP = int(os.getenv("FUSED_THRESHOLD_WARMUP", "120"))

# Ingestion runtime state
last_ingest_timestamp_ms = None
last_valid_vector = []
sensor_dropout_streak = []
ingest_stats = {
    "total": 0,
    "accepted": 0,
    "dropped_dimension_mismatch": 0,
    "dropped_invalid_timestamp": 0,
    "out_of_order": 0,
    "clock_skew": 0,
    "imputed_values": 0,
    "outlier_values": 0,
    "degraded_events": 0,
}
last_ingest_meta = {
    "imputed_ratio": 0.0,
    "imputed_count": 0,
    "outlier_count": 0,
    "degraded": False,
}

score_histories = {
    "recon": deque(maxlen=2000),
    "forecast": deque(maxlen=2000),
    "corr": deque(maxlen=2000),
    "fused": deque(maxlen=2000),
}

recent_alert_history = deque(maxlen=500)
anomaly_streak = 0
last_score_meta = {
    "recon_score": 0.0,
    "forecast_score": 0.0,
    "corr_score": 0.0,
    "fused_score": 0.0,
    "threshold": FUSED_THRESHOLD_DEFAULT,
}

class TelemetryData(BaseModel):
    timestamp_ms: int
    sensors: list[float]
    
class SwapRequest(BaseModel):
    dataset: str

def _reset_ingestion_state(dim: int):
    global last_ingest_timestamp_ms, last_valid_vector, sensor_dropout_streak, last_ingest_meta, last_score_meta
    last_ingest_timestamp_ms = None
    last_valid_vector = [0.0] * dim
    sensor_dropout_streak = [0] * dim
    last_ingest_meta = {
        "imputed_ratio": 0.0,
        "imputed_count": 0,
        "outlier_count": 0,
        "degraded": False,
    }
    for key in ingest_stats:
        ingest_stats[key] = 0

    for k in score_histories:
        score_histories[k].clear()
    last_score_meta = {
        "recon_score": 0.0,
        "forecast_score": 0.0,
        "corr_score": 0.0,
        "fused_score": 0.0,
        "threshold": FUSED_THRESHOLD_DEFAULT,
    }

def _safe_corrcoef(x: np.ndarray) -> np.ndarray:
    if x.ndim != 2 or x.shape[1] <= 1:
        return np.eye(max(1, x.shape[1]), dtype=np.float64)
    centered = x - np.mean(x, axis=0, keepdims=True)
    cov = np.dot(centered.T, centered) / max(1, x.shape[0] - 1)
    std = np.sqrt(np.clip(np.diag(cov), 1e-8, None))
    denom = np.outer(std, std)
    c = cov / denom
    c = np.nan_to_num(c, nan=0.0, posinf=0.0, neginf=0.0)
    if c.ndim == 0:
        return np.eye(1, dtype=np.float64)
    np.fill_diagonal(c, 1.0)
    return c

def _correlation_shift_score(history_window: np.ndarray) -> float:
    if history_window.ndim != 2 or history_window.shape[0] < 8:
        return 0.0
    midpoint = history_window.shape[0] // 2
    prev_block = history_window[:midpoint]
    curr_block = history_window[midpoint:]
    c_prev = _safe_corrcoef(prev_block)
    c_curr = _safe_corrcoef(curr_block)
    diff = c_curr - c_prev
    denom = float(diff.size) if diff.size else 1.0
    return float(np.linalg.norm(diff, ord='fro') / denom)

def _positive_zscore(value: float, history: deque) -> float:
    hist = np.asarray(history, dtype=np.float64)
    if hist.size < 30:
        return max(0.0, float(value))
    mu = float(np.mean(hist))
    sigma = float(np.std(hist) + 1e-8)
    return max(0.0, float((value - mu) / sigma))

def _compute_fused_score(recon_vec: np.ndarray, forecast_vec: np.ndarray, corr_shift: float):
    global last_score_meta
    recon_score = float(np.mean(recon_vec))
    forecast_score = float(np.mean(forecast_vec))
    corr_score = float(corr_shift)

    score_histories["recon"].append(recon_score)
    score_histories["forecast"].append(forecast_score)
    score_histories["corr"].append(corr_score)

    recon_z = _positive_zscore(recon_score, score_histories["recon"])
    forecast_z = _positive_zscore(forecast_score, score_histories["forecast"])
    corr_z = _positive_zscore(corr_score, score_histories["corr"])

    fused_score = (
        FUSED_WEIGHT_RECON * recon_z +
        FUSED_WEIGHT_FORECAST * forecast_z +
        FUSED_WEIGHT_CORR * corr_z
    )
    score_histories["fused"].append(fused_score)

    if len(score_histories["fused"]) >= FUSED_THRESHOLD_WARMUP:
        threshold = float(np.percentile(np.asarray(score_histories["fused"], dtype=np.float64), FUSED_THRESHOLD_PERCENTILE))
    else:
        threshold = FUSED_THRESHOLD_DEFAULT

    last_score_meta = {
        "recon_score": recon_score,
        "forecast_score": forecast_score,
        "corr_score": corr_score,
        "fused_score": float(fused_score),
        "threshold": threshold,
    }
    return float(fused_score), threshold

def _severity_and_confidence(fused_score: float, threshold: float):
    if threshold <= 1e-8:
        ratio = 0.0
    else:
        ratio = fused_score / threshold
    sev = int(max(0, min(100, round(100.0 / (1.0 + math.exp(-4.0 * (ratio - 1.0)))))))
    if ratio >= 1.2:
        level = "critical"
    elif ratio >= 0.8:
        level = "warning"
    else:
        level = "info"
    confidence = float(max(0.0, min(1.0, 1.0 / (1.0 + math.exp(-6.0 * (ratio - 1.0))))))
    return sev, level, confidence

def _classify_anomaly_type(recon_score: float, forecast_score: float, corr_score: float):
    if corr_score > max(recon_score, forecast_score):
        return "collective_anomaly"
    if forecast_score > (recon_score * 1.25):
        return "contextual_anomaly"
    return "point_anomaly"

def _rank_contributors(recon_vec: np.ndarray, forecast_vec: np.ndarray, top_k: int = 5):
    blended = (0.65 * recon_vec) + (0.35 * forecast_vec)
    total = float(np.sum(blended) + 1e-12)
    order = np.argsort(blended)[::-1][:top_k]
    ranked = []
    for idx in order:
        contribution_pct = float((blended[idx] / total) * 100.0)
        ranked.append({
            "sensor": f"s{int(idx)}",
            "importance": float(blended[idx]),
            "contribution_pct": contribution_pct,
            "recon_error": float(recon_vec[idx]),
            "forecast_error": float(forecast_vec[idx]),
        })
    return ranked, blended

def _cosine_similarity(a: np.ndarray, b: np.ndarray):
    denom = float((np.linalg.norm(a) * np.linalg.norm(b)) + 1e-12)
    return float(np.dot(a, b) / denom)

def _get_similar_history(blended_vec: np.ndarray, top_k: int = 3):
    candidates = []
    for item in recent_alert_history:
        if not item.get("is_anomalous", False):
            continue
        sim = _cosine_similarity(blended_vec, item["blended_vec"])
        candidates.append((sim, item))
    candidates.sort(key=lambda x: x[0], reverse=True)
    results = []
    for sim, item in candidates[:top_k]:
        results.append({
            "tick": item["tick"],
            "dataset": item["dataset"],
            "anomaly_type": item["anomaly_type"],
            "severity": item["severity"],
            "similarity": float(max(0.0, min(1.0, sim))),
            "summary": f"{item['anomaly_type']} with top sensor {item['top_sensor']}",
        })
    return results

def _investigation_hints(anomaly_type: str, contributors: list[dict], corr_score: float):
    hints = []
    if contributors:
        top = contributors[0]
        hints.append(f"Inspect {top['sensor']} first; highest contribution {top['contribution_pct']:.1f}%.")
    if anomaly_type == "collective_anomaly":
        hints.append(f"Check cross-sensor dependency break; correlation shift score={corr_score:.6f}.")
    elif anomaly_type == "contextual_anomaly":
        hints.append("Validate temporal context and operating mode; forecast mismatch is dominant.")
    else:
        hints.append("Investigate sudden local spike and recent actuator/control actions.")
    if len(contributors) > 1:
        hints.append(f"Compare {contributors[0]['sensor']} with {contributors[1]['sensor']} for coupled deviation.")
    return hints[:4]

def _validate_timestamp(timestamp_ms: int):
    global last_ingest_timestamp_ms
    now_ms = int(time.time() * 1000)

    try:
        ts = int(timestamp_ms)
    except (TypeError, ValueError):
        ingest_stats["dropped_invalid_timestamp"] += 1
        return False, "invalid timestamp"

    if abs(now_ms - ts) > INGEST_MAX_CLOCK_SKEW_MS:
        ingest_stats["clock_skew"] += 1

    if last_ingest_timestamp_ms is not None:
        if ts < last_ingest_timestamp_ms - INGEST_MAX_BACKWARD_MS:
            ingest_stats["dropped_invalid_timestamp"] += 1
            return False, "timestamp too old"
        if ts < last_ingest_timestamp_ms:
            ingest_stats["out_of_order"] += 1

    if last_ingest_timestamp_ms is None or ts > last_ingest_timestamp_ms:
        last_ingest_timestamp_ms = ts
    return True, "ok"

def _sanitize_sensors(raw_sensors: list[float], expected_dim: int):
    global last_valid_vector, sensor_dropout_streak, last_ingest_meta

    if len(raw_sensors) != expected_dim:
        ingest_stats["dropped_dimension_mismatch"] += 1
        return None, "dimension mismatch"

    history_mean = None
    history_std = None
    if len(live_buffer) >= INGEST_MIN_STATS_WINDOW:
        history_arr = np.asarray(live_buffer, dtype=np.float64)
        history_mean = history_arr.mean(axis=0)
        history_std = history_arr.std(axis=0)

    sanitized = [0.0] * expected_dim
    imputed_indices = []
    outlier_indices = []

    for idx in range(expected_dim):
        raw_value = raw_sensors[idx]
        should_impute = False

        try:
            value = float(raw_value)
            if not np.isfinite(value):
                should_impute = True
        except (TypeError, ValueError):
            should_impute = True

        if should_impute:
            value = last_valid_vector[idx]
            imputed_indices.append(idx)
        elif history_mean is not None and history_std is not None and history_std[idx] > 1e-9:
            z_score = abs((value - history_mean[idx]) / (history_std[idx] + 1e-9))
            if z_score > INGEST_OUTLIER_ZSCORE:
                outlier_indices.append(idx)

        sanitized[idx] = value

    imputed_index_set = set(imputed_indices)
    for idx in range(expected_dim):
        if idx in imputed_index_set:
            sensor_dropout_streak[idx] += 1
        else:
            sensor_dropout_streak[idx] = 0
        last_valid_vector[idx] = sanitized[idx]

    imputed_count = len(imputed_indices)
    outlier_count = len(outlier_indices)
    imputed_ratio = imputed_count / float(expected_dim) if expected_dim else 0.0
    degraded = imputed_ratio >= INGEST_DEGRADED_DROPOUT_RATIO

    ingest_stats["imputed_values"] += imputed_count
    ingest_stats["outlier_values"] += outlier_count
    if degraded:
        ingest_stats["degraded_events"] += 1

    last_ingest_meta = {
        "imputed_ratio": imputed_ratio,
        "imputed_count": imputed_count,
        "outlier_count": outlier_count,
        "degraded": degraded,
    }
    return sanitized, "ok"

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
    _reset_ingestion_state(feats_dim)
    
    # Pre-fill buffer with mean zero-state to prevent startup crashes
    for _ in range(101):
        live_buffer.append([0.0] * feats_dim)

@app.post("/ingest")
async def ingest_telemetry(payload: TelemetryData):
    ingest_stats["total"] += 1
    async with model_lock:
        timestamp_ok, timestamp_reason = _validate_timestamp(payload.timestamp_ms)
        if not timestamp_ok:
            return {"status": "dropped", "reason": timestamp_reason}

        sanitized_sensors, sanitize_reason = _sanitize_sensors(payload.sensors, feats_dim)
        if sanitized_sensors is None:
            return {"status": "dropped", "reason": sanitize_reason}
            
        async with data_condition:
            live_buffer.append(sanitized_sensors)
            data_condition.notify_all()

    ingest_stats["accepted"] += 1
    return {
        "status": "ingested",
        "degraded": last_ingest_meta["degraded"],
        "imputed_count": last_ingest_meta["imputed_count"],
        "outlier_count": last_ingest_meta["outlier_count"],
    }

@app.get("/status")
async def get_status():
    return {
        "active_dataset": DATASET,
        "dimensions": feats_dim,
        "ingest": {
            "totals": ingest_stats,
            "last": last_ingest_meta,
            "last_timestamp_ms": last_ingest_timestamp_ms,
            "degraded_mode": last_ingest_meta["degraded"],
        },
        "scoring": {
            "weights": {
                "recon": FUSED_WEIGHT_RECON,
                "forecast": FUSED_WEIGHT_FORECAST,
                "corr": FUSED_WEIGHT_CORR,
            },
            "last": last_score_meta,
            "fused_history_size": len(score_histories["fused"]),
        },
    }

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
        _reset_ingestion_state(feats_dim)
        
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
    global anomaly_streak
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

                # Use true predictive head output (horizon step 0) for dashboard forecast curves.
                # forecast shape: (H, Batch, Feats)
                pred_future = forecast[0, 0, :].detach().cpu().numpy()

            forecast_loss = np.square(pred_future - np.asarray(actual_sensors, dtype=np.float64))
            corr_shift = _correlation_shift_score(np.asarray(history_window, dtype=np.float64))
            fused_score, fused_threshold = _compute_fused_score(recon_loss, forecast_loss, corr_shift)
            is_anomalous = fused_score > fused_threshold
            if is_anomalous:
                anomaly_streak += 1
            else:
                anomaly_streak = 0

            severity_score, severity_level, confidence = _severity_and_confidence(fused_score, fused_threshold)
            anomaly_type = _classify_anomaly_type(
                last_score_meta["recon_score"],
                last_score_meta["forecast_score"],
                last_score_meta["corr_score"],
            )
            top_contributors, blended_vec = _rank_contributors(recon_loss, forecast_loss, top_k=5)
            similar_history = _get_similar_history(blended_vec, top_k=3)
            hints = _investigation_hints(anomaly_type, top_contributors, last_score_meta["corr_score"])

            recent_alert_history.append({
                "tick": current_tick,
                "dataset": DATASET,
                "is_anomalous": is_anomalous,
                "anomaly_type": anomaly_type,
                "severity": severity_score,
                "top_sensor": top_contributors[0]["sensor"] if top_contributors else "n/a",
                "blended_vec": blended_vec,
            })
                
            # Dynamically compile the dictionary of all sensors based on reality
            sensors_actual = {}
            sensors_forecast = {}
            for i in range(feats_dim):
                sensors_actual[f"s{i}_actual"] = float(actual_sensors[i])
                sensors_forecast[f"s{i}_forecast"] = float(pred_future[i])

            payload = {
                "tick": current_tick,
                "system_loss": fused_score,
                "is_anomalous": is_anomalous,
                "threshold": fused_threshold,
                "dimensions": feats_dim, # Tell React how many DOM elements to spawn
                "sensors": sensors_actual,
                "forecast": sensors_forecast,
                "score_components": {
                    "recon": last_score_meta["recon_score"],
                    "forecast": last_score_meta["forecast_score"],
                    "corr": last_score_meta["corr_score"],
                },
                "alert_explanation": {
                    "severity_score": severity_score,
                    "severity_level": severity_level,
                    "confidence": confidence,
                    "anomaly_type": anomaly_type,
                    "duration_steps": anomaly_streak,
                    "top_contributors": top_contributors,
                    "historical_similar": similar_history,
                    "investigation_hints": hints,
                },
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
