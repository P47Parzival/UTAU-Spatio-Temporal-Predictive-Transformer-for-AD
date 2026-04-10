import argparse
import asyncio
import json
import os
import time
from typing import Optional

import numpy as np
from aiokafka import AIOKafkaProducer

DEFAULT_TOPIC = os.getenv("KAFKA_TOPIC", "telemetry-stream")
DEFAULT_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:29092")
DEFAULT_HZ = float(os.getenv("PRODUCER_HZ", "1.0"))


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
        elif dataset == "synthetic":
            path = f"processed/{dataset}/test.npy"
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
    data = load_dataset_array(args.dataset, args.file)
    total = len(data)
    idx = args.start_index % total
    seq = 0
    period = 1.0 / max(args.hz, 1e-6)

    producer = AIOKafkaProducer(
        bootstrap_servers=[s.strip() for s in args.bootstrap_servers.split(",") if s.strip()],
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        acks="all",
    )

    await producer.start()
    print(
        f"[PRODUCER] Streaming dataset={args.dataset}, rows={total}, dims={data.shape[1]}, "
        f"topic={args.topic}, hz={args.hz:.3f}, bootstrap={args.bootstrap_servers}"
    )

    try:
        while True:
            sensors = data[idx].tolist()
            payload = {
                "timestamp_ms": int(time.time() * 1000),
                "sensors": sensors,
                "dataset": args.dataset,
                "source_id": args.source_id,
                "seq_id": seq,
            }
            await producer.send_and_wait(args.topic, payload)

            print(f"\r[PRODUCER] Sent seq={seq} idx={idx}/{total}", end="")
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
    parser.add_argument("--dataset", default="SMD", choices=["SMD", "MSL", "SMAP", "synthetic", "demo"])
    parser.add_argument("--file", default=None, help="Optional explicit .npy path")
    parser.add_argument("--topic", default=DEFAULT_TOPIC)
    parser.add_argument("--bootstrap-servers", default=DEFAULT_BOOTSTRAP)
    parser.add_argument("--hz", type=float, default=DEFAULT_HZ, help="Publish frequency in Hz (default: 1.0)")
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--source-id", default="local-producer")
    parser.add_argument("--loop", action="store_true", help="Loop dataset indefinitely")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        asyncio.run(stream_data(args))
    except KeyboardInterrupt:
        print("\n[PRODUCER] Interrupted by user.")
