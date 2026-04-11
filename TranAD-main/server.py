import asyncio
import copy
import json
import numpy as np
import torch
import torch.nn as nn
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from collections import deque
import os
from dotenv import load_dotenv
from src.online_finetuner import run_finetune, FT_LR

_SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
_WORKSPACE_ROOT = os.path.dirname(_SERVER_DIR)
load_dotenv(os.path.join(_SERVER_DIR, ".env"))
_frontend_env_path = os.path.join(_WORKSPACE_ROOT, "Frontend", ".env")
if os.path.exists(_frontend_env_path):
    # Allows local dev fallback when API keys are staged in Frontend/.env.
    load_dotenv(_frontend_env_path, override=False)

import gc
import time
import math
import sqlite3
import csv
import textwrap
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional
try:
    from aiokafka import AIOKafkaConsumer
except ImportError:
    AIOKafkaConsumer = None
try:
    from influxdb_client import InfluxDBClient, Point, WritePrecision
except ImportError:
    InfluxDBClient = None
    Point = None
    WritePrecision = None

from src.models import STP_TranAD
from src.rl_policy_manager import RLPolicyManager

app = FastAPI(title="STP-TranAD Streaming Inference Engine")


def _env_flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}

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
ft_optimizer = None  # Separate low-LR optimizer for feedback-driven fine-tuning
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
FEEDBACK_DB_PATH = os.getenv("FEEDBACK_DB_PATH", os.path.join(_SERVER_DIR, "results", "operator_feedback.db"))
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

# ── Twilio WhatsApp Pager Alert ──────────────────────────────────────────
TWILIO_ACCOUNT_SID   = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN    = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_WHATSAPP = os.getenv("TWILIO_FROM_WHATSAPP", "whatsapp:+14155238886")
TWILIO_TO_NUMBERS    = [n.strip() for n in os.getenv("TWILIO_TO_WHATSAPP", "").split(",") if n.strip()]
TWILIO_COOLDOWN      = int(os.getenv("TWILIO_ALERT_COOLDOWN_SEC", "30"))
TWILIO_MIN_SEV       = os.getenv("TWILIO_MIN_SEVERITY", "warning")  # info | warning | critical

# Optional LLM-backed SOP generation
SOP_LLM_PROVIDER = os.getenv("SOP_LLM_PROVIDER", "groq").strip().lower()
SOP_OPENAI_API_KEY = os.getenv("SOP_OPENAI_API_KEY", os.getenv("OPENAI_API_KEY", "")).strip()
SOP_OPENAI_MODEL = os.getenv("SOP_OPENAI_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini")).strip()
SOP_OPENAI_ENDPOINT = os.getenv("SOP_OPENAI_ENDPOINT", "https://api.openai.com/v1/chat/completions").strip()
SOP_GROQ_API_KEY = os.getenv("SOP_GROQ_API_KEY", os.getenv("GROQ_API_KEY", os.getenv("VITE_GROQ_API_KEY", ""))).strip()
SOP_GROQ_MODEL = os.getenv("SOP_GROQ_MODEL", "llama-3.3-70b-versatile").strip()
SOP_GROQ_ENDPOINT = os.getenv("SOP_GROQ_ENDPOINT", "https://api.groq.com/openai/v1/chat/completions").strip()
SOP_LLM_TIMEOUT_SEC = float(os.getenv("SOP_LLM_TIMEOUT_SEC", "20"))
SOP_HISTORY_PATH = os.getenv("SOP_HISTORY_PATH", os.path.join(_SERVER_DIR, "results", "sop_history.ndjson"))
SENSOR_NAME_MAP_PATH = os.getenv("SENSOR_NAME_MAP_PATH", os.path.join(_SERVER_DIR, "results", "sensor_name_map.json"))

# Kafka streaming controls
KAFKA_CONSUMER_ENABLED = _env_flag("KAFKA_CONSUMER_ENABLED", "true")
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:29092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "telemetry-stream")
KAFKA_GROUP_ID = os.getenv("KAFKA_GROUP_ID", "stp-tranad-consumer")
KAFKA_AUTO_OFFSET_RESET = os.getenv("KAFKA_AUTO_OFFSET_RESET", "latest")
KAFKA_RECONNECT_BACKOFF_SEC = float(os.getenv("KAFKA_RECONNECT_BACKOFF_SEC", "5.0"))

# Phase 5 InfluxDB controls
INFLUX_ENABLED = _env_flag("INFLUX_ENABLED")
INFLUX_URL = os.getenv("INFLUX_URL", "http://127.0.0.1:8086")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "")
INFLUX_ORG = os.getenv("INFLUX_ORG", "catch-org")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "catch-telemetry")
INFLUX_BATCH_SIZE = int(os.getenv("INFLUX_BATCH_SIZE", "100"))
INFLUX_FLUSH_INTERVAL_SEC = float(os.getenv("INFLUX_FLUSH_INTERVAL_SEC", "2.0"))
INFLUX_QUEUE_MAXSIZE = int(os.getenv("INFLUX_QUEUE_MAXSIZE", "5000"))
INFLUX_DEADLETTER_PATH = os.getenv("INFLUX_DEADLETTER_PATH", os.path.join("results", "influx_deadletter.ndjson"))

# Phase 1 rollout flags
FEATURE_ANOMALY_SOURCE_TAB = _env_flag("FEATURE_ANOMALY_SOURCE_TAB", "true")
FEATURE_DATA_SOURCE_TAB = _env_flag("FEATURE_DATA_SOURCE_TAB", "true")
FEATURE_RL_POLICY_SUGGESTIONS = _env_flag("FEATURE_RL_POLICY_SUGGESTIONS")
SOURCE_REGISTRY_PATH = os.getenv("SOURCE_REGISTRY_PATH", os.path.join(_SERVER_DIR, "results", "data_sources.json"))

# Phase 8 RL suggestion-only controls
RL_POLICY_STATE_PATH = os.getenv("RL_POLICY_STATE_PATH", os.path.join("results", "rl_policy_state.json"))
RL_POLICY_LEARNING_RATE = float(os.getenv("RL_POLICY_LEARNING_RATE", "0.12"))
RL_POLICY_DISCOUNT = float(os.getenv("RL_POLICY_DISCOUNT", "0.90"))
RL_POLICY_EPSILON = float(os.getenv("RL_POLICY_EPSILON", "0.05"))

# Phase 9 guarded apply controls
POLICY_APPLY_MAX_THRESHOLD_DELTA = float(os.getenv("POLICY_APPLY_MAX_THRESHOLD_DELTA", "0.20"))
POLICY_APPLY_MAX_RETRAIN_FEEDBACK_DELTA = int(os.getenv("POLICY_APPLY_MAX_RETRAIN_FEEDBACK_DELTA", "20"))
POLICY_APPLY_MAX_DRIFT_Z_DELTA = float(os.getenv("POLICY_APPLY_MAX_DRIFT_Z_DELTA", "0.50"))
POLICY_CANARY_MIN_POINTS = int(os.getenv("POLICY_CANARY_MIN_POINTS", "60"))
POLICY_CANARY_MAX_ALERT_RATE_DELTA = float(os.getenv("POLICY_CANARY_MAX_ALERT_RATE_DELTA", "0.20"))

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
anomaly_event_history = deque(maxlen=2000)
anomaly_event_seq = 0
anomaly_streak = 0
runtime_policy = {
    "fused_threshold_default": float(FUSED_THRESHOLD_DEFAULT),
    "retrain_min_feedback": int(RETRAIN_MIN_FEEDBACK),
    "drift_z_threshold": float(DRIFT_Z_THRESHOLD),
}
policy_apply_history = deque(maxlen=200)
policy_apply_seq = 0
policy_apply_state = {
    "enabled": FEATURE_RL_POLICY_SUGGESTIONS,
    "last_apply_id": "",
    "last_apply_status": "idle",
    "last_apply_reason": "",
    "last_apply_ts": 0,
    "last_rollback_ts": 0,
    "active_policy": dict(runtime_policy),
}
last_score_meta = {
    "recon_score": 0.0,
    "forecast_score": 0.0,
    "corr_score": 0.0,
    "recon_z": 0.0,
    "forecast_z": 0.0,
    "corr_z": 0.0,
    "fused_score": 0.0,
    "threshold": float(runtime_policy["fused_threshold_default"]),
}
sensor_name_map_cache: dict[str, dict[str, str]] = {}
sensor_name_map_loaded_ms = 0

