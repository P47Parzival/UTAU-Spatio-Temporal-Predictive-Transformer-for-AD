import asyncio
import copy
import json
import numpy as np
import torch
import torch.nn as nn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from collections import deque
import os
import gc
import time
import math
import sqlite3
from pathlib import Path
from typing import Optional

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

# Phase 4 governance controls
FEEDBACK_DB_PATH = os.getenv("FEEDBACK_DB_PATH", os.path.join("results", "operator_feedback.db"))
DRIFT_MONITOR_INTERVAL_SEC = int(os.getenv("DRIFT_MONITOR_INTERVAL_SEC", "10"))
DRIFT_MIN_POINTS = int(os.getenv("DRIFT_MIN_POINTS", "120"))
DRIFT_Z_THRESHOLD = float(os.getenv("DRIFT_Z_THRESHOLD", "2.5"))
DRIFT_COOLDOWN_SEC = int(os.getenv("DRIFT_COOLDOWN_SEC", "120"))
RETRAIN_MIN_FEEDBACK = int(os.getenv("RETRAIN_MIN_FEEDBACK", "40"))
RETRAIN_MIN_DRIFT_EVENTS = int(os.getenv("RETRAIN_MIN_DRIFT_EVENTS", "3"))
RETRAIN_RECOMMEND_COOLDOWN_SEC = int(os.getenv("RETRAIN_RECOMMEND_COOLDOWN_SEC", "1800"))
CALIBRATE_WARMUP_STEPS = int(os.getenv("CALIBRATE_WARMUP_STEPS", "3"))
CALIBRATE_FINETUNE_STEPS = int(os.getenv("CALIBRATE_FINETUNE_STEPS", "6"))
CALIBRATE_PATIENCE = int(os.getenv("CALIBRATE_PATIENCE", "4"))
CALIBRATE_TOL = float(os.getenv("CALIBRATE_TOL", "1e-4"))
CALIBRATE_MAX_SAMPLES = int(os.getenv("CALIBRATE_MAX_SAMPLES", "48"))

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

feedback_db_lock = asyncio.Lock()
governance_task = None
feedback_counters = {
    "total": 0,
    "confirmed": 0,
    "dismissed": 0,
}
drift_state = {
    "ready": False,
    "triggered": False,
    "events": 0,
    "last_trigger_ts": 0.0,
    "baseline_mean": 0.0,
    "recent_mean": 0.0,
    "z_shift": 0.0,
}
retrain_state = {
    "recommended": False,
    "reason": "",
    "last_recommendation_ts": 0.0,
    "last_applied_ts": 0.0,
}
model_registry = {
    "dataset": DATASET,
    "model_version": "default",
    "checkpoint_path": "",
    "checkpoint_mtime": 0.0,
    "loaded_at_ms": 0,
    "calibration_runs": 0,
    "calibration_rollbacks": 0,
}

class TelemetryData(BaseModel):
    timestamp_ms: int
    sensors: list[float]
    
class SwapRequest(BaseModel):
    dataset: str

class FeedbackPayload(BaseModel):
    was_anomaly: bool
    tick: Optional[int] = None
    note: Optional[str] = None
    severity_level: Optional[str] = None
    confidence: Optional[float] = None
    anomaly_type: Optional[str] = None
    calibrate_requested: bool = False
    system_loss: Optional[float] = None
    threshold: Optional[float] = None

class RetrainAppliedPayload(BaseModel):
    model_version: Optional[str] = None
    note: Optional[str] = None

def _now_ms() -> int:
    return int(time.time() * 1000)

def _init_feedback_db():
    db_path = Path(FEEDBACK_DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS operator_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at_ms INTEGER NOT NULL,
                dataset TEXT NOT NULL,
                tick INTEGER,
                was_anomaly INTEGER NOT NULL,
                severity_level TEXT,
                confidence REAL,
                anomaly_type TEXT,
                note TEXT,
                calibrate_requested INTEGER NOT NULL DEFAULT 0,
                system_loss REAL,
                threshold REAL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_operator_feedback_created_at ON operator_feedback(created_at_ms)"
        )
        conn.commit()

def _load_feedback_counters() -> dict:
    db_path = Path(FEEDBACK_DB_PATH)
    if not db_path.exists():
        return {"total": 0, "confirmed": 0, "dismissed": 0}
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN was_anomaly = 1 THEN 1 ELSE 0 END) AS confirmed,
                SUM(CASE WHEN was_anomaly = 0 THEN 1 ELSE 0 END) AS dismissed
            FROM operator_feedback
            """
        ).fetchone()
    return {
        "total": int(row[0] or 0),
        "confirmed": int(row[1] or 0),
        "dismissed": int(row[2] or 0),
    }

def _save_feedback_row(record: dict) -> int:
    with sqlite3.connect(FEEDBACK_DB_PATH) as conn:
        cursor = conn.execute(
            """
            INSERT INTO operator_feedback (
                created_at_ms, dataset, tick, was_anomaly, severity_level,
                confidence, anomaly_type, note, calibrate_requested,
                system_loss, threshold
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["created_at_ms"],
                record["dataset"],
                record["tick"],
                1 if record["was_anomaly"] else 0,
                record["severity_level"],
                record["confidence"],
                record["anomaly_type"],
                record["note"],
                1 if record["calibrate_requested"] else 0,
                record["system_loss"],
                record["threshold"],
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)

def _load_recent_feedback(limit: int = 20) -> list[dict]:
    db_path = Path(FEEDBACK_DB_PATH)
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, created_at_ms, dataset, tick, was_anomaly, severity_level,
                   confidence, anomaly_type, note, calibrate_requested, system_loss, threshold
            FROM operator_feedback
            ORDER BY created_at_ms DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()

    result = []
    for row in rows:
        result.append({
            "id": int(row[0]),
            "created_at_ms": int(row[1]),
            "dataset": row[2],
            "tick": None if row[3] is None else int(row[3]),
            "was_anomaly": bool(row[4]),
            "severity_level": row[5],
            "confidence": None if row[6] is None else float(row[6]),
            "anomaly_type": row[7],
            "note": row[8],
            "calibrate_requested": bool(row[9]),
            "system_loss": None if row[10] is None else float(row[10]),
            "threshold": None if row[11] is None else float(row[11]),
        })
    return result

def _resolve_checkpoint_and_version(target_ds: str):
    folder = Path(f"checkpoints/{MODEL_NAME}_{target_ds}")
    fallback_ckpt = folder / "model.ckpt"
    registry_file = folder / "registry.json"
    model_version = "default"
    ckpt_path = fallback_ckpt

    if registry_file.exists():
        try:
            with registry_file.open("r", encoding="utf-8") as f:
                registry = json.load(f)
            production = registry.get("production")
            versions = registry.get("versions", {})
            if production and production in versions:
                candidate = versions[production].get("checkpoint", "model.ckpt")
                candidate_path = folder / candidate
                if candidate_path.exists():
                    ckpt_path = candidate_path
                    model_version = production
        except Exception as exc:
            print(f"WARNING: Failed to parse model registry for {target_ds}: {exc}")

    return str(ckpt_path), model_version

def _update_model_registry(dataset: str, model_version: str, checkpoint_path: str):
    global model_registry
    mtime = 0.0
    if checkpoint_path and os.path.exists(checkpoint_path):
        mtime = os.path.getmtime(checkpoint_path)
    model_registry = {
        **model_registry,
        "dataset": dataset,
        "model_version": model_version,
        "checkpoint_path": checkpoint_path,
        "checkpoint_mtime": float(mtime),
        "loaded_at_ms": _now_ms(),
    }

def _reset_ingestion_state(dim: int):
    global last_ingest_timestamp_ms, last_valid_vector, sensor_dropout_streak, last_ingest_meta, last_score_meta, anomaly_streak
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
    recent_alert_history.clear()
    anomaly_streak = 0
    last_score_meta = {
        "recon_score": 0.0,
        "forecast_score": 0.0,
        "corr_score": 0.0,
        "fused_score": 0.0,
        "threshold": FUSED_THRESHOLD_DEFAULT,
    }

def _compute_drift_metrics_from_scores() -> dict:
    fused = np.asarray(score_histories["fused"], dtype=np.float64)
    if fused.size < max(DRIFT_MIN_POINTS, 20):
        return {
            "ready": False,
            "baseline_mean": 0.0,
            "recent_mean": 0.0,
            "z_shift": 0.0,
        }

    window = fused[-DRIFT_MIN_POINTS:]
    midpoint = len(window) // 2
    baseline = window[:midpoint]
    recent = window[midpoint:]
    baseline_mean = float(np.mean(baseline))
    recent_mean = float(np.mean(recent))
    baseline_std = float(np.std(baseline) + 1e-8)
    z_shift = float(abs(recent_mean - baseline_mean) / baseline_std)
    return {
        "ready": True,
        "baseline_mean": baseline_mean,
        "recent_mean": recent_mean,
        "z_shift": z_shift,
    }

def _refresh_retrain_recommendation(force: bool = False):
    now_ts = time.time()
    reasons = []
    if feedback_counters["total"] >= RETRAIN_MIN_FEEDBACK:
        reasons.append(f"operator feedback count reached {feedback_counters['total']}")
    if drift_state["events"] >= RETRAIN_MIN_DRIFT_EVENTS:
        reasons.append(f"drift events reached {drift_state['events']}")

    if reasons:
        cooldown_elapsed = (now_ts - retrain_state["last_recommendation_ts"]) >= RETRAIN_RECOMMEND_COOLDOWN_SEC
        if force or cooldown_elapsed or (not retrain_state["recommended"]):
            retrain_state["recommended"] = True
            retrain_state["reason"] = "; ".join(reasons)
            retrain_state["last_recommendation_ts"] = now_ts
    else:
        retrain_state["recommended"] = False
        retrain_state["reason"] = ""

def _update_drift_state():
    global drift_state
    metrics = _compute_drift_metrics_from_scores()
    drift_state["ready"] = metrics["ready"]
    drift_state["baseline_mean"] = metrics["baseline_mean"]
    drift_state["recent_mean"] = metrics["recent_mean"]
    drift_state["z_shift"] = metrics["z_shift"]

    if not metrics["ready"]:
        drift_state["triggered"] = False
        return

    now_ts = time.time()
    cooldown_elapsed = (now_ts - drift_state["last_trigger_ts"]) >= DRIFT_COOLDOWN_SEC
    should_trigger = metrics["z_shift"] >= DRIFT_Z_THRESHOLD and cooldown_elapsed
    drift_state["triggered"] = bool(should_trigger)
    if should_trigger:
        drift_state["events"] += 1
        drift_state["last_trigger_ts"] = now_ts

    _refresh_retrain_recommendation()

def _set_adaptation_trainable(warmup_only: bool):
    warmup_keys = ("decoder1", "decoder2", "recon_fcn", "forecaster", "log_vars")
    for name, param in model.named_parameters():
        if warmup_only:
            param.requires_grad = any(k in name for k in warmup_keys)
        else:
            param.requires_grad = True

def _build_adaptation_tensors(buffer_snapshot: list[list[float]]):
    if model is None or len(buffer_snapshot) < model.n_window + 1:
        return None, None

    window_np = np.asarray(buffer_snapshot, dtype=np.float64)
    examples = []
    for end_idx in range(model.n_window, window_np.shape[0]):
        history = window_np[end_idx - model.n_window:end_idx]
        target = window_np[end_idx]
        examples.append((history, target))

    if not examples:
        return None, None

    examples = examples[-CALIBRATE_MAX_SAMPLES:]
    history_batch = np.stack([e[0] for e in examples], axis=0)  # (B, W, F)
    target_batch = np.stack([e[1] for e in examples], axis=0)   # (B, F)

    history_tensor = torch.DoubleTensor(history_batch).permute(1, 0, 2).to(device)  # (W, B, F)
    target_tensor = torch.DoubleTensor(target_batch).unsqueeze(0).to(device)         # (1, B, F)
    return history_tensor, target_tensor

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
    if a.ndim != 1:
        a = a.reshape(-1)
    if b.ndim != 1:
        b = b.reshape(-1)
    if a.shape != b.shape:
        return 0.0
    denom = float((np.linalg.norm(a) * np.linalg.norm(b)) + 1e-12)
    return float(np.dot(a, b) / denom)

def _get_similar_history(blended_vec: np.ndarray, top_k: int = 3):
    candidates = []
    blended_arr = np.asarray(blended_vec, dtype=np.float64).reshape(-1)
    for item in recent_alert_history:
        if not item.get("is_anomalous", False):
            continue
        item_vec = np.asarray(item.get("blended_vec", []), dtype=np.float64).reshape(-1)
        if item_vec.shape != blended_arr.shape:
            continue
        sim = _cosine_similarity(blended_arr, item_vec)
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
    ckpt_path, model_version = _resolve_checkpoint_and_version(target_ds)
    
    # Identify target dynamic files
    if target_ds == 'SMD':
        test_arr = np.load(f'processed/{target_ds}/machine-1-1_test.npy')
    elif target_ds == 'MSL':
        test_arr = np.load(f'processed/{target_ds}/C-1_test.npy')
    elif target_ds == 'SMAP':
        test_arr = np.load(f'processed/{target_ds}/A-1_test.npy')
    elif target_ds == 'synthetic':
        test_arr = np.load(f'processed/{target_ds}/test.npy')
    else:
        raise ValueError(f"Unsupported dataset for STP server: {target_ds}")
        
    feats = test_arr.shape[1]
    
    # Initialize Model fundamentally equivalent to Training initialization
    m = STP_TranAD(feats).double().to(device)
    opt = torch.optim.AdamW(m.parameters(), lr=1e-5, weight_decay=1e-5)
    
    if os.path.exists(ckpt_path):
        checkpoint = torch.load(ckpt_path, map_location=device, weights_only=False)
        m.load_state_dict(checkpoint['model_state_dict'])
        if 'optimizer_state_dict' in checkpoint:
            try:
                opt.load_state_dict(checkpoint['optimizer_state_dict'])
            except Exception as exc:
                print(f"WARNING: Optimizer state incompatible, continuing with fresh optimizer: {exc}")
        print(f"Pre-trained checkpoint loaded successfully from {ckpt_path}.")
    else:
        print("WARNING: Checkpoint not found. Running with uninitialized random weights.")
    m.eval()
    _update_model_registry(target_ds, model_version, ckpt_path)
    return m, opt, feats

async def _governance_monitor_loop():
    while True:
        await asyncio.sleep(DRIFT_MONITOR_INTERVAL_SEC)
        _update_drift_state()
        _refresh_retrain_recommendation()

@app.on_event("startup")
async def startup_event():
    global model, optimizer, feats_dim, governance_task
    _init_feedback_db()
    feedback_counters.update(_load_feedback_counters())
    model, optimizer, feats_dim = init_model()
    _reset_ingestion_state(feats_dim)
    _refresh_retrain_recommendation(force=True)
    governance_task = asyncio.create_task(_governance_monitor_loop())
    
    # Pre-fill buffer with mean zero-state to prevent startup crashes
    for _ in range(101):
        live_buffer.append([0.0] * feats_dim)

@app.on_event("shutdown")
async def shutdown_event():
    global governance_task
    if governance_task is None:
        return
    governance_task.cancel()
    try:
        await governance_task
    except asyncio.CancelledError:
        pass
    governance_task = None

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
    _update_drift_state()
    _refresh_retrain_recommendation()
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
        "governance": {
            "drift": drift_state,
            "retraining": retrain_state,
            "model_registry": model_registry,
            "feedback": feedback_counters,
        },
    }

@app.post("/change_dataset")
async def trigger_dataset_swap(req: SwapRequest):
    global DATASET, model, optimizer, feats_dim
    if req.dataset not in ['SMD', 'MSL', 'SMAP', 'synthetic']:
        return {"error": "Invalid Dataset"}
    if req.dataset == DATASET:
        return {"status": "noop", "new_dataset": DATASET, "new_dim": feats_dim}

    async with model_lock:
        print(f"--- INITIATING HOT-SWAP TO {req.dataset} ---")
        prev_dataset = DATASET
        prev_model = model
        prev_optimizer = optimizer
        prev_feats = feats_dim

        try:
            new_model, new_optimizer, new_feats = init_model(target_ds=req.dataset)
        except Exception as exc:
            print(f"Dataset swap failed, keeping previous model: {exc}")
            DATASET = prev_dataset
            model = prev_model
            optimizer = prev_optimizer
            feats_dim = prev_feats
            return {"error": "swap_failed", "detail": str(exc), "active_dataset": DATASET}

        DATASET = req.dataset
        model = new_model
        optimizer = new_optimizer
        feats_dim = new_feats
        _reset_ingestion_state(feats_dim)
        
        # Flush baseline frames to buffer
        live_buffer.clear()
        for _ in range(101):
            live_buffer.append([0.0] * feats_dim)

        if prev_model is not None:
            del prev_model
        if prev_optimizer is not None:
            del prev_optimizer
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            
    return {
        "status": "success",
        "new_dataset": DATASET,
        "new_dim": feats_dim,
        "model_version": model_registry["model_version"],
    }

@app.post("/calibrate")
async def trigger_online_learning():
    """Adaptive local fine-tune with rollback guards for drift events."""
    if model is None:
        return {"status": "unavailable", "detail": "model not initialized"}

    async with model_lock:
        buffer_snapshot = list(live_buffer)
        if len(buffer_snapshot) < model.n_window + 1:
            return {"status": "buffering"}

        history_tensor, target_tensor = _build_adaptation_tensors(buffer_snapshot)
        if history_tensor is None or target_tensor is None:
            return {"status": "buffering"}

        print("[ADAPTIVE CALIBRATION] Running guarded online adaptation...")
        mse = nn.MSELoss()
        model_backup = copy.deepcopy(model.state_dict())
        optimizer_backup = copy.deepcopy(optimizer.state_dict())

        with torch.no_grad():
            _, x2_base, forecast_base = model(history_tensor)
            initial_recon = mse(x2_base, target_tensor)
            initial_forecast = mse(forecast_base[0], target_tensor[0])
            initial_loss = float((0.7 * initial_recon + 0.3 * initial_forecast).item())

        loss_trace = []
        best_loss = initial_loss
        stale_steps = 0
        diverged = False
        early_stop = False

        model.train()
        for _, steps, warmup_only in [
            ("warmup", CALIBRATE_WARMUP_STEPS, True),
            ("finetune", CALIBRATE_FINETUNE_STEPS, False),
        ]:
            _set_adaptation_trainable(warmup_only)
            for _ in range(steps):
                optimizer.zero_grad()
                _, x2, forecast = model(history_tensor)
                recon_loss = mse(x2, target_tensor)
                forecast_loss = mse(forecast[0], target_tensor[0])
                loss = (0.7 * recon_loss) + (0.3 * forecast_loss)
                if not torch.isfinite(loss):
                    diverged = True
                    break
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                optimizer.step()

                current_loss = float(loss.item())
                loss_trace.append(current_loss)
                if current_loss + CALIBRATE_TOL < best_loss:
                    best_loss = current_loss
                    stale_steps = 0
                else:
                    stale_steps += 1
                if stale_steps >= CALIBRATE_PATIENCE:
                    early_stop = True
                    break
            if diverged or early_stop:
                break

        _set_adaptation_trainable(False)
        model.eval()

        final_loss = loss_trace[-1] if loss_trace else initial_loss
        rollback = diverged or (not np.isfinite(final_loss)) or (final_loss > (initial_loss * 1.15))

        if rollback:
            model.load_state_dict(model_backup)
            optimizer.load_state_dict(optimizer_backup)
            model_registry["calibration_rollbacks"] += 1
            status = "rollback"
        else:
            model_registry["calibration_runs"] += 1
            status = "calibrated"

    return {
        "status": status,
        "initial_loss": initial_loss,
        "final_loss": float(final_loss),
        "best_loss": float(best_loss),
        "steps": len(loss_trace),
        "early_stop": early_stop,
        "rollback": rollback,
    }

@app.post("/feedback")
async def submit_operator_feedback(payload: FeedbackPayload):
    note = (payload.note or "").strip()
    if len(note) > 512:
        note = note[:512]

    record = {
        "created_at_ms": _now_ms(),
        "dataset": DATASET,
        "tick": payload.tick,
        "was_anomaly": bool(payload.was_anomaly),
        "severity_level": payload.severity_level,
        "confidence": payload.confidence,
        "anomaly_type": payload.anomaly_type,
        "note": note,
        "calibrate_requested": bool(payload.calibrate_requested),
        "system_loss": payload.system_loss,
        "threshold": payload.threshold,
    }

    async with feedback_db_lock:
        row_id = await asyncio.to_thread(_save_feedback_row, record)
        latest_counts = await asyncio.to_thread(_load_feedback_counters)
    feedback_counters.update(latest_counts)
    _refresh_retrain_recommendation(force=False)

    return {
        "status": "recorded",
        "id": row_id,
        "feedback": feedback_counters,
        "retraining": retrain_state,
    }

@app.get("/feedback/summary")
async def feedback_summary(limit: int = 20):
    capped_limit = max(1, min(100, int(limit)))
    recent = await asyncio.to_thread(_load_recent_feedback, capped_limit)
    return {
        "totals": feedback_counters,
        "recent": recent,
    }

@app.get("/retrain/plan")
async def retrain_plan():
    _refresh_retrain_recommendation(force=False)
    return {
        "recommended": retrain_state["recommended"],
        "reason": retrain_state["reason"],
        "feedback_totals": feedback_counters,
        "drift": drift_state,
        "model_registry": model_registry,
    }

@app.post("/retrain/mark_applied")
async def retrain_mark_applied(payload: RetrainAppliedPayload):
    retrain_state["recommended"] = False
    retrain_state["reason"] = ""
    retrain_state["last_applied_ts"] = time.time()
    if payload.model_version:
        model_registry["model_version"] = payload.model_version
    return {
        "status": "acknowledged",
        "last_applied_ts": retrain_state["last_applied_ts"],
        "model_registry": model_registry,
        "note": payload.note,
    }

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
            _update_drift_state()
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
