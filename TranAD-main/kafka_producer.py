import argparse
import asyncio
import json
import os
import socket
import time
from typing import Optional
from urllib import error as urlerror
from urllib import request as urlrequest

import numpy as np
from aiokafka import AIOKafkaProducer

DEFAULT_TOPIC = os.getenv("KAFKA_TOPIC", "telemetry-stream")
DEFAULT_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:29092")
DEFAULT_HZ = float(os.getenv("PRODUCER_HZ", "1.0"))
DEFAULT_STATUS_URL = os.getenv("BACKEND_STATUS_URL", "http://127.0.0.1:8000/status")

SUPPORTED_DATASETS = {"SMD", "MSL", "SMAP", "synthetic", "ESP32", "demo"}


def fetch_active_dataset(status_url: str, timeout_sec: float) -> Optional[str]:
    try:
        with urlrequest.urlopen(status_url, timeout=float(timeout_sec)) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urlerror.URLError, socket.timeout, TimeoutError, OSError, json.JSONDecodeError, ValueError):
        return None

    dataset = payload.get("active_dataset")
    if dataset in SUPPORTED_DATASETS:
        return dataset
    return None


def load_dataset_array(dataset: str, file_path: Optional[str]) -> np.ndarray:
    if file_path:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Dataset file not found: {file_path}")
        arr = np.load(file_path)
    else:
        if dataset == "SMD":
            path = f"processed/{dataset}/machine-1-1_test.npy"
        elif dataset == "MSL":
            path = f"processed/{dataset}/C-1_test.npy"
        elif dataset == "SMAP":
            path = f"processed/{dataset}/A-1_test.npy"
        elif dataset in {"synthetic", "ESP32"}:
            path = f"processed/{dataset}/test.npy"
            if dataset == "ESP32":
                path = "processed/synthetic/test.npy"
        elif dataset == "demo":
            path = "processed/synthetic/demo_synthetic_50sig_5min.npy"
        else:
            raise ValueError(f"Unsupported dataset: {dataset}")
        if not os.path.exists(path):
            raise FileNotFoundError(f"Dataset file not found: {path}")
        arr = np.load(path)

    if arr.ndim != 2:
        raise ValueError(f"Expected 2D array, got shape {arr.shape}")
    return np.asarray(arr, dtype=np.float64)


async def stream_data(args: argparse.Namespace) -> None:
    follow_active_dataset = bool(not args.no_follow_active_dataset and not args.file)

    current_dataset = args.dataset
    if follow_active_dataset:
        active_dataset = await asyncio.to_thread(fetch_active_dataset, args.status_url, args.status_timeout_sec)
        if active_dataset:
            current_dataset = active_dataset
        else:
            print(
                f"[PRODUCER] Status endpoint unreachable ({args.status_url}); "
                f"continuing with dataset={current_dataset}"
            )

    data = load_dataset_array(current_dataset, args.file)
    total = len(data)
    idx = args.start_index % total
    seq = 0
    period = 1.0 / max(args.hz, 1e-6)
    last_poll_ts = 0.0

    producer = AIOKafkaProducer(
        bootstrap_servers=[s.strip() for s in args.bootstrap_servers.split(",") if s.strip()],
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        acks="all",
    )

    await producer.start()
    print(
        f"[PRODUCER] Streaming dataset={current_dataset}, rows={total}, dims={data.shape[1]}, "
        f"topic={args.topic}, hz={args.hz:.3f}, bootstrap={args.bootstrap_servers}, "
        f"follow_active_dataset={follow_active_dataset}"
    )

    try:
        while True:
            now = time.time()
            if follow_active_dataset and (now - last_poll_ts) >= args.status_poll_sec:
                last_poll_ts = now
                active_dataset = await asyncio.to_thread(fetch_active_dataset, args.status_url, args.status_timeout_sec)
                if active_dataset and active_dataset != current_dataset:
                    data = load_dataset_array(active_dataset, None)
                    total = len(data)
                    idx = 0
                    current_dataset = active_dataset
                    print(
                        f"\n[PRODUCER] Active dataset changed -> {current_dataset}. "
                        f"Reloaded rows={total}, dims={data.shape[1]}"
                    )

            sensors = data[idx].tolist()
            payload = {
                "timestamp_ms": int(time.time() * 1000),
                "sensors": sensors,
                "dataset": current_dataset,
                "source_id": args.source_id,
                "seq_id": seq,
            }
            await producer.send_and_wait(args.topic, payload)

            print(f"\r[PRODUCER] Sent dataset={current_dataset} seq={seq} idx={idx}/{total}", end="")
            seq += 1
            idx += 1

            if idx >= total:
                if args.loop:
                    idx = 0
                else:
                    break

            await asyncio.sleep(period)
    finally:
        print("\n[PRODUCER] Stopping producer...")
        await producer.stop()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Kafka telemetry producer for STP-TranAD")
    parser.add_argument("--dataset", default="SMD", choices=sorted(SUPPORTED_DATASETS))
    parser.add_argument("--file", default=None, help="Optional explicit .npy path")
    parser.add_argument("--topic", default=DEFAULT_TOPIC)
    parser.add_argument("--bootstrap-servers", default=DEFAULT_BOOTSTRAP)
    parser.add_argument("--hz", type=float, default=DEFAULT_HZ, help="Publish frequency in Hz (default: 1.0)")
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--source-id", default="local-producer")
    parser.add_argument("--loop", action="store_true", help="Loop dataset indefinitely")
    parser.add_argument("--status-url", default=DEFAULT_STATUS_URL, help="Backend status URL used for active dataset polling")
    parser.add_argument("--status-poll-sec", type=float, default=2.0, help="How often to poll backend active dataset")
    parser.add_argument("--status-timeout-sec", type=float, default=1.0, help="Timeout for status polling request")
    parser.add_argument(
        "--no-follow-active-dataset",
        action="store_true",
        help="Disable automatic switch to backend active dataset",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        asyncio.run(stream_data(args))
    except KeyboardInterrupt:
        print("\n[PRODUCER] Interrupted by user.")