feedback_db_lock = asyncio.Lock()
governance_task = None
kafka_consumer_task = None
influx_writer_task = None
influx_queue = None
_twilio_last_sent_ts: float = 0.0  # cooldown tracker for WhatsApp alerts
rl_policy_manager = None
rl_policy_last_suggestion = None
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
manual_anomaly_state = {
    "pending_ticks": 0,
    "last_trigger_ts": 0.0,
    "last_reason": "",
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
kafka_state = {
    "enabled": KAFKA_CONSUMER_ENABLED,
    "connected": False,
    "bootstrap_servers": KAFKA_BOOTSTRAP_SERVERS,
    "topic": KAFKA_TOPIC,
    "group_id": KAFKA_GROUP_ID,
    "received_count": 0,
    "ingested_count": 0,
    "dropped_messages": 0,
    "deserialize_errors": 0,
    "last_message_ts_ms": None,
    "last_error": "",
}
influx_state = {
    "enabled": INFLUX_ENABLED,
    "configured": bool(INFLUX_TOKEN and INFLUX_ORG and INFLUX_BUCKET),
    "connected": False,
    "url": INFLUX_URL,
    "org": INFLUX_ORG,
    "bucket": INFLUX_BUCKET,
    "written_points": 0,
    "dropped_points": 0,
    "write_errors": 0,
    "queue_size": 0,
    "last_write_ms": None,
    "last_error": "",
}

source_registry_lock = asyncio.Lock()
source_registry = {
    "items": [],
    "next_id": 1,
    "updated_at_ms": int(time.time() * 1000),
}
source_runtime = {
    "active_source_id": None,
    "last_health_check_ms": 0,
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
    raw_window: Optional[list] = None  # (n_window x n_feats) flattened — stored as BLOB for fine-tuning

class RetrainAppliedPayload(BaseModel):
    model_version: Optional[str] = None
    note: Optional[str] = None

class ManualAnomalyTriggerPayload(BaseModel):
    ticks: int = Field(default=1, ge=1, le=20)
    reason: Optional[str] = None

class RLRewardPayload(BaseModel):
    suggestion_id: str
    reward: float
    note: Optional[str] = None

class RLApplyPayload(BaseModel):
    suggestion_id: str
    mode: str = "canary"
    canary_points: int = 120
    note: Optional[str] = None

class RLRollbackPayload(BaseModel):
    apply_id: Optional[str] = None
    note: Optional[str] = None

class SourceCreatePayload(BaseModel):
    name: str
    protocol: str
    endpoint: str
    topic: Optional[str] = None
    dataset: Optional[str] = None
    expected_dimensions: Optional[int] = None
    enabled: bool = True
    is_active: bool = False
    notes: Optional[str] = None
    mapping: dict[str, Any] = {}
    auth: Optional[dict[str, Any]] = None

class SourceUpdatePayload(BaseModel):
    name: Optional[str] = None
    protocol: Optional[str] = None
    endpoint: Optional[str] = None
    topic: Optional[str] = None
    dataset: Optional[str] = None
    expected_dimensions: Optional[int] = None
    enabled: Optional[bool] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None
    mapping: Optional[dict[str, Any]] = None
    auth: Optional[dict[str, Any]] = None

class SourceMappingValidatePayload(BaseModel):
    sample: Optional[dict[str, Any]] = None

class SOPRequest(BaseModel):
    objective: str = "Prevent recurrence at source"
    constraints: list[str] = Field(default_factory=list)
    max_steps: int = 8
    force_llm: bool = False
    model: Optional[str] = None

def _now_ms() -> int:
    return int(time.time() * 1000)

def _safe_float(value):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isfinite(f):
        return f
    return None

def _model_dump(payload: BaseModel, **kwargs) -> dict[str, Any]:
    if hasattr(payload, "model_dump"):
        return payload.model_dump(**kwargs)
    return payload.dict(**kwargs)

def _load_sensor_name_map(force: bool = False) -> dict[str, dict[str, str]]:
    global sensor_name_map_cache, sensor_name_map_loaded_ms
    if sensor_name_map_cache and not force:
        return sensor_name_map_cache

    path = Path(SENSOR_NAME_MAP_PATH)
    if not path.exists():
        sensor_name_map_cache = {}
        sensor_name_map_loaded_ms = _now_ms()
        return sensor_name_map_cache

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        sensor_name_map_cache = {}
        sensor_name_map_loaded_ms = _now_ms()
        return sensor_name_map_cache

    normalized: dict[str, dict[str, str]] = {}
    if isinstance(raw, dict):
        for ds_name, ds_mapping in raw.items():
            if not isinstance(ds_mapping, dict):
                continue
            ds_key = str(ds_name).strip()
            if not ds_key:
                continue
            inner: dict[str, str] = {}
            for sensor_key, sensor_label in ds_mapping.items():
                k = str(sensor_key).strip()
                label = str(sensor_label).strip()
                if not k or not label:
                    continue
                inner[k] = label
                if k.startswith("s"):
                    inner[k[1:]] = label
            normalized[ds_key] = inner
            normalized[ds_key.upper()] = inner

    sensor_name_map_cache = normalized
    sensor_name_map_loaded_ms = _now_ms()
    return sensor_name_map_cache

def _parse_smd_anomalous_sensor_ids(machine_id: str) -> set[int]:
    result: set[int] = set()
    path = Path(_SERVER_DIR) / "data" / "SMD" / "interpretation_label" / f"{machine_id}.txt"
    if not path.exists():
        return result
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return result
    for line in lines:
        _window, sep, sensor_block = line.partition(":")
        if sep != ":":
            continue
        for token in sensor_block.split(","):
            t = token.strip()
            if not t:
                continue
            try:
                result.add(int(t))
            except ValueError:
                continue
    return result

def _parse_telemanom_classes(spacecraft: str, chan_id: str) -> list[str]:
    path = Path(_SERVER_DIR) / "data" / "SMAP_MSL" / "labeled_anomalies.csv"
    if not path.exists():
        return []
    found: list[str] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if str(row.get("spacecraft", "")).strip().upper() != spacecraft.upper():
                    continue
                if str(row.get("chan_id", "")).strip() != chan_id:
                    continue
                class_raw = str(row.get("class", "")).strip()
                class_raw = class_raw.strip("[]")
                parts = [p.strip().strip("'\"") for p in class_raw.split(",") if p.strip()]
                for item in parts:
                    if item and item not in found:
                        found.append(item)
                break
    except Exception:
        return []
    return found

def _build_real_dataset_sensor_map(dataset: str, source_id: str, feature_count: int) -> dict[str, str]:
    ds = str(dataset or "").strip()
    src = str(source_id or "").strip()
    if feature_count <= 0:
        return {}

    labels: dict[str, str] = {}
    if ds == "SMD":
        hist_anom_ids = _parse_smd_anomalous_sensor_ids(src)
        for idx in range(feature_count):
            sensor_num = idx + 1
            label = f"{src} sensor {sensor_num:02d}"
            if sensor_num in hist_anom_ids:
                label += " (historical anomaly-linked)"
            labels[f"s{idx}"] = label
    elif ds in {"SMAP", "MSL"}:
        classes = _parse_telemanom_classes(ds, src)
        suffix = ""
        if classes:
            suffix = f" ({'/'.join(classes)})"
        for idx in range(feature_count):
            labels[f"s{idx}"] = f"{ds} {src} telemetry {idx + 1:02d}{suffix}"
    elif ds == "ESP32":
        for idx in range(feature_count):
            labels[f"s{idx}"] = f"ESP32 channel {idx + 1:02d}"
    elif ds == "synthetic":
        for idx in range(feature_count):
            labels[f"s{idx}"] = f"Synthetic signal {idx + 1:02d}"
    else:
        for idx in range(feature_count):
            labels[f"s{idx}"] = f"{ds} feature {idx + 1:02d}"

    return labels

def _register_runtime_sensor_name_map(dataset: str, source_id: str, feature_count: int) -> None:
    if feature_count <= 0:
        return
    mapping = _load_sensor_name_map(force=False)
    ds = str(dataset or "").strip()
    if not ds:
        return
    src = str(source_id or "").strip() or _DATASET_FEATURE_SOURCE.get(ds, "")
    generated = _build_real_dataset_sensor_map(ds, src, feature_count)
    if not generated:
        return

    source_key = f"{ds.upper()}:{src}"
    combined = dict(generated)
    existing_source_map = mapping.get(source_key, {})
    if isinstance(existing_source_map, dict):
        combined.update(existing_source_map)
    mapping[source_key] = combined

    ds_key = ds.upper()
    existing_ds_map = mapping.get(ds_key)
    if not isinstance(existing_ds_map, dict) or not existing_ds_map:
        mapping[ds_key] = dict(generated)

    global sensor_name_map_cache, sensor_name_map_loaded_ms
    sensor_name_map_cache = mapping
    sensor_name_map_loaded_ms = _now_ms()

def _sensor_label(sensor_name: str, dataset: Optional[str] = None, source_id: Optional[str] = None) -> str:
    mapping = _load_sensor_name_map(force=False)
    ds = str(dataset or DATASET).strip()
    src = str(source_id or model_registry.get("feature_source_id", "")).strip()
    candidate_maps = []
    if ds and src:
        candidate_maps.append(mapping.get(f"{ds}:{src}"))
        candidate_maps.append(mapping.get(f"{ds.upper()}:{src}"))
    candidate_maps.append(mapping.get(ds))
    candidate_maps.append(mapping.get(ds.upper()))

    sensor_key = str(sensor_name).strip()
    if not sensor_key:
        return sensor_name
    for ds_map in candidate_maps:
        if isinstance(ds_map, dict):
            if sensor_key in ds_map:
                return str(ds_map[sensor_key])
            if sensor_key.startswith("s") and sensor_key[1:] in ds_map:
                return str(ds_map[sensor_key[1:]])
    return sensor_name

def _append_sop_history_record(record: dict[str, Any]) -> None:
    path = Path(SOP_HISTORY_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=True) + "\n")

def _append_influx_deadletter(batch: list[dict], reason: str):
    path = Path(INFLUX_DEADLETTER_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at_ms": _now_ms(),
        "reason": reason,
        "count": len(batch),
        "records": batch,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")

_SOURCE_PROTOCOLS = {"kafka", "mqtt", "opcua", "http"}
_SOURCE_DATASETS = {"SMD", "MSL", "SMAP", "ESP32", "synthetic"}
_SOURCE_SECRET_KEYS = ("token", "password", "secret", "key")
_MODEL_DATASET_ALIASES = {
    "ESP32": "synthetic",
}
_DATASET_FEATURE_SOURCE = {
    "SMD": "machine-1-1",
    "MSL": "C-1",
    "SMAP": "A-1",
    "synthetic": "synthetic",
    "ESP32": "esp32-replay",
}

def _mask_secret(value: Any) -> str:
    s = str(value)
    if len(s) <= 4:
        return "****"
    return ("*" * max(4, len(s) - 4)) + s[-4:]

def _sanitize_auth(auth: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(auth, dict):
        return {}
    sanitized = {}
    for k, v in auth.items():
        if v is None:
            continue
        key_l = str(k).lower()
        if isinstance(v, str):
            value = v.strip()
            if value == "":
                continue
        else:
            value = v
        sanitized[str(k)] = value
    return sanitized

def _public_source_item(item: dict[str, Any]) -> dict[str, Any]:
    out = dict(item)
    auth = out.get("auth")
    if isinstance(auth, dict):
        masked = {}
        for k, v in auth.items():
            key_l = str(k).lower()
            if any(secret_key in key_l for secret_key in _SOURCE_SECRET_KEYS):
                masked[str(k)] = _mask_secret(v)
            else:
                masked[str(k)] = v
        out["auth"] = masked
    else:
        out["auth"] = {}
    return out

def _normalize_dataset_name(dataset: Optional[str]) -> Optional[str]:
    if dataset is None:
        return None
    text = str(dataset).strip()
    if text == "":
        return None
    if text.lower() == "synthetic":
        return "synthetic"
    up = text.upper()
    return up

def _runtime_dataset_alias(dataset: str) -> str:
    return _MODEL_DATASET_ALIASES.get(dataset, dataset)

def _validate_source_payload(raw: dict[str, Any], partial: bool) -> tuple[dict[str, Any], list[str]]:
    normalized = {}
    errors = []

    if (not partial) or ("name" in raw):
        name = str(raw.get("name", "")).strip()
        if not name:
            errors.append("name is required")
        else:
            normalized["name"] = name[:96]

    if (not partial) or ("protocol" in raw):
        protocol = str(raw.get("protocol", "")).strip().lower()
        if protocol not in _SOURCE_PROTOCOLS:
            errors.append(f"protocol must be one of: {', '.join(sorted(_SOURCE_PROTOCOLS))}")
        else:
            normalized["protocol"] = protocol

    if (not partial) or ("endpoint" in raw):
        endpoint = str(raw.get("endpoint", "")).strip()
        if not endpoint:
            errors.append("endpoint is required")
        else:
            normalized["endpoint"] = endpoint[:512]

    if "topic" in raw:
        topic_raw = raw.get("topic")
        topic = None if topic_raw is None else str(topic_raw).strip()
        normalized["topic"] = topic[:128] if topic else None
    elif not partial:
        normalized["topic"] = None

    if "dataset" in raw:
        dataset = _normalize_dataset_name(raw.get("dataset"))
        if dataset is not None and dataset not in _SOURCE_DATASETS:
            errors.append("dataset must be one of SMD, MSL, SMAP, ESP32, synthetic")
        else:
            normalized["dataset"] = dataset
    elif not partial:
        normalized["dataset"] = None

    if "expected_dimensions" in raw:
        expected_raw = raw.get("expected_dimensions")
        if expected_raw is None or expected_raw == "":
            normalized["expected_dimensions"] = None
        else:
            try:
                expected = int(expected_raw)
                if expected <= 0:
                    raise ValueError()
                normalized["expected_dimensions"] = expected
            except Exception:
                errors.append("expected_dimensions must be a positive integer")
    elif not partial:
        normalized["expected_dimensions"] = None

    if (not partial) or ("enabled" in raw):
        normalized["enabled"] = bool(raw.get("enabled", True))

    if "is_active" in raw:
        normalized["is_active"] = bool(raw.get("is_active", False))
    elif not partial:
        normalized["is_active"] = False

    if "notes" in raw:
        note_raw = raw.get("notes")
        note = None if note_raw is None else str(note_raw).strip()
        normalized["notes"] = note[:512] if note else None
    elif not partial:
        normalized["notes"] = None

    if "mapping" in raw:
        mapping = raw.get("mapping")
        if mapping is None:
            normalized["mapping"] = {}
        elif isinstance(mapping, dict):
            normalized["mapping"] = mapping
        else:
            errors.append("mapping must be an object")
    elif not partial:
        normalized["mapping"] = {}

    if "auth" in raw:
        auth = raw.get("auth")
        if auth is None:
            normalized["auth"] = {}
        elif isinstance(auth, dict):
            normalized["auth"] = _sanitize_auth(auth)
        else:
            errors.append("auth must be an object")
    elif not partial:
        normalized["auth"] = {}

    return normalized, errors

def _save_source_registry() -> None:
    path = Path(SOURCE_REGISTRY_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "items": source_registry.get("items", []),
        "next_id": int(source_registry.get("next_id", 1)),
        "updated_at_ms": int(source_registry.get("updated_at_ms", _now_ms())),
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

def _load_source_registry() -> None:
    path = Path(SOURCE_REGISTRY_PATH)
    if not path.exists():
        source_registry["items"] = []
        source_registry["next_id"] = 1
        source_registry["updated_at_ms"] = _now_ms()
        source_runtime["active_source_id"] = None
        return

    try:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        print(f"WARNING: Failed to load source registry ({SOURCE_REGISTRY_PATH}): {exc}")
        source_registry["items"] = []
        source_registry["next_id"] = 1
        source_registry["updated_at_ms"] = _now_ms()
        source_runtime["active_source_id"] = None
        return

    items = payload.get("items", [])
    if not isinstance(items, list):
        items = []

    normalized_items = []
    max_id = 0
    active_source_id = None
    for item in items:
        if not isinstance(item, dict):
            continue
        source_id = int(item.get("id", 0))
        if source_id <= 0:
            continue
        max_id = max(max_id, source_id)
        entry = {
            "id": source_id,
            "name": str(item.get("name", f"source-{source_id}")),
            "protocol": str(item.get("protocol", "kafka")).lower(),
            "endpoint": str(item.get("endpoint", "")),
            "topic": item.get("topic"),
            "dataset": _normalize_dataset_name(item.get("dataset")),
            "expected_dimensions": item.get("expected_dimensions"),
            "enabled": bool(item.get("enabled", True)),
            "is_active": bool(item.get("is_active", False)),
            "notes": item.get("notes"),
            "mapping": item.get("mapping") if isinstance(item.get("mapping"), dict) else {},
            "auth": _sanitize_auth(item.get("auth") if isinstance(item.get("auth"), dict) else {}),
            "created_at_ms": int(item.get("created_at_ms", _now_ms())),
            "updated_at_ms": int(item.get("updated_at_ms", _now_ms())),
        }
        if entry["is_active"] and active_source_id is None:
            active_source_id = source_id
        normalized_items.append(entry)

    if active_source_id is None and normalized_items:
        normalized_items[0]["is_active"] = True
        active_source_id = int(normalized_items[0]["id"])

    for entry in normalized_items:
        entry["is_active"] = int(entry["id"]) == int(active_source_id) if active_source_id is not None else False

    source_registry["items"] = normalized_items
    source_registry["next_id"] = max(int(payload.get("next_id", max_id + 1)), max_id + 1)
    source_registry["updated_at_ms"] = int(payload.get("updated_at_ms", _now_ms()))
    source_runtime["active_source_id"] = active_source_id

def _set_active_source(source_id: int) -> None:
    active_id = None
    for item in source_registry["items"]:
        is_active = int(item.get("id", -1)) == int(source_id)
        item["is_active"] = is_active
        if is_active:
            active_id = int(item["id"])
    source_runtime["active_source_id"] = active_id

def _find_source_by_id(source_id: int) -> Optional[dict[str, Any]]:
    for item in source_registry["items"]:
        if int(item.get("id", -1)) == int(source_id):
            return item
    return None

def _extract_nested_path(sample: dict[str, Any], path: str) -> Any:
    if not path:
        return None
    current: Any = sample
    for part in path.split('.'):
        key = part.strip()
        if not key:
            return None
        if isinstance(current, dict) and key in current:
            current = current[key]
            continue
        return None
    return current

def _source_health_snapshot(source: dict[str, Any]) -> dict[str, Any]:
    now = _now_ms()
    source_runtime["last_health_check_ms"] = now
    protocol = str(source.get("protocol", "kafka"))
    enabled = bool(source.get("enabled", True))
    dataset = source.get("dataset")
    dataset_matches = (dataset is None) or (dataset == DATASET)
    last_message_ts = kafka_state.get("last_message_ts_ms")
    message_age_ms = None
    if isinstance(last_message_ts, int):
        message_age_ms = max(0, now - int(last_message_ts))

    drop_total = int(ingest_stats.get("dropped_dimension_mismatch", 0) + ingest_stats.get("dropped_invalid_timestamp", 0))
    total = int(ingest_stats.get("total", 0))
    drop_ratio = float(drop_total / max(1, total))

    status = "offline"
    reason = "source_disabled"
    if enabled:
        if not dataset_matches:
            status = "idle"
            reason = "dataset_not_active"
        elif protocol == "kafka":
            if not kafka_state.get("connected", False):
                status = "offline"
                reason = "kafka_not_connected"
            elif message_age_ms is not None and message_age_ms > 15000:
                status = "degraded"
                reason = "stale_kafka_messages"
            elif drop_ratio >= 0.30:
                status = "degraded"
                reason = "high_drop_ratio"
            elif total <= 0:
                status = "waiting"
                reason = "awaiting_ingest"
            else:
                status = "healthy"
                reason = "streaming"
        else:
            if total <= 0:
                status = "waiting"
                reason = "awaiting_ingest"
            elif drop_ratio >= 0.30:
                status = "degraded"
                reason = "high_drop_ratio"
            else:
                status = "healthy"
                reason = "ingesting"

    return {
        "source_id": int(source.get("id", -1)),
        "source_name": source.get("name", ""),
        "protocol": protocol,
        "enabled": enabled,
        "dataset": dataset,
        "dataset_active": dataset_matches,
        "status": status,
        "reason": reason,
        "checked_at_ms": now,
        "kafka_connected": bool(kafka_state.get("connected", False)),
        "last_message_ts_ms": last_message_ts,
        "message_age_ms": message_age_ms,
        "ingest_total": total,
        "ingest_drop_ratio": drop_ratio,
        "ingest_dropped_dimension_mismatch": int(ingest_stats.get("dropped_dimension_mismatch", 0)),
        "ingest_dropped_invalid_timestamp": int(ingest_stats.get("dropped_invalid_timestamp", 0)),
    }

def _source_registry_summary() -> dict[str, Any]:
    items = source_registry.get("items", [])
    active = None
    for item in items:
        if item.get("is_active", False):
            active = item
            break

    return {
        "enabled": FEATURE_DATA_SOURCE_TAB,
        "path": SOURCE_REGISTRY_PATH,
        "total": len(items),
        "enabled_count": sum(1 for item in items if item.get("enabled", False)),
        "active_source_id": None if active is None else int(active.get("id", -1)),
        "active_source_name": None if active is None else str(active.get("name", "")),
        "last_updated_ms": int(source_registry.get("updated_at_ms", 0)),
        "last_health_check_ms": int(source_runtime.get("last_health_check_ms", 0)),
    }

def _influx_record(measurement: str, tags: dict, fields: dict, timestamp_ms: Optional[int] = None):
    if Point is None or WritePrecision is None:
        return None
    point = Point(measurement)
    for key, value in (tags or {}).items():
        if value is None:
            continue
        point = point.tag(str(key), str(value))
    for key, value in (fields or {}).items():
        if value is None:
            continue
        if isinstance(value, (bool, int, float, str)):
            point = point.field(str(key), value)
        else:
            point = point.field(str(key), str(value))
    ts_ms = int(timestamp_ms) if timestamp_ms is not None else _now_ms()
    point = point.time(ts_ms * 1_000_000, WritePrecision.NS)
    return point

def _enqueue_influx(measurement: str, tags: dict, fields: dict, timestamp_ms: Optional[int] = None):
    if not INFLUX_ENABLED:
        return
    global influx_queue
    if influx_queue is None:
        return
    try:
        influx_queue.put_nowait({
            "measurement": measurement,
            "tags": tags,
            "fields": fields,
            "timestamp_ms": int(timestamp_ms) if timestamp_ms is not None else _now_ms(),
        })
        influx_state["queue_size"] = influx_queue.qsize()
    except asyncio.QueueFull:
        influx_state["dropped_points"] += 1
        influx_state["last_error"] = "queue_full"

def _emit_policy_event(event_type: str, action: str, reason: str = "", metadata: Optional[dict] = None):
    fields = {
        "event_type": event_type,
        "action": action,
        "reason": reason,
        "feedback_total": int(feedback_counters.get("total", 0)),
        "drift_events": int(drift_state.get("events", 0)),
        "recommended": bool(retrain_state.get("recommended", False)),
    }
    if metadata:
        for k, v in metadata.items():
            if isinstance(v, (bool, int, float, str)):
                fields[k] = v
            elif v is not None:
                fields[k] = str(v)

    _enqueue_influx(
        "policy_events",
        {
            "dataset": DATASET,
            "model_version": model_registry.get("model_version", "default"),
            "event_type": event_type,
        },
        fields,
    )

def _build_rl_metrics_snapshot() -> dict:
    recent = list(recent_alert_history)[-100:]
    anomalous = 0
    for item in recent:
        if item.get("is_anomalous", False):
            anomalous += 1
    anomaly_rate = float(anomalous / max(1, len(recent)))

    return {
        "drift_z": float(drift_state.get("z_shift", 0.0)),
        "drift_triggered": bool(drift_state.get("triggered", False)),
        "feedback_total": int(feedback_counters.get("total", 0)),
        "feedback_confirmed": int(feedback_counters.get("confirmed", 0)),
        "feedback_dismissed": int(feedback_counters.get("dismissed", 0)),
        "anomaly_rate_recent": anomaly_rate,
        "fused_score": float(last_score_meta.get("fused_score", 0.0)),
        "threshold": float(last_score_meta.get("threshold", runtime_policy["fused_threshold_default"])),
    }

def _current_policy_snapshot() -> dict[str, float]:
    return {
        "fused_threshold_default": float(runtime_policy["fused_threshold_default"]),
        "retrain_min_feedback": int(runtime_policy["retrain_min_feedback"]),
        "drift_z_threshold": float(runtime_policy["drift_z_threshold"]),
    }

def _normalize_policy_values(policy: dict[str, Any]) -> dict[str, float]:
    return {
        "fused_threshold_default": float(min(3.0, max(0.5, float(policy.get("fused_threshold_default", runtime_policy["fused_threshold_default"]))))),
        "retrain_min_feedback": int(min(200, max(10, int(policy.get("retrain_min_feedback", runtime_policy["retrain_min_feedback"]))))),
        "drift_z_threshold": float(min(5.0, max(1.0, float(policy.get("drift_z_threshold", runtime_policy["drift_z_threshold"]))))),
    }

def _policy_deltas(current_policy: dict[str, float], candidate_policy: dict[str, float]) -> dict[str, float]:
    return {
        "fused_threshold_default": float(candidate_policy["fused_threshold_default"] - current_policy["fused_threshold_default"]),
        "retrain_min_feedback": float(candidate_policy["retrain_min_feedback"] - current_policy["retrain_min_feedback"]),
        "drift_z_threshold": float(candidate_policy["drift_z_threshold"] - current_policy["drift_z_threshold"]),
    }

def _policy_guardrail_report(current_policy: dict[str, float], candidate_policy: dict[str, float]) -> dict:
    deltas = _policy_deltas(current_policy, candidate_policy)
    violations = []

    if abs(deltas["fused_threshold_default"]) > POLICY_APPLY_MAX_THRESHOLD_DELTA:
        violations.append(
            f"fused_threshold_default delta {deltas['fused_threshold_default']:.4f} exceeds {POLICY_APPLY_MAX_THRESHOLD_DELTA:.4f}"
        )
    if abs(deltas["retrain_min_feedback"]) > POLICY_APPLY_MAX_RETRAIN_FEEDBACK_DELTA:
        violations.append(
            f"retrain_min_feedback delta {deltas['retrain_min_feedback']:.0f} exceeds {POLICY_APPLY_MAX_RETRAIN_FEEDBACK_DELTA}"
        )
    if abs(deltas["drift_z_threshold"]) > POLICY_APPLY_MAX_DRIFT_Z_DELTA:
        violations.append(
            f"drift_z_threshold delta {deltas['drift_z_threshold']:.4f} exceeds {POLICY_APPLY_MAX_DRIFT_Z_DELTA:.4f}"
        )

    return {
        "passed": len(violations) == 0,
        "deltas": deltas,
        "limits": {
            "fused_threshold_default": float(POLICY_APPLY_MAX_THRESHOLD_DELTA),
            "retrain_min_feedback": int(POLICY_APPLY_MAX_RETRAIN_FEEDBACK_DELTA),
            "drift_z_threshold": float(POLICY_APPLY_MAX_DRIFT_Z_DELTA),
        },
        "violations": violations,
    }

def _policy_canary_report(current_policy: dict[str, float], candidate_policy: dict[str, float], canary_points: int) -> dict:
    requested_points = max(1, int(canary_points))
    min_points = max(1, int(POLICY_CANARY_MIN_POINTS))
    window_points = max(requested_points, min_points)
    fused = np.asarray(score_histories["fused"], dtype=np.float64)

    if fused.size < window_points:
        return {
            "ready": False,
            "passed": False,
            "required_points": int(window_points),
            "available_points": int(fused.size),
            "reason": "insufficient_fused_history",
        }

    window = fused[-window_points:]
    current_threshold = float(current_policy["fused_threshold_default"])
    candidate_threshold = float(candidate_policy["fused_threshold_default"])
    current_alert_rate = float(np.mean(window > current_threshold))
    candidate_alert_rate = float(np.mean(window > candidate_threshold))
    alert_rate_delta = float(candidate_alert_rate - current_alert_rate)
    passed = abs(alert_rate_delta) <= POLICY_CANARY_MAX_ALERT_RATE_DELTA

    return {
        "ready": True,
        "passed": bool(passed),
        "required_points": int(window_points),
        "available_points": int(fused.size),
        "current_alert_rate": current_alert_rate,
        "candidate_alert_rate": candidate_alert_rate,
        "alert_rate_delta": alert_rate_delta,
        "max_allowed_alert_rate_delta": float(POLICY_CANARY_MAX_ALERT_RATE_DELTA),
        "reason": "ok" if passed else "alert_rate_shift_too_large",
    }

def _record_policy_apply_entry(
    suggestion_id: str,
    action: str,
    previous_policy: dict[str, float],
    candidate_policy: dict[str, float],
    mode: str,
    note: str,
    guardrail: dict,
    canary: dict,
) -> dict:
    global policy_apply_seq
    policy_apply_seq += 1
    created_at_ms = _now_ms()
    apply_id = f"policy-apply-{policy_apply_seq}"

    entry = {
        "id": apply_id,
        "type": "apply",
        "created_at_ms": created_at_ms,
        "suggestion_id": suggestion_id,
        "action": action,
        "mode": mode,
        "note": note,
        "previous_policy": previous_policy,
        "applied_policy": candidate_policy,
        "guardrail": guardrail,
        "canary": canary,
        "rolled_back": False,
    }
    policy_apply_history.append(entry)
    policy_apply_state.update({
        "last_apply_id": apply_id,
        "last_apply_status": "applied",
        "last_apply_reason": "policy applied successfully",
        "last_apply_ts": created_at_ms,
        "active_policy": dict(candidate_policy),
    })
    return entry

def _find_apply_entry(apply_id: Optional[str] = None) -> Optional[dict]:
    if not policy_apply_history:
        return None
    entries = list(policy_apply_history)
    for item in reversed(entries):
        if item.get("type") != "apply":
            continue
        if item.get("rolled_back", False):
            continue
        if apply_id and item.get("id") != apply_id:
            continue
        return item
    return None

def _record_policy_rollback_entry(target: dict, note: str) -> dict:
    global policy_apply_seq
    policy_apply_seq += 1
    created_at_ms = _now_ms()
    rollback_id = f"policy-rollback-{policy_apply_seq}"

    target["rolled_back"] = True
    target["rollback_ts_ms"] = created_at_ms

    rollback_entry = {
        "id": rollback_id,
        "type": "rollback",
        "created_at_ms": created_at_ms,
        "target_apply_id": target.get("id", ""),
        "suggestion_id": target.get("suggestion_id", ""),
        "restored_policy": dict(target.get("previous_policy", {})),
        "note": note,
    }
    policy_apply_history.append(rollback_entry)
    policy_apply_state.update({
        "last_apply_id": rollback_id,
        "last_apply_status": "rolled_back",
        "last_apply_reason": "policy rolled back",
        "last_apply_ts": created_at_ms,
        "last_rollback_ts": created_at_ms,
        "active_policy": dict(runtime_policy),
    })
    return rollback_entry

async def _flush_influx_batch(write_api, batch: list[dict]):
    points = []
    for item in batch:
        rec = _influx_record(
            item.get("measurement", "events"),
            item.get("tags", {}),
            item.get("fields", {}),
            item.get("timestamp_ms"),
        )
        if rec is not None:
            points.append(rec)

    if not points:
        return

    try:
        await asyncio.to_thread(write_api.write, bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=points)
        influx_state["written_points"] += len(points)
        influx_state["last_write_ms"] = _now_ms()
        influx_state["last_error"] = ""
    except Exception as exc:
        influx_state["write_errors"] += 1
        influx_state["dropped_points"] += len(points)
        influx_state["last_error"] = str(exc)
        await asyncio.to_thread(_append_influx_deadletter, batch, str(exc))

async def _influx_writer_loop():
    if not INFLUX_ENABLED:
        return
    if InfluxDBClient is None:
        influx_state["last_error"] = "influxdb-client is not installed"
        return
    if not (INFLUX_TOKEN and INFLUX_ORG and INFLUX_BUCKET):
        influx_state["last_error"] = "missing Influx configuration"
        return

    client = None
    try:
        client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG, timeout=5000)
        write_api = client.write_api()
        influx_state["connected"] = True
        influx_state["last_error"] = ""

        while True:
            batch = []
            item = await influx_queue.get()
            batch.append(item)
            start_ts = time.time()

            while len(batch) < INFLUX_BATCH_SIZE:
                remaining = INFLUX_FLUSH_INTERVAL_SEC - (time.time() - start_ts)
                if remaining <= 0:
                    break
                try:
                    nxt = await asyncio.wait_for(influx_queue.get(), timeout=remaining)
                    batch.append(nxt)
                except asyncio.TimeoutError:
                    break

            await _flush_influx_batch(write_api, batch)
            influx_state["queue_size"] = influx_queue.qsize()

    except asyncio.CancelledError:
        raise
    except Exception as exc:
        influx_state["connected"] = False
        influx_state["write_errors"] += 1
        influx_state["last_error"] = str(exc)
    finally:
        influx_state["connected"] = False
        if client is not None:
            await asyncio.to_thread(client.close)

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
                threshold REAL,
                raw_window BLOB
            )
            """
        )
        # ── Migration: add raw_window column to existing DBs ──────────────
        try:
            conn.execute("ALTER TABLE operator_feedback ADD COLUMN raw_window BLOB")
            conn.commit()
        except Exception:
            pass  # Column already exists
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
                system_loss, threshold, raw_window
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                record.get("raw_window"),  # BLOB or None
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
    storage_ds = _runtime_dataset_alias(target_ds)
    folder = Path(f"checkpoints/{MODEL_NAME}_{storage_ds}")
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

def _update_model_registry(
    dataset: str,
    model_version: str,
    checkpoint_path: str,
    feature_source_id: str,
    feature_count: int,
):
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
        "feature_source_id": feature_source_id,
        "feature_count": int(feature_count),
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
        "recon_z": 0.0,
        "forecast_z": 0.0,
        "corr_z": 0.0,
        "fused_score": 0.0,
        "threshold": float(runtime_policy["fused_threshold_default"]),
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
    prev_recommended = bool(retrain_state.get("recommended", False))
    prev_reason = str(retrain_state.get("reason", ""))
    reasons = []
    retrain_min_feedback = int(runtime_policy["retrain_min_feedback"])
    if feedback_counters["total"] >= retrain_min_feedback:
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

    if retrain_state["recommended"] and (not prev_recommended or retrain_state["reason"] != prev_reason):
        _emit_policy_event(
            "retrain_recommendation",
            "raised",
            retrain_state["reason"],
            {
                "forced_refresh": bool(force),
            },
        )
    elif prev_recommended and not retrain_state["recommended"]:
        _emit_policy_event(
            "retrain_recommendation",
            "cleared",
            "retrain criteria no longer met",
            {
                "previous_reason": prev_reason,
            },
        )


async def _finetune_async_wrapper():
    """Async wrapper — syncs model_registry version key after fine-tune completes."""
    if model is None or ft_optimizer is None:
        return
    _ft_ckpt_dir = os.path.join(
        _SERVER_DIR, "checkpoints", f"STP_TranAD_{_runtime_dataset_alias(DATASET)}"
    )
    version_ref = {"version": str(model_registry.get("model_version", "default"))}
    try:
        result = await run_finetune(
            model=model,
            optimizer=ft_optimizer,
            db_path=FEEDBACK_DB_PATH,
            checkpoint_dir=_ft_ckpt_dir,
            device=device,
            model_version_ref=version_ref,
            retrain_state=retrain_state,
            model_lock=model_lock,
        )
        if not result.get("skipped"):
            model_registry["model_version"] = version_ref["version"]
            _enqueue_influx(
                "finetune_events",
                {"dataset": DATASET, "model_version": model_registry["model_version"]},
                {
                    "windows_used": int(result.get("windows_used", 0)),
                    "epochs": int(result.get("epochs", 0)),
                    "new_version": str(result.get("new_version", "")),
                },
            )
            print(f"[FINETUNE] Complete → version={model_registry['model_version']}  result={result}")
        else:
            print(f"[FINETUNE] Skipped: {result.get('reason')} (windows={result.get('count')})")
    except Exception as exc:
        print(f"[FINETUNE] Error during fine-tune: {exc}")


def _launch_finetune_task():
    """Fire-and-forget fine-tune — safe to call from any async FastAPI context."""
    if model is None or ft_optimizer is None:
        print("[FINETUNE] Skipped — model or ft_optimizer not ready.")
        return
    try:
        asyncio.create_task(_finetune_async_wrapper())
        print("[FINETUNE] Background fine-tune task queued.")
    except RuntimeError as exc:
        print(f"[FINETUNE] Could not schedule task (event loop issue): {exc}")


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
    drift_z_threshold = float(runtime_policy["drift_z_threshold"])
    should_trigger = metrics["z_shift"] >= drift_z_threshold and cooldown_elapsed
    drift_state["triggered"] = bool(should_trigger)
    if should_trigger:
        drift_state["events"] += 1
        drift_state["last_trigger_ts"] = now_ts
        _enqueue_influx(
            "drift_events",
            {
                "dataset": DATASET,
                "model_version": model_registry.get("model_version", "default"),
            },
            {
                "z_shift": float(drift_state["z_shift"]),
                "baseline_mean": float(drift_state["baseline_mean"]),
                "recent_mean": float(drift_state["recent_mean"]),
                "events": int(drift_state["events"]),
            },
        )

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
        threshold = float(runtime_policy["fused_threshold_default"])

    last_score_meta = {
        "recon_score": recon_score,
        "forecast_score": forecast_score,
        "corr_score": corr_score,
        "recon_z": float(recon_z),
        "forecast_z": float(forecast_z),
        "corr_z": float(corr_z),
        "fused_score": float(fused_score),
        "threshold": threshold,
    }
    return float(fused_score), threshold

def _build_anomaly_source_breakdown() -> dict:
    recon_w = FUSED_WEIGHT_RECON * float(last_score_meta.get("recon_z", 0.0))
    forecast_w = FUSED_WEIGHT_FORECAST * float(last_score_meta.get("forecast_z", 0.0))
    corr_w = FUSED_WEIGHT_CORR * float(last_score_meta.get("corr_z", 0.0))
    total = float(recon_w + forecast_w + corr_w)
    if total <= 1e-12:
        total = 1.0

    return {
        "weights": {
            "recon": FUSED_WEIGHT_RECON,
            "forecast": FUSED_WEIGHT_FORECAST,
            "corr": FUSED_WEIGHT_CORR,
        },
        "z_scores": {
            "recon": float(last_score_meta.get("recon_z", 0.0)),
            "forecast": float(last_score_meta.get("forecast_z", 0.0)),
            "corr": float(last_score_meta.get("corr_z", 0.0)),
        },
        "weighted_components": {
            "recon": recon_w,
            "forecast": forecast_w,
            "corr": corr_w,
        },
        "contribution_pct": {
            "recon": float((recon_w / total) * 100.0),
            "forecast": float((forecast_w / total) * 100.0),
            "corr": float((corr_w / total) * 100.0),
        },
    }

def _correlation_change_snapshot(history_window: np.ndarray, top_k: int = 5) -> dict:
    if history_window.ndim != 2 or history_window.shape[0] < 8:
        return {
            "ready": False,
            "fro_norm": 0.0,
            "top_pair_changes": [],
        }

    midpoint = history_window.shape[0] // 2
    prev_block = history_window[:midpoint]
    curr_block = history_window[midpoint:]
    c_prev = _safe_corrcoef(prev_block)
    c_curr = _safe_corrcoef(curr_block)
    diff = c_curr - c_prev
    abs_diff = np.abs(diff)
    if abs_diff.ndim != 2 or abs_diff.shape[0] <= 1:
        return {
            "ready": False,
            "fro_norm": float(np.linalg.norm(diff, ord='fro')),
            "top_pair_changes": [],
        }

    tri_r, tri_c = np.triu_indices(abs_diff.shape[0], k=1)
    if tri_r.size == 0:
        return {
            "ready": False,
            "fro_norm": float(np.linalg.norm(diff, ord='fro')),
            "top_pair_changes": [],
        }

    top_order = np.argsort(abs_diff[tri_r, tri_c])[::-1][:top_k]
    top_changes = []
    for idx in top_order:
        r = int(tri_r[idx])
        c = int(tri_c[idx])
        sensor_a = f"s{r}"
        sensor_b = f"s{c}"
        source_id = str(model_registry.get("feature_source_id", ""))
        top_changes.append({
            "sensor_a": sensor_a,
            "sensor_b": sensor_b,
            "sensor_a_label": _sensor_label(sensor_a, DATASET, source_id),
            "sensor_b_label": _sensor_label(sensor_b, DATASET, source_id),
            "prev_corr": float(c_prev[r, c]),
            "curr_corr": float(c_curr[r, c]),
            "delta": float(diff[r, c]),
            "abs_delta": float(abs_diff[r, c]),
        })

    return {
        "ready": True,
        "fro_norm": float(np.linalg.norm(diff, ord='fro')),
        "top_pair_changes": top_changes,
    }

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
    source_id = str(model_registry.get("feature_source_id", ""))
    for idx in order:
        contribution_pct = float((blended[idx] / total) * 100.0)
        sensor_name = f"s{int(idx)}"
        ranked.append({
            "sensor": sensor_name,
            "sensor_label": _sensor_label(sensor_name, DATASET, source_id),
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
        top_name = top.get("sensor_label") or top.get("sensor", "sensor")
        hints.append(f"Inspect {top_name} first; highest contribution {top['contribution_pct']:.1f}%.")
    if anomaly_type == "collective_anomaly":
        hints.append(f"Check cross-sensor dependency break; correlation shift score={corr_score:.6f}.")
    elif anomaly_type == "contextual_anomaly":
        hints.append("Validate temporal context and operating mode; forecast mismatch is dominant.")
    else:
        hints.append("Investigate sudden local spike and recent actuator/control actions.")
    if len(contributors) > 1:
        a_name = contributors[0].get("sensor_label") or contributors[0].get("sensor", "sensor_a")
        b_name = contributors[1].get("sensor_label") or contributors[1].get("sensor", "sensor_b")
        hints.append(f"Compare {a_name} with {b_name} for coupled deviation.")
    return hints[:4]

def _sensor_idx_from_name(sensor_name: str) -> Optional[int]:
    if not isinstance(sensor_name, str):
        return None
    s = sensor_name.strip().lower()
    if not s.startswith("s"):
        return None
    try:
        return int(s[1:])
    except ValueError:
        return None

def _build_sensor_snapshot(
    actual_sensors: np.ndarray,
    forecast_sensors: np.ndarray,
    recon_vec: np.ndarray,
    forecast_vec: np.ndarray,
    top_contributors: list[dict],
) -> dict:
    source_id = str(model_registry.get("feature_source_id", ""))
    actual_arr = np.asarray(actual_sensors, dtype=np.float64).reshape(-1)
    forecast_arr = np.asarray(forecast_sensors, dtype=np.float64).reshape(-1)
    recon_arr = np.asarray(recon_vec, dtype=np.float64).reshape(-1)
    forecast_err_arr = np.asarray(forecast_vec, dtype=np.float64).reshape(-1)
    residual_abs = np.abs(forecast_arr - actual_arr)

    top_sensor_details: list[dict[str, Any]] = []
    for contributor in top_contributors[:5]:
        sensor_name = str(contributor.get("sensor", ""))
        idx = _sensor_idx_from_name(sensor_name)
        if idx is None or idx < 0 or idx >= actual_arr.shape[0]:
            continue
        top_sensor_details.append({
            "sensor": sensor_name,
            "sensor_label": _sensor_label(sensor_name, DATASET, source_id),
            "index": int(idx),
            "contribution_pct": float(contributor.get("contribution_pct", 0.0)),
            "actual": float(actual_arr[idx]),
            "forecast": float(forecast_arr[idx]),
            "abs_residual": float(residual_abs[idx]),
            "recon_error": float(recon_arr[idx]),
            "forecast_error": float(forecast_err_arr[idx]),
        })

    return {
        "dimensions": int(actual_arr.shape[0]),
        "top_sensors": top_sensor_details,
        "actual_vector": [float(x) for x in actual_arr.tolist()],
        "forecast_vector": [float(x) for x in forecast_arr.tolist()],
        "recon_error_vector": [float(x) for x in recon_arr.tolist()],
        "forecast_error_vector": [float(x) for x in forecast_err_arr.tolist()],
    }

def _find_anomaly_event(anomaly_id: int) -> Optional[dict[str, Any]]:
    for event in anomaly_event_history:
        if event.get("id") == anomaly_id:
            return event
    return None

def _build_anomaly_source_payload(event: dict[str, Any]) -> dict[str, Any]:
    top_sensor = str(event.get("top_sensor", "n/a"))
    event_dataset = str(event.get("dataset", DATASET))
    feature_source_id = str(event.get("feature_source_id", model_registry.get("feature_source_id", "")))
    return {
        "anomaly_id": int(event.get("id", 0)),
        "dataset": str(event.get("dataset", "")),
        "feature_source_id": feature_source_id,
        "tick": int(event.get("tick", 0)),
        "anomaly_type": str(event.get("anomaly_type", "")),
        "severity_level": str(event.get("severity_level", "")),
        "severity_score": int(event.get("severity_score", 0)),
        "confidence": float(event.get("confidence", 0.0)),
        "top_sensor": top_sensor,
        "top_sensor_label": str(event.get("top_sensor_label", _sensor_label(top_sensor, event_dataset, feature_source_id))),
        "top_contributors": list(event.get("top_contributors", [])),
        "investigation_hints": list(event.get("investigation_hints", [])),
        "score_components": dict(event.get("score_components", {})),
        "anomaly_source": event.get("anomaly_source"),
        "sensor_snapshot": event.get("sensor_snapshot"),
        "sop_history": list(event.get("sop_history", [])),
    }

def _fallback_sop(event: dict[str, Any], request: SOPRequest) -> str:
    top_sensor = str(event.get("top_sensor", "n/a"))
    anomaly_type = str(event.get("anomaly_type", "unknown"))
    severity = str(event.get("severity_level", "info"))
    top_contributors = list(event.get("top_contributors", []))
    hints = list(event.get("investigation_hints", []))
    max_steps = int(max(3, min(15, request.max_steps)))
    secondary = top_contributors[1]["sensor"] if len(top_contributors) > 1 else "n/a"
    constraints = [str(x).strip() for x in request.constraints if str(x).strip()]

    steps = [
        f"Acknowledge {severity.upper()} {anomaly_type} event and isolate impacted subsystem around {top_sensor}.",
        f"Validate {top_sensor} instrumentation: power, wiring, calibration, and timestamp freshness.",
        f"Cross-check coupled sensor {secondary} for correlated drift before replacing any hardware.",
        "Compare live readings against last known-good baseline and enforce safe operating envelope.",
        "If mismatch persists, switch to fallback control mode and escalate to maintenance owner.",
        "Apply corrective action, then monitor 15 minutes for recurrence and alert suppression stability.",
        "Record root cause evidence and update preventive maintenance schedule for the affected sensor chain.",
    ][:max_steps]

    if hints:
        steps.append(f"Analyst hint: {hints[0]}")
        steps = steps[:max_steps]

    constraint_block = ""
    if constraints:
        constraint_block = "\nConstraints:\n" + "\n".join([f"- {item}" for item in constraints])

    return textwrap.dedent(
        f"""
        SOP Objective: {request.objective}
        Event: anomaly_id={event.get('id')} dataset={event.get('dataset')} tick={event.get('tick')}
        Source Focus: top_sensor={top_sensor}, anomaly_type={anomaly_type}, severity={severity}
        Recommended Steps:
        {chr(10).join([f"{idx + 1}. {step}" for idx, step in enumerate(steps)])}
        Verification Gate:
        1. Confirm fused score remains below threshold for 3 consecutive windows.
        2. Verify top contributor concentration falls below 20% for prior top sensor.
        3. Close incident only after operator sign-off and log archival.
        {constraint_block}
        """
    ).strip()

def _build_sop_llm_prompt(event: dict[str, Any], request: SOPRequest) -> str:
    source_payload = _build_anomaly_source_payload(event)
    compact = {
        "objective": request.objective,
        "constraints": request.constraints,
        "event": source_payload,
    }
    return (
        "You are an industrial anomaly response engineer. "
        "Generate a concise, practical SOP with numbered steps, verification checks, "
        "and rollback criteria. Focus on prevention at sensor source. "
        "Return plain text only. Input JSON follows:\n" + json.dumps(compact, ensure_ascii=True)
    )

def _sop_llm_config() -> tuple[str, str, str]:
    provider = str(SOP_LLM_PROVIDER or "").strip().lower()
    if provider == "groq":
        return provider, SOP_GROQ_API_KEY, SOP_GROQ_ENDPOINT
    if provider == "openai":
        return provider, SOP_OPENAI_API_KEY, SOP_OPENAI_ENDPOINT
    return provider, "", ""

def _generate_sop_with_llm(event: dict[str, Any], request: SOPRequest) -> str:
    provider, api_key, endpoint = _sop_llm_config()
    if provider not in {"groq", "openai"}:
        raise RuntimeError(f"unsupported_llm_provider:{provider}")
    if not api_key:
        raise RuntimeError(f"{provider}_api_key_not_configured")

    if provider == "groq":
        default_model = SOP_GROQ_MODEL or "llama-3.3-70b-versatile"
    else:
        default_model = SOP_OPENAI_MODEL or "gpt-4o-mini"

    model = (request.model or default_model).strip()
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You write precise incident SOPs for sensor anomalies.",
            },
            {
                "role": "user",
                "content": _build_sop_llm_prompt(event, request),
            },
        ],
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=SOP_LLM_TIMEOUT_SEC) as response:
        body = response.read().decode("utf-8")
    parsed = json.loads(body)
    choices = parsed.get("choices", [])
    if not choices:
        raise RuntimeError("LLM returned no choices")
    message = choices[0].get("message", {})
    content = str(message.get("content", "")).strip()
    if not content:
        raise RuntimeError("LLM returned empty SOP content")
    return content

def _record_anomaly_event(
    tick: int,
    fused_score: float,
    threshold: float,
    severity_score: int,
    severity_level: str,
    confidence: float,
    anomaly_type: str,
    duration_steps: int,
    top_contributors: list[dict],
    historical_similar: list[dict],
    investigation_hints: list[str],
    anomaly_source: Optional[dict],
    sensor_snapshot: Optional[dict],
):
    global anomaly_event_seq
    anomaly_event_seq += 1
    event = {
        "id": anomaly_event_seq,
        "created_at_ms": _now_ms(),
        "dataset": DATASET,
        "feature_source_id": str(model_registry.get("feature_source_id", "")),
        "tick": tick,
        "system_loss": float(fused_score),
        "threshold": float(threshold),
        "severity_score": int(severity_score),
        "severity_level": severity_level,
        "confidence": float(confidence),
        "anomaly_type": anomaly_type,
        "duration_steps": int(duration_steps),
        "top_sensor": top_contributors[0]["sensor"] if top_contributors else "n/a",
        "top_sensor_label": top_contributors[0].get("sensor_label", top_contributors[0]["sensor"]) if top_contributors else "n/a",
        "top_contributors": top_contributors,
        "historical_similar": historical_similar,
        "investigation_hints": investigation_hints,
        "score_components": {
            "recon": float(last_score_meta.get("recon_score", 0.0)),
            "forecast": float(last_score_meta.get("forecast_score", 0.0)),
            "corr": float(last_score_meta.get("corr_score", 0.0)),
        },
        "anomaly_source": anomaly_source,
        "sensor_snapshot": sensor_snapshot,
        "sop_history": [],
    }
    anomaly_event_history.append(event)
    return event

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

async def _process_telemetry_event(payload: TelemetryData, source: str = "http"):
    ingest_stats["total"] += 1
    async with model_lock:
        timestamp_ok, timestamp_reason = _validate_timestamp(payload.timestamp_ms)
        if not timestamp_ok:
            if source == "kafka":
                kafka_state["dropped_messages"] += 1
            return {
                "status": "dropped",
                "reason": timestamp_reason,
            }

        sanitized_sensors, sanitize_reason = _sanitize_sensors(payload.sensors, feats_dim)
        if sanitized_sensors is None:
            if source == "kafka":
                kafka_state["dropped_messages"] += 1
            return {
                "status": "dropped",
                "reason": sanitize_reason,
            }

        async with data_condition:
            live_buffer.append(sanitized_sensors)
            data_condition.notify_all()

    ingest_stats["accepted"] += 1
    if source == "kafka":
        kafka_state["ingested_count"] += 1
    return {
        "status": "ingested",
        "degraded": last_ingest_meta["degraded"],
        "imputed_count": last_ingest_meta["imputed_count"],
        "outlier_count": last_ingest_meta["outlier_count"],
    }

def init_model(target_ds=None):
    if target_ds is None:
        target_ds = DATASET
    print(f"Loading STP-TranAD Model for {target_ds}...")
    storage_ds = _runtime_dataset_alias(target_ds)
    ckpt_path, model_version = _resolve_checkpoint_and_version(target_ds)
    
    # Identify target dynamic files
    feature_source_id = _DATASET_FEATURE_SOURCE.get(str(target_ds), _DATASET_FEATURE_SOURCE.get(storage_ds, "unknown"))
    if storage_ds == 'SMD':
        feature_source_id = "machine-1-1"
        test_arr = np.load(f'processed/{storage_ds}/{feature_source_id}_test.npy')
    elif storage_ds == 'MSL':
        feature_source_id = "C-1"
        test_arr = np.load(f'processed/{storage_ds}/{feature_source_id}_test.npy')
    elif storage_ds == 'SMAP':
        feature_source_id = "A-1"
        test_arr = np.load(f'processed/{storage_ds}/{feature_source_id}_test.npy')
    elif storage_ds == 'synthetic':
        feature_source_id = "esp32-replay" if str(target_ds) == "ESP32" else "synthetic"
        test_arr = np.load(f'processed/{storage_ds}/test.npy')
    else:
        raise ValueError(f"Unsupported dataset for STP server: {target_ds}")
        
    feats = test_arr.shape[1]
    
    # Initialize Model fundamentally equivalent to Training initialization
    m = STP_TranAD(feats).double().to(device)
    opt = torch.optim.AdamW(m.parameters(), lr=1e-5, weight_decay=1e-5)
    global ft_optimizer
    ft_optimizer = torch.optim.Adam(m.parameters(), lr=FT_LR, weight_decay=1e-5)
    
    if os.path.exists(ckpt_path):
        try:
            checkpoint = torch.load(ckpt_path, map_location=device, weights_only=False)
            m.load_state_dict(checkpoint['model_state_dict'])
            if 'optimizer_state_dict' in checkpoint:
                try:
                    opt.load_state_dict(checkpoint['optimizer_state_dict'])
                except Exception as exc:
                    print(f"WARNING: Optimizer state incompatible, continuing with fresh optimizer: {exc}")
            print(f"Pre-trained checkpoint loaded successfully from {ckpt_path}.")
        except Exception as exc:
            print(f"WARNING: Checkpoint incompatible with current feature dimension; using random initialization: {exc}")
    else:
        print("WARNING: Checkpoint not found. Running with uninitialized random weights.")
    m.eval()
    _register_runtime_sensor_name_map(str(target_ds), feature_source_id, int(feats))
    _update_model_registry(target_ds, model_version, ckpt_path, feature_source_id, int(feats))
    return m, opt, feats

async def _send_whatsapp_alert(
    anomaly_type: str,
    severity_level: str,
    confidence: float,
    top_sensor: str,
    fused_score: float,
    threshold: float,
    tick: int,
    dataset: str,
):
    """Fire a WhatsApp alert via Twilio. Silently no-ops if not configured."""
    global _twilio_last_sent_ts
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_TO_NUMBERS:
        return  # not configured — skip silently

    now = time.time()
    if now - _twilio_last_sent_ts < TWILIO_COOLDOWN:
        return  # cooldown active — skip to avoid spam

    sev_order = {"info": 0, "warning": 1, "critical": 2}
    if sev_order.get(severity_level, 0) < sev_order.get(TWILIO_MIN_SEV, 1):
        return  # below configured minimum severity

    _twilio_last_sent_ts = now
    emoji = "\U0001f6a8" if severity_level == "critical" else "\u26a0\ufe0f"
    timestamp = time.strftime("%I:%M %p", time.localtime())

    body = (
        f"{emoji} UTAU-IIoT ALERT\n\n"
        f"Dataset:    {dataset}\n"
        f"Severity:   {severity_level.upper()}\n"
        f"Type:       {anomaly_type}\n"
        f"Sensor:     {top_sensor}\n"
        f"Confidence: {confidence * 100:.1f}%\n"
        f"Score:      {fused_score:.4f} (thresh {threshold:.4f})\n"
        f"Tick:       {tick} | {timestamp}\n\n"
        f"Autonomic canary rollback initiated."
    )

    def _send_sync():
        try:
            from twilio.rest import Client
            client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            for to_number in TWILIO_TO_NUMBERS:
                try:
                    msg = client.messages.create(
                        from_=TWILIO_FROM_WHATSAPP,
                        to=to_number,
                        body=body,
                    )
                    print(f"[TWILIO] Alert sent to {to_number}: {msg.sid}")
                except Exception as exc:
                    print(f"[TWILIO] Failed to send to {to_number}: {exc}")
        except ImportError:
            print("[TWILIO] twilio package not installed. Run: pip install twilio")

    await asyncio.to_thread(_send_sync)


async def _governance_monitor_loop():
    while True:
        await asyncio.sleep(DRIFT_MONITOR_INTERVAL_SEC)
        _update_drift_state()
        _refresh_retrain_recommendation()
        _enqueue_influx(
            "ingest_quality",
            {
                "dataset": DATASET,
            },
            {
                "total": int(ingest_stats["total"]),
                "accepted": int(ingest_stats["accepted"]),
                "dropped_dimension_mismatch": int(ingest_stats["dropped_dimension_mismatch"]),
                "dropped_invalid_timestamp": int(ingest_stats["dropped_invalid_timestamp"]),
                "out_of_order": int(ingest_stats["out_of_order"]),
                "clock_skew": int(ingest_stats["clock_skew"]),
                "imputed_values": int(ingest_stats["imputed_values"]),
                "outlier_values": int(ingest_stats["outlier_values"]),
                "degraded_events": int(ingest_stats["degraded_events"]),
                "imputed_ratio": float(last_ingest_meta["imputed_ratio"]),
            },
        )

async def _kafka_consumer_loop():
    if not KAFKA_CONSUMER_ENABLED:
        return

    if AIOKafkaConsumer is None:
        kafka_state["last_error"] = "aiokafka is not installed"
        print("WARNING: Kafka consumer is enabled but aiokafka is not installed.")
        return

    bootstrap_servers = [s.strip() for s in KAFKA_BOOTSTRAP_SERVERS.split(",") if s.strip()]

    while True:
        consumer = None
        try:
            consumer = AIOKafkaConsumer(
                KAFKA_TOPIC,
                bootstrap_servers=bootstrap_servers,
                group_id=KAFKA_GROUP_ID,
                auto_offset_reset=KAFKA_AUTO_OFFSET_RESET,
                enable_auto_commit=True,
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            )
            await consumer.start()
            kafka_state["connected"] = True
            kafka_state["last_error"] = ""
            print(f"[KAFKA] Consumer connected to topic '{KAFKA_TOPIC}' on {KAFKA_BOOTSTRAP_SERVERS}")

            async for msg in consumer:
                kafka_state["received_count"] += 1
                kafka_state["last_message_ts_ms"] = _now_ms()

                try:
                    payload = msg.value
                    telemetry = TelemetryData(**payload)
                except Exception as exc:
                    kafka_state["deserialize_errors"] += 1
                    kafka_state["last_error"] = f"deserialize_error: {exc}"
                    continue

                await _process_telemetry_event(telemetry, source="kafka")

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            kafka_state["connected"] = False
            kafka_state["last_error"] = str(exc)
            print(f"[KAFKA] Consumer error: {exc}")
            await asyncio.sleep(KAFKA_RECONNECT_BACKOFF_SEC)
        finally:
            kafka_state["connected"] = False
            if consumer is not None:
                try:
                    await consumer.stop()
                except Exception:
                    pass

@app.on_event("startup")
async def startup_event():
    global model, optimizer, feats_dim, governance_task, kafka_consumer_task, influx_writer_task, influx_queue, rl_policy_manager
    _init_feedback_db()
    _load_source_registry()
    _load_sensor_name_map(force=True)
    feedback_counters.update(_load_feedback_counters())
    model, optimizer, feats_dim = init_model()
    _reset_ingestion_state(feats_dim)
    _refresh_retrain_recommendation(force=True)
    if INFLUX_ENABLED:
        influx_queue = asyncio.Queue(maxsize=INFLUX_QUEUE_MAXSIZE)
        influx_writer_task = asyncio.create_task(_influx_writer_loop())
    else:
        influx_queue = None

    if FEATURE_RL_POLICY_SUGGESTIONS:
        rl_policy_manager = RLPolicyManager(
            state_path=RL_POLICY_STATE_PATH,
            learning_rate=RL_POLICY_LEARNING_RATE,
            discount_factor=RL_POLICY_DISCOUNT,
            epsilon=RL_POLICY_EPSILON,
        )
    else:
        rl_policy_manager = None
    policy_apply_state.update({
        "enabled": FEATURE_RL_POLICY_SUGGESTIONS,
        "active_policy": _current_policy_snapshot(),
    })
    governance_task = asyncio.create_task(_governance_monitor_loop())
    if KAFKA_CONSUMER_ENABLED:
        kafka_consumer_task = asyncio.create_task(_kafka_consumer_loop())
    
    # Pre-fill buffer with mean zero-state to prevent startup crashes
    for _ in range(101):
        live_buffer.append([0.0] * feats_dim)

@app.on_event("shutdown")
async def shutdown_event():
    global governance_task, kafka_consumer_task, influx_writer_task, influx_queue
    if kafka_consumer_task is not None:
        kafka_consumer_task.cancel()
        try:
            await kafka_consumer_task
        except asyncio.CancelledError:
            pass
        kafka_consumer_task = None

    if governance_task is not None:
        governance_task.cancel()
        try:
            await governance_task
        except asyncio.CancelledError:
            pass
        governance_task = None

    if influx_writer_task is not None:
        influx_writer_task.cancel()
        try:
            await influx_writer_task
        except asyncio.CancelledError:
            pass
        influx_writer_task = None
    influx_queue = None

@app.post("/ingest")
async def ingest_telemetry(payload: TelemetryData):
    return await _process_telemetry_event(payload, source="http")

@app.get("/status")
async def get_status():
    _update_drift_state()
    _refresh_retrain_recommendation()
    if influx_queue is not None:
        influx_state["queue_size"] = influx_queue.qsize()
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
            "active_policy": _current_policy_snapshot(),
            "last": last_score_meta,
            "fused_history_size": len(score_histories["fused"]),
        },
        "governance": {
            "drift": drift_state,
            "retraining": retrain_state,
            "manual_anomaly": manual_anomaly_state,
            "model_registry": model_registry,
            "feedback": feedback_counters,
        },
        "features": {
            "anomaly_source_tab": FEATURE_ANOMALY_SOURCE_TAB,
            "data_source_tab": FEATURE_DATA_SOURCE_TAB,
            "rl_policy_suggestions": FEATURE_RL_POLICY_SUGGESTIONS,
        },
        "sources": _source_registry_summary(),
        "rl_policy": {
            "enabled": FEATURE_RL_POLICY_SUGGESTIONS,
            "manager_ready": rl_policy_manager is not None,
            "state_path": RL_POLICY_STATE_PATH,
            "last_suggestion": rl_policy_last_suggestion,
            "apply": {
                **policy_apply_state,
                "history_depth": len(policy_apply_history),
            },
        },
        "kafka": kafka_state,
        "influx": influx_state,
    }

@app.get("/sources")
async def list_sources():
    async with source_registry_lock:
        items = [_public_source_item(item) for item in source_registry["items"]]
        active_source_id = source_runtime.get("active_source_id")
    return {
        "total": len(items),
        "active_source_id": active_source_id,
        "items": items,
    }

@app.post("/sources")
async def create_source(payload: SourceCreatePayload):
    body = _model_dump(payload)
    normalized, errors = _validate_source_payload(body, partial=False)
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))

    async with source_registry_lock:
        source_id = int(source_registry["next_id"])
        now_ms = _now_ms()
        entry = {
            "id": source_id,
            "name": normalized["name"],
            "protocol": normalized["protocol"],
            "endpoint": normalized["endpoint"],
            "topic": normalized.get("topic"),
            "dataset": normalized.get("dataset"),
            "expected_dimensions": normalized.get("expected_dimensions"),
            "enabled": bool(normalized.get("enabled", True)),
            "is_active": False,
            "notes": normalized.get("notes"),
            "mapping": normalized.get("mapping", {}),
            "auth": normalized.get("auth", {}),
            "created_at_ms": now_ms,
            "updated_at_ms": now_ms,
        }
        source_registry["items"].append(entry)
        source_registry["next_id"] = source_id + 1
        source_registry["updated_at_ms"] = now_ms

        requested_active = bool(normalized.get("is_active", False))
        has_active = any(item.get("is_active", False) for item in source_registry["items"])
        if requested_active or (not has_active):
            _set_active_source(source_id)

        _save_source_registry()
        created = _public_source_item(entry)

    return {
        "status": "created",
        "item": created,
        "active_source_id": source_runtime.get("active_source_id"),
    }

@app.patch("/sources/{source_id}")
async def update_source(source_id: int, payload: SourceUpdatePayload):
    body = _model_dump(payload, exclude_unset=True)
    if not body:
        raise HTTPException(status_code=400, detail="empty_patch_payload")

    normalized, errors = _validate_source_payload(body, partial=True)
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))

    async with source_registry_lock:
        entry = _find_source_by_id(source_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="source_not_found")

        for key, value in normalized.items():
            if key == "is_active":
                continue
            entry[key] = value
        entry["updated_at_ms"] = _now_ms()
        source_registry["updated_at_ms"] = entry["updated_at_ms"]

        if "is_active" in normalized:
            if normalized["is_active"]:
                _set_active_source(source_id)
            else:
                entry["is_active"] = False
                if source_runtime.get("active_source_id") == source_id:
                    source_runtime["active_source_id"] = None
                    for candidate in source_registry["items"]:
                        if candidate.get("enabled", False):
                            _set_active_source(int(candidate["id"]))
                            break

        _save_source_registry()
        updated = _public_source_item(entry)

    return {
        "status": "updated",
        "item": updated,
        "active_source_id": source_runtime.get("active_source_id"),
    }

@app.get("/sources/{source_id}/health")
async def source_health(source_id: int):
    async with source_registry_lock:
        entry = _find_source_by_id(source_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="source_not_found")
        health = _source_health_snapshot(entry)
    return health

@app.post("/sources/{source_id}/mapping/validate")
async def validate_source_mapping(source_id: int, payload: SourceMappingValidatePayload):
    async with source_registry_lock:
        entry = _find_source_by_id(source_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="source_not_found")
        mapping = entry.get("mapping") if isinstance(entry.get("mapping"), dict) else {}
        expected_dims = entry.get("expected_dimensions")

    timestamp_path = str(mapping.get("timestamp_path", "timestamp_ms")).strip()
    vector_path = str(mapping.get("vector_path", "sensors")).strip()
    issues = []
    warnings = []

    if not timestamp_path:
        issues.append("mapping.timestamp_path is required")
    if not vector_path:
        issues.append("mapping.vector_path is required")

    sample_result = {
        "checked": False,
        "timestamp_ok": False,
        "vector_ok": False,
        "vector_length": None,
    }

    if payload.sample is not None:
        sample_result["checked"] = True
        sample = payload.sample
        ts_value = _extract_nested_path(sample, timestamp_path)
        vec_value = _extract_nested_path(sample, vector_path)

        if not isinstance(ts_value, int):
            issues.append(f"timestamp_path '{timestamp_path}' did not resolve to integer timestamp")
        else:
            sample_result["timestamp_ok"] = True

        if not isinstance(vec_value, list):
            issues.append(f"vector_path '{vector_path}' did not resolve to numeric array")
        else:
            sample_result["vector_ok"] = True
            sample_result["vector_length"] = len(vec_value)
            if any(_safe_float(v) is None for v in vec_value):
                issues.append("sample vector contains non-numeric values")
            if expected_dims is not None and len(vec_value) != int(expected_dims):
                issues.append(
                    f"sample vector length {len(vec_value)} does not match expected_dimensions {int(expected_dims)}"
                )
            if len(vec_value) != feats_dim:
                warnings.append(f"sample vector length {len(vec_value)} differs from active model dimensions {feats_dim}")

    if expected_dims is None:
        warnings.append("expected_dimensions is not set; dimension mismatch protection may be weaker")

    return {
        "source_id": source_id,
        "valid": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "resolved_mapping": {
            "timestamp_path": timestamp_path,
            "vector_path": vector_path,
            "expected_dimensions": expected_dims,
            "active_model_dimensions": feats_dim,
        },
        "sample_check": sample_result,
    }

@app.get("/anomalies")
async def list_anomalies(
    dataset: Optional[str] = None,
    severity_min: int = Query(0, ge=0, le=100),
    anomaly_type: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    include_sop_history: bool = Query(False),
):
    events = list(anomaly_event_history)
    events.reverse()

    filtered = []
    for event in events:
        if dataset and event["dataset"] != dataset:
            continue
        if event["severity_score"] < severity_min:
            continue
        if anomaly_type and event["anomaly_type"] != anomaly_type:
            continue
        item = dict(event)
        if not include_sop_history:
            sop_hist = list(item.get("sop_history", []))
            item["sop_history_count"] = len(sop_hist)
            item.pop("sop_history", None)
        filtered.append(item)

    total = len(filtered)
    page = filtered[offset:offset + limit]
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": page,
    }

@app.get("/anomalies/{anomaly_id}")
async def get_anomaly_detail(anomaly_id: int):
    event = _find_anomaly_event(anomaly_id)
    if event is not None:
        return event
    raise HTTPException(status_code=404, detail="anomaly_not_found")

@app.get("/anomalies/{anomaly_id}/source")
async def get_anomaly_source(anomaly_id: int):
    event = _find_anomaly_event(anomaly_id)
    if event is None:
        raise HTTPException(status_code=404, detail="anomaly_not_found")
    return _build_anomaly_source_payload(event)

@app.post("/anomalies/{anomaly_id}/sop")
async def generate_anomaly_sop(anomaly_id: int, payload: SOPRequest):
    event = _find_anomaly_event(anomaly_id)
    if event is None:
        raise HTTPException(status_code=404, detail="anomaly_not_found")

    llm_error = None
    mode = "fallback"
    sop_text = _fallback_sop(event, payload)

    provider, api_key, _endpoint = _sop_llm_config()
    should_try_llm = provider in {"groq", "openai"} and bool(api_key)
    if payload.force_llm and not should_try_llm:
        raise HTTPException(status_code=503, detail="llm_not_configured")

    if should_try_llm:
        try:
            sop_text = await asyncio.to_thread(_generate_sop_with_llm, event, payload)
            mode = "llm"
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, RuntimeError, ValueError) as exc:
            llm_error = str(exc)
            if payload.force_llm:
                raise HTTPException(status_code=503, detail=f"llm_generation_failed: {exc}")

    history_entry = {
        "created_at_ms": _now_ms(),
        "mode": mode,
        "provider": provider,
        "model": payload.model or (SOP_GROQ_MODEL if provider == "groq" else SOP_OPENAI_MODEL),
        "objective": payload.objective,
        "constraints": list(payload.constraints),
        "sop": sop_text,
        "llm_error": llm_error,
    }
    event.setdefault("sop_history", []).append(history_entry)
    _append_sop_history_record({
        "anomaly_id": anomaly_id,
        "dataset": event.get("dataset", ""),
        "tick": event.get("tick", 0),
        **history_entry,
    })

    return {
        "anomaly_id": anomaly_id,
        "mode": mode,
        "sop": sop_text,
        "llm_error": llm_error,
        "history_entry": history_entry,
        "sop_history_total": len(event.get("sop_history", [])),
        "source": _build_anomaly_source_payload(event),
    }

@app.get("/anomalies/{anomaly_id}/sop/history")
async def get_anomaly_sop_history(anomaly_id: int):
    event = _find_anomaly_event(anomaly_id)
    if event is None:
        raise HTTPException(status_code=404, detail="anomaly_not_found")
    return {
        "anomaly_id": anomaly_id,
        "items": list(event.get("sop_history", [])),
        "total": len(event.get("sop_history", [])),
    }

@app.get("/api/feedback_history")
async def get_feedback_history_api(limit: int = 5):
    return _load_recent_feedback(limit)

@app.post("/change_dataset")
async def trigger_dataset_swap(req: SwapRequest):
    global DATASET, model, optimizer, feats_dim
    if req.dataset not in ['SMD', 'MSL', 'SMAP', 'ESP32', 'synthetic']:
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
        ft_optimizer = torch.optim.Adam(new_model.parameters(), lr=FT_LR, weight_decay=1e-5)
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

    _emit_policy_event(
        "calibration",
        status,
        "adaptive calibration executed",
        {
            "rollback": bool(rollback),
            "initial_loss": float(initial_loss),
            "final_loss": float(final_loss),
            "best_loss": float(best_loss),
            "steps": int(len(loss_trace)),
        },
    )

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

    # ── Capture raw window snapshot for fine-tuning ──────────────────────────
    raw_window_blob: Optional[bytes] = None
    if payload.raw_window is not None:
        try:
            raw_arr = np.array(payload.raw_window, dtype=np.float32)
            raw_window_blob = raw_arr.tobytes()
        except Exception:
            raw_window_blob = None
    elif model is not None and len(live_buffer) >= model.n_window:
        try:
            window_snap = list(live_buffer)[-model.n_window:]
            raw_arr = np.array(window_snap, dtype=np.float32)
            raw_window_blob = raw_arr.tobytes()
        except Exception:
            raw_window_blob = None
    record["raw_window"] = raw_window_blob

    # ── FIXED: snapshot BEFORE refresh so we detect the flip correctly ────────
    was_recommended_before = bool(retrain_state.get("recommended", False))

    async with feedback_db_lock:
        row_id = await asyncio.to_thread(_save_feedback_row, record)
        latest_counts = await asyncio.to_thread(_load_feedback_counters)
    feedback_counters.update(latest_counts)
    _refresh_retrain_recommendation(force=False)

    # ── Fire adaptive fine-tune if recommendation just became active ──────────
    if retrain_state.get("recommended") and not was_recommended_before:
        _launch_finetune_task()

    _enqueue_influx(
        "operator_feedback",
        {
            "dataset": DATASET,
            "model_version": model_registry.get("model_version", "default"),
            "anomaly_type": payload.anomaly_type or "unknown",
            "severity_level": payload.severity_level or "unknown",
        },
        {
            "was_anomaly": bool(payload.was_anomaly),
            "tick": int(payload.tick) if payload.tick is not None else -1,
            "confidence": _safe_float(payload.confidence),
            "system_loss": _safe_float(payload.system_loss),
            "threshold": _safe_float(payload.threshold),
            "calibrate_requested": bool(payload.calibrate_requested),
        },
        timestamp_ms=record["created_at_ms"],
    )

    return {
        "status": "recorded",
        "id": row_id,
        "feedback": feedback_counters,
        "retraining": retrain_state,
    }


@app.post("/api/retrain")
async def trigger_manual_retrain(note: Optional[str] = None):
    """
    Manually trigger a fine-tuning cycle from the dashboard or operator CLI.
    Does NOT require the retrain_state recommendation flag to be set.
    Returns immediately; fine-tuning runs in the background.
    """
    if model is None:
        raise HTTPException(status_code=503, detail="model_not_loaded")
    if ft_optimizer is None:
        raise HTTPException(status_code=503, detail="ft_optimizer_not_initialized")

    _launch_finetune_task()

    _emit_policy_event(
        "manual_retrain",
        "triggered",
        note or "operator-initiated manual fine-tune",
        {
            "model_version": str(model_registry.get("model_version", "default")),
            "feedback_total": int(feedback_counters.get("total", 0)),
        },
    )

    return {
        "status": "finetune_started",
        "current_version": model_registry.get("model_version", "default"),
        "note": note,
        "feedback_totals": feedback_counters,
    }

@app.post("/api/anomaly/trigger")
async def trigger_manual_anomaly(payload: ManualAnomalyTriggerPayload):
    requested_ticks = int(payload.ticks)
    manual_anomaly_state["pending_ticks"] = max(int(manual_anomaly_state.get("pending_ticks", 0)), requested_ticks)
    manual_anomaly_state["last_trigger_ts"] = time.time()
    manual_anomaly_state["last_reason"] = (payload.reason or "").strip()[:200]

    return {
        "status": "manual_anomaly_armed",
        "pending_ticks": int(manual_anomaly_state["pending_ticks"]),
        "reason": manual_anomaly_state["last_reason"],
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

@app.get("/policy/suggest")
async def policy_suggest(explore: bool = False):
    global rl_policy_last_suggestion
    if not FEATURE_RL_POLICY_SUGGESTIONS:
        return {
            "enabled": False,
            "reason": "FEATURE_RL_POLICY_SUGGESTIONS=false",
        }
    if rl_policy_manager is None:
        return {
            "enabled": True,
            "ready": False,
            "reason": "RL policy manager not initialized",
        }

    snapshot = _build_rl_metrics_snapshot()
    current_policy = _current_policy_snapshot()
    suggestion = rl_policy_manager.suggest(snapshot, current_policy, explore=bool(explore))
    rl_policy_last_suggestion = suggestion

    _emit_policy_event(
        "rl_suggestion",
        "generated",
        suggestion.get("reason", ""),
        {
            "suggestion_id": suggestion.get("suggestion_id", ""),
            "action": suggestion.get("action", "hold"),
            "state_key": suggestion.get("state_key", ""),
            "explore": bool(explore),
        },
    )

    return {
        "enabled": True,
        "ready": True,
        "metrics_snapshot": snapshot,
        "suggestion": suggestion,
    }

@app.post("/policy/reward")
async def policy_reward(payload: RLRewardPayload):
    if not FEATURE_RL_POLICY_SUGGESTIONS:
        raise HTTPException(status_code=400, detail="rl_policy_suggestions_disabled")
    if rl_policy_manager is None:
        raise HTTPException(status_code=503, detail="rl_policy_manager_unavailable")

    next_snapshot = _build_rl_metrics_snapshot()
    try:
        result = rl_policy_manager.record_reward(
            suggestion_id=payload.suggestion_id,
            reward=float(payload.reward),
            next_metrics=next_snapshot,
            note=payload.note or "",
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="suggestion_id_not_found")

    _emit_policy_event(
        "rl_suggestion",
        "reward_recorded",
        payload.note or "reward recorded",
        {
            "suggestion_id": payload.suggestion_id,
            "reward": float(payload.reward),
            "action": result.get("action", "hold"),
            "updated_q": float(result.get("updated_q", 0.0)),
        },
    )

    return {
        "status": "recorded",
        "update": result,
        "next_metrics": next_snapshot,
    }

@app.get("/policy/stats")
async def policy_stats():
    if not FEATURE_RL_POLICY_SUGGESTIONS:
        return {
            "enabled": False,
            "reason": "FEATURE_RL_POLICY_SUGGESTIONS=false",
        }
    if rl_policy_manager is None:
        return {
            "enabled": True,
            "ready": False,
            "reason": "RL policy manager not initialized",
        }
    return {
        "enabled": True,
        "ready": True,
        "stats": rl_policy_manager.get_stats(),
        "last_suggestion": rl_policy_last_suggestion,
    }

@app.post("/policy/apply")
async def policy_apply(payload: RLApplyPayload):
    if not FEATURE_RL_POLICY_SUGGESTIONS:
        raise HTTPException(status_code=400, detail="rl_policy_suggestions_disabled")
    if rl_policy_manager is None:
        raise HTTPException(status_code=503, detail="rl_policy_manager_unavailable")

    mode = str(payload.mode or "canary").strip().lower()
    if mode not in {"dry_run", "canary", "force"}:
        raise HTTPException(status_code=400, detail="invalid_mode")

    pending = rl_policy_manager.get_pending(payload.suggestion_id)
    if pending is None and rl_policy_last_suggestion and rl_policy_last_suggestion.get("suggestion_id") == payload.suggestion_id:
        pending = dict(rl_policy_last_suggestion)
    if pending is None:
        raise HTTPException(status_code=404, detail="suggestion_id_not_found")

    suggested_policy_raw = pending.get("suggested_policy", {})
    if not isinstance(suggested_policy_raw, dict):
        raise HTTPException(status_code=400, detail="invalid_suggestion_payload")

    current_policy = _current_policy_snapshot()
    candidate_policy = _normalize_policy_values(suggested_policy_raw)
    guardrail = _policy_guardrail_report(current_policy, candidate_policy)
    canary = _policy_canary_report(current_policy, candidate_policy, payload.canary_points)
    note = (payload.note or "").strip()[:512]
    action = str(pending.get("action", "hold"))

    if not guardrail["passed"]:
        _emit_policy_event(
            "rl_policy_apply",
            "rejected",
            "guardrail_violation",
            {
                "suggestion_id": payload.suggestion_id,
                "mode": mode,
                "violations": "; ".join(guardrail["violations"]),
            },
        )
        return {
            "status": "rejected",
            "reason": "guardrail_violation",
            "guardrail": guardrail,
            "canary": canary,
            "current_policy": current_policy,
            "candidate_policy": candidate_policy,
        }

    if mode == "canary":
        if not canary.get("ready", False):
            return {
                "status": "buffering",
                "reason": "insufficient_history_for_canary",
                "guardrail": guardrail,
                "canary": canary,
                "current_policy": current_policy,
                "candidate_policy": candidate_policy,
            }
        if not canary.get("passed", False):
            _emit_policy_event(
                "rl_policy_apply",
                "rejected",
                "canary_failed",
                {
                    "suggestion_id": payload.suggestion_id,
                    "mode": mode,
                    "alert_rate_delta": float(canary.get("alert_rate_delta", 0.0)),
                },
            )
            return {
                "status": "rejected",
                "reason": "canary_failed",
                "guardrail": guardrail,
                "canary": canary,
                "current_policy": current_policy,
                "candidate_policy": candidate_policy,
            }

    if mode == "dry_run":
        return {
            "status": "dry_run",
            "guardrail": guardrail,
            "canary": canary,
            "current_policy": current_policy,
            "candidate_policy": candidate_policy,
        }

    runtime_policy.update(candidate_policy)
    _refresh_retrain_recommendation(force=True)
    apply_entry = _record_policy_apply_entry(
        suggestion_id=payload.suggestion_id,
        action=action,
        previous_policy=current_policy,
        candidate_policy=candidate_policy,
        mode=mode,
        note=note,
        guardrail=guardrail,
        canary=canary,
    )

    _emit_policy_event(
        "rl_policy_apply",
        "applied",
        note or "policy applied",
        {
            "apply_id": apply_entry.get("id", ""),
            "suggestion_id": payload.suggestion_id,
            "mode": mode,
            "action": action,
            "fused_threshold_default": float(candidate_policy["fused_threshold_default"]),
            "retrain_min_feedback": int(candidate_policy["retrain_min_feedback"]),
            "drift_z_threshold": float(candidate_policy["drift_z_threshold"]),
        },
    )

    return {
        "status": "applied",
        "entry": apply_entry,
        "active_policy": _current_policy_snapshot(),
    }

@app.post("/policy/rollback")
async def policy_rollback(payload: RLRollbackPayload):
    if not FEATURE_RL_POLICY_SUGGESTIONS:
        raise HTTPException(status_code=400, detail="rl_policy_suggestions_disabled")

    target = _find_apply_entry(payload.apply_id)
    if target is None:
        raise HTTPException(status_code=404, detail="apply_entry_not_found")

    previous_policy_raw = target.get("previous_policy", {})
    if not isinstance(previous_policy_raw, dict):
        raise HTTPException(status_code=400, detail="invalid_apply_history")

    restored_policy = _normalize_policy_values(previous_policy_raw)
    runtime_policy.update(restored_policy)
    _refresh_retrain_recommendation(force=True)

    note = (payload.note or "").strip()[:512]
    rollback_entry = _record_policy_rollback_entry(target, note or "manual rollback")

    _emit_policy_event(
        "rl_policy_apply",
        "rolled_back",
        note or "policy rollback",
        {
            "rollback_id": rollback_entry.get("id", ""),
            "target_apply_id": rollback_entry.get("target_apply_id", ""),
            "suggestion_id": rollback_entry.get("suggestion_id", ""),
        },
    )

    return {
        "status": "rolled_back",
        "rollback": rollback_entry,
        "active_policy": _current_policy_snapshot(),
    }

@app.get("/policy/history")
async def policy_history(limit: int = Query(20, ge=1, le=200)):
    entries = list(policy_apply_history)
    entries.reverse()
    return {
        "total": len(entries),
        "limit": int(limit),
        "items": entries[:limit],
    }

@app.post("/retrain/mark_applied")
async def retrain_mark_applied(payload: RetrainAppliedPayload):
    retrain_state["recommended"] = False
    retrain_state["reason"] = ""
    retrain_state["last_applied_ts"] = time.time()
    if payload.model_version:
        model_registry["model_version"] = payload.model_version

    _emit_policy_event(
        "retrain_application",
        "acknowledged",
        payload.note or "retrain marked as applied",
        {
            "model_version": payload.model_version or model_registry.get("model_version", "default"),
            "last_applied_ts": float(retrain_state["last_applied_ts"]),
        },
    )
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
        recent_fused_scores = deque(maxlen=100)
        
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
            recent_fused_scores.append(float(fused_score))

            degradation_velocity = 0.0
            predicted_ttf_ticks = -1
            rul_status = "NOMINAL (Stable Timeline)"

            if len(recent_fused_scores) >= 10:
                y = np.array(recent_fused_scores)
                x = np.arange(len(y))
                # Linear extrapolation
                slope, _ = np.polyfit(x, y, 1)
                degradation_velocity = float(slope)
                
                rul_status = f"NOMINAL (Deviation vel: {degradation_velocity:+.4f}/tick)"
                
                critical_threshold = fused_threshold * 2.0 
                if slope > 0.00001:
                    predicted_ttf_ticks = max(1, int((critical_threshold - float(fused_score)) / slope))

            is_anomalous = fused_score > fused_threshold
            manual_override_active = False
            manual_override_reason = ""
            if int(manual_anomaly_state.get("pending_ticks", 0)) > 0:
                manual_override_active = True
                manual_override_reason = str(manual_anomaly_state.get("last_reason", ""))
                manual_anomaly_state["pending_ticks"] = max(0, int(manual_anomaly_state["pending_ticks"]) - 1)
                fused_score = float(max(fused_score, fused_threshold * 1.35))
                is_anomalous = True
                rul_status = "MANUAL TEST ANOMALY TRIGGERED"
            
            if is_anomalous and not manual_override_active:
                if degradation_velocity > 0.005:
                    rul_status = f"IMPEDING FAILURE! Velocity {degradation_velocity:.3f}. RUL: ~{predicted_ttf_ticks} ticks (mins)."
                elif degradation_velocity > 0.0001:
                    rul_status = f"DETERIORATING. Velocity {degradation_velocity:.4f}. RUL: ~{predicted_ttf_ticks} ticks (mins)."
                else:
                    rul_status = "ANOMALOUS SIG (Velocity flattened. Standby.)"

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
            if manual_override_active:
                anomaly_type = "manual_test_anomaly"
                severity_score = max(int(severity_score), 95)
                severity_level = "critical"
                confidence = max(float(confidence), 0.99)
            top_contributors, blended_vec = _rank_contributors(recon_loss, forecast_loss, top_k=5)
            similar_history = _get_similar_history(blended_vec, top_k=3)
            hints = _investigation_hints(anomaly_type, top_contributors, last_score_meta["corr_score"])
            if manual_override_active:
                lead_hint = "Manual anomaly trigger activated for tester validation."
                if manual_override_reason:
                    lead_hint += f" Reason: {manual_override_reason}"
                hints = [lead_hint, *hints]

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

            anomaly_source_info = None
            if FEATURE_ANOMALY_SOURCE_TAB:
                anomaly_source_info = {
                    "breakdown": _build_anomaly_source_breakdown(),
                    "correlation_change": _correlation_change_snapshot(
                        np.asarray(history_window, dtype=np.float64),
                        top_k=5,
                    ),
                }

            sensor_snapshot = None
            if is_anomalous:
                sensor_snapshot = _build_sensor_snapshot(
                    actual_sensors=np.asarray(actual_sensors, dtype=np.float64),
                    forecast_sensors=np.asarray(pred_future, dtype=np.float64),
                    recon_vec=np.asarray(recon_loss, dtype=np.float64),
                    forecast_vec=np.asarray(forecast_loss, dtype=np.float64),
                    top_contributors=top_contributors,
                )

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
                    "manual_trigger": manual_override_active,
                    "manual_trigger_reason": manual_override_reason,
                    "duration_steps": anomaly_streak,
                    "top_contributors": top_contributors,
                    "historical_similar": similar_history,
                    "investigation_hints": hints,
                    "degradation_velocity": degradation_velocity,
                    "predicted_ttf": predicted_ttf_ticks,
                    "rul_status": rul_status,
                },
            }

            _enqueue_influx(
                "anomaly_scores",
                {
                    "dataset": DATASET,
                    "model_version": model_registry.get("model_version", "default"),
                },
                {
                    "tick": int(current_tick),
                    "fused_score": float(fused_score),
                    "threshold": float(fused_threshold),
                    "recon_score": float(last_score_meta["recon_score"]),
                    "forecast_score": float(last_score_meta["forecast_score"]),
                    "corr_score": float(last_score_meta["corr_score"]),
                    "is_anomalous": bool(is_anomalous),
                    "severity_score": int(severity_score),
                    "confidence": float(confidence),
                },
            )

            if is_anomalous:
                _enqueue_influx(
                    "anomaly_events",
                    {
                        "dataset": DATASET,
                        "model_version": model_registry.get("model_version", "default"),
                        "anomaly_type": anomaly_type,
                        "severity_level": severity_level,
                    },
                    {
                        "tick": int(current_tick),
                        "fused_score": float(fused_score),
                        "threshold": float(fused_threshold),
                        "severity_score": int(severity_score),
                        "confidence": float(confidence),
                        "duration_steps": int(anomaly_streak),
                    },
                )

            if anomaly_source_info is not None:
                payload["anomaly_source"] = anomaly_source_info

            if is_anomalous:
                # Avoid paging real operators for tester-triggered anomalies.
                if not manual_override_active:
                    asyncio.create_task(_send_whatsapp_alert(
                        anomaly_type=anomaly_type,
                        severity_level=severity_level,
                        confidence=confidence,
                        top_sensor=top_contributors[0]["sensor"] if top_contributors else "unknown",
                        fused_score=fused_score,
                        threshold=fused_threshold,
                        tick=current_tick,
                        dataset=DATASET,
                    ))
                _record_anomaly_event(
                    tick=current_tick,
                    fused_score=fused_score,
                    threshold=fused_threshold,
                    severity_score=severity_score,
                    severity_level=severity_level,
                    confidence=confidence,
                    anomaly_type=anomaly_type,
                    duration_steps=anomaly_streak,
                    top_contributors=top_contributors,
                    historical_similar=similar_history,
                    investigation_hints=hints,
                    anomaly_source=anomaly_source_info,
                    sensor_snapshot=sensor_snapshot,
                )

            await websocket.send_text(json.dumps(payload))
            current_tick += 1
            
    except WebSocketDisconnect:
        active_connections.remove(websocket)
        print("UI Client Disconnected")

@app.post("/api/whatsapp/test")
async def test_whatsapp_alert():
    """Manually fire a test WhatsApp alert — useful for demos."""
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        return {"status": "error", "detail": "Twilio not configured. Check TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in .env."}
    if not TWILIO_TO_NUMBERS:
        return {"status": "error", "detail": "No recipients. Check TWILIO_TO_WHATSAPP in .env."}
    # Bypass cooldown for test calls
    global _twilio_last_sent_ts
    _twilio_last_sent_ts = 0.0
    await _send_whatsapp_alert(
        anomaly_type="collective_anomaly",
        severity_level="critical",
        confidence=0.983,
        top_sensor="s22",
        fused_score=2.871,
        threshold=1.500,
        tick=9999,
        dataset=DATASET,
    )
    return {"status": "test_sent", "recipients": TWILIO_TO_NUMBERS}

@app.get("/api/whatsapp/status")
async def whatsapp_status():
    """Returns Twilio configuration status (no secrets exposed)."""
    return {
        "configured": bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN),
        "recipient_count": len(TWILIO_TO_NUMBERS),
        "from_number": TWILIO_FROM_WHATSAPP,
        "cooldown_sec": TWILIO_COOLDOWN,
        "min_severity": TWILIO_MIN_SEV,
        "last_sent_ts": _twilio_last_sent_ts,
    }

@app.get("/")
def read_root():
    return {"status": "STP-TranAD Engine is running", "ready": model is not None}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)