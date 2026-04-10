import argparse
import glob
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    from influxdb_client import InfluxDBClient, Point, WritePrecision
    from influxdb_client.client.write_api import SYNCHRONOUS
except ImportError:
    InfluxDBClient = None
    Point = None
    WritePrecision = None
    SYNCHRONOUS = None

try:
    import torch
except ImportError:
    torch = None


@dataclass
class BackfillSummary:
    feedback_rows_read: int = 0
    feedback_points_prepared: int = 0
    checkpoint_files_read: int = 0
    training_points_prepared: int = 0
    write_points_attempted: int = 0
    write_points_succeeded: int = 0
    write_points_failed: int = 0


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f == float("inf") or f == float("-inf"):
        return None
    if f != f:
        return None
    return f


def _safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dataset_from_checkpoint_path(path: str) -> str:
    folder = Path(path).parent.name
    parts = folder.split("_")
    if not parts:
        return "unknown"
    return parts[-1]


def _as_ns_from_ms(timestamp_ms: int) -> int:
    return int(timestamp_ms) * 1_000_000


def _build_feedback_points(db_path: str, summary: BackfillSummary) -> list[Any]:
    if not os.path.exists(db_path):
        return []

    points: list[Any] = []
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT created_at_ms, dataset, tick, was_anomaly, severity_level,
                   confidence, anomaly_type, calibrate_requested, system_loss, threshold
            FROM operator_feedback
            ORDER BY created_at_ms ASC
            """
        ).fetchall()

    summary.feedback_rows_read = len(rows)

    for row in rows:
        created_at_ms = _safe_int(row[0])
        if created_at_ms is None:
            continue
        dataset = str(row[1] or "unknown")
        tick = _safe_int(row[2])
        was_anomaly = bool(row[3])
        severity_level = str(row[4] or "unknown")
        confidence = _safe_float(row[5])
        anomaly_type = str(row[6] or "unknown")
        calibrate_requested = bool(row[7])
        system_loss = _safe_float(row[8])
        threshold = _safe_float(row[9])

        if Point is None:
            points.append(
                {
                    "measurement": "operator_feedback",
                    "tags": {
                        "dataset": dataset,
                        "severity_level": severity_level,
                        "anomaly_type": anomaly_type,
                        "backfill": "true",
                    },
                    "fields": {
                        "was_anomaly": was_anomaly,
                        "tick": tick if tick is not None else -1,
                        "confidence": confidence,
                        "system_loss": system_loss,
                        "threshold": threshold,
                        "calibrate_requested": calibrate_requested,
                    },
                    "timestamp_ms": created_at_ms,
                }
            )
            continue

        p = (
            Point("operator_feedback")
            .tag("dataset", dataset)
            .tag("severity_level", severity_level)
            .tag("anomaly_type", anomaly_type)
            .tag("backfill", "true")
            .field("was_anomaly", was_anomaly)
            .field("tick", tick if tick is not None else -1)
            .field("calibrate_requested", calibrate_requested)
            .time(_as_ns_from_ms(created_at_ms), WritePrecision.NS)
        )

        if confidence is not None:
            p = p.field("confidence", confidence)
        if system_loss is not None:
            p = p.field("system_loss", system_loss)
        if threshold is not None:
            p = p.field("threshold", threshold)

        points.append(p)

    summary.feedback_points_prepared = len(points)
    return points


def _load_checkpoint_metadata(path: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "parse_ok": False,
        "epoch": None,
        "accuracy_points": 0,
        "accuracy_last": None,
        "accuracy_best": None,
        "has_optimizer": False,
        "has_scheduler": False,
        "parse_error": "",
    }

    if torch is None:
        result["parse_error"] = "torch_not_installed"
        return result

    try:
        ckpt = torch.load(path, map_location="cpu", weights_only=False)
        result["parse_ok"] = True
        result["epoch"] = _safe_int(ckpt.get("epoch"))
        accuracy_list = ckpt.get("accuracy_list", [])
        if isinstance(accuracy_list, (list, tuple)):
            accuracy_values = [
                _safe_float(v if not isinstance(v, dict) else v.get("f1")) for v in accuracy_list
            ]
            accuracy_values = [v for v in accuracy_values if v is not None]
            result["accuracy_points"] = len(accuracy_values)
            if accuracy_values:
                result["accuracy_last"] = accuracy_values[-1]
                result["accuracy_best"] = max(accuracy_values)
        result["has_optimizer"] = "optimizer_state_dict" in ckpt
        result["has_scheduler"] = "scheduler_state_dict" in ckpt
    except Exception as exc:  # noqa: BLE001
        result["parse_error"] = str(exc)

    return result


def _build_training_points(checkpoint_glob: str, summary: BackfillSummary) -> list[Any]:
    files = sorted(glob.glob(checkpoint_glob))
    summary.checkpoint_files_read = len(files)
    points: list[Any] = []

    for ckpt_path in files:
        stat = os.stat(ckpt_path)
        mtime_ms = int(stat.st_mtime * 1000)
        dataset = _dataset_from_checkpoint_path(ckpt_path)
        meta = _load_checkpoint_metadata(ckpt_path)

        if Point is None:
            points.append(
                {
                    "measurement": "model_training",
                    "tags": {
                        "dataset": dataset,
                        "training_source": "checkpoint_backfill",
                        "backfill": "true",
                    },
                    "fields": {
                        "checkpoint_path": ckpt_path,
                        "checkpoint_size_bytes": int(stat.st_size),
                        "parse_ok": bool(meta["parse_ok"]),
                        "epoch": meta["epoch"],
                        "accuracy_points": int(meta["accuracy_points"]),
                        "accuracy_last": meta["accuracy_last"],
                        "accuracy_best": meta["accuracy_best"],
                        "has_optimizer": bool(meta["has_optimizer"]),
                        "has_scheduler": bool(meta["has_scheduler"]),
                        "parse_error": str(meta["parse_error"]),
                    },
                    "timestamp_ms": mtime_ms,
                }
            )
            continue

        p = (
            Point("model_training")
            .tag("dataset", dataset)
            .tag("training_source", "checkpoint_backfill")
            .tag("backfill", "true")
            .field("checkpoint_path", ckpt_path)
            .field("checkpoint_size_bytes", int(stat.st_size))
            .field("parse_ok", bool(meta["parse_ok"]))
            .field("accuracy_points", int(meta["accuracy_points"]))
            .field("has_optimizer", bool(meta["has_optimizer"]))
            .field("has_scheduler", bool(meta["has_scheduler"]))
            .field("parse_error", str(meta["parse_error"]))
            .time(_as_ns_from_ms(mtime_ms), WritePrecision.NS)
        )

        if meta["epoch"] is not None:
            p = p.field("epoch", int(meta["epoch"]))
        if meta["accuracy_last"] is not None:
            p = p.field("accuracy_last", float(meta["accuracy_last"]))
        if meta["accuracy_best"] is not None:
            p = p.field("accuracy_best", float(meta["accuracy_best"]))

        points.append(p)

    summary.training_points_prepared = len(points)
    return points


def _write_points(points: list[Any], influx_url: str, influx_token: str, influx_org: str, influx_bucket: str, summary: BackfillSummary):
    if InfluxDBClient is None or Point is None or WritePrecision is None or SYNCHRONOUS is None:
        raise RuntimeError("influxdb-client is not installed. Install requirements first.")

    if not influx_token:
        raise RuntimeError("INFLUX_TOKEN is required for non-dry-run mode.")

    summary.write_points_attempted = len(points)
    if not points:
        return

    with InfluxDBClient(url=influx_url, token=influx_token, org=influx_org, timeout=10000) as client:
        write_api = client.write_api(write_options=SYNCHRONOUS)
        write_api.write(bucket=influx_bucket, org=influx_org, record=points)

    summary.write_points_succeeded = len(points)


def _query_measurement_count(client: Any, influx_org: str, influx_bucket: str, measurement: str) -> int:
    query = f'''from(bucket: "{influx_bucket}")
  |> range(start: -365d)
  |> filter(fn: (r) => r._measurement == "{measurement}")
  |> count()'''
    tables = client.query_api().query(query=query, org=influx_org)
    total = 0
    for table in tables:
        for record in table.records:
            total += int(record.get_value() or 0)
    return total


def _verify_influx_counts(influx_url: str, influx_token: str, influx_org: str, influx_bucket: str) -> int:
    if InfluxDBClient is None:
        print("verify_error: influxdb-client is not installed")
        return 1
    if not influx_token:
        print("verify_error: INFLUX_TOKEN is required for verification")
        return 1

    with InfluxDBClient(url=influx_url, token=influx_token, org=influx_org, timeout=10000) as client:
        model_training_count = _query_measurement_count(client, influx_org, influx_bucket, "model_training")
        operator_feedback_count = _query_measurement_count(client, influx_org, influx_bucket, "operator_feedback")

    print("=== Influx Verification ===")
    print(f"bucket: {influx_bucket}")
    print(f"model_training_count: {model_training_count}")
    print(f"operator_feedback_count: {operator_feedback_count}")
    return 0


def _print_summary(summary: BackfillSummary, dry_run: bool):
    print("=== Phase 7 Backfill Summary ===")
    print(f"dry_run: {dry_run}")
    print(f"feedback_rows_read: {summary.feedback_rows_read}")
    print(f"feedback_points_prepared: {summary.feedback_points_prepared}")
    print(f"checkpoint_files_read: {summary.checkpoint_files_read}")
    print(f"training_points_prepared: {summary.training_points_prepared}")
    print(f"write_points_attempted: {summary.write_points_attempted}")
    print(f"write_points_succeeded: {summary.write_points_succeeded}")
    print(f"write_points_failed: {summary.write_points_failed}")


def _dump_preview(feedback_points: list[Any], training_points: list[Any]):
    preview = {
        "feedback_preview": feedback_points[:2],
        "training_preview": training_points[:2],
    }
    print("preview_json:")
    print(json.dumps(preview, indent=2, default=str))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 7 backfill to InfluxDB (feedback + checkpoint metadata)")
    parser.add_argument("--dry-run", action="store_true", help="Prepare points and print summary without writing to InfluxDB")
    parser.add_argument("--feedback-db", default="results/operator_feedback.db", help="Path to feedback sqlite db")
    parser.add_argument("--checkpoints-glob", default="checkpoints/*/model.ckpt", help="Glob pattern for checkpoint files")
    parser.add_argument("--influx-url", default=os.getenv("INFLUX_URL", "http://127.0.0.1:8086"))
    parser.add_argument("--influx-token", default=os.getenv("INFLUX_TOKEN", ""))
    parser.add_argument("--influx-org", default=os.getenv("INFLUX_ORG", "catch-org"))
    parser.add_argument("--influx-bucket", default=os.getenv("INFLUX_BUCKET", "catch-telemetry"))
    parser.add_argument("--preview", action="store_true", help="Print a small JSON preview of prepared payloads")
    parser.add_argument("--verify", action="store_true", help="Verify Influx measurement counts after dry-run or write")
    parser.add_argument("--verify-only", action="store_true", help="Only verify Influx counts; skip preparing and writing points")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.verify_only:
        return _verify_influx_counts(
            influx_url=args.influx_url,
            influx_token=args.influx_token,
            influx_org=args.influx_org,
            influx_bucket=args.influx_bucket,
        )

    summary = BackfillSummary()

    feedback_points = _build_feedback_points(args.feedback_db, summary)
    training_points = _build_training_points(args.checkpoints_glob, summary)
    all_points = feedback_points + training_points

    if args.preview:
        _dump_preview(feedback_points, training_points)

    if args.dry_run:
        _print_summary(summary, dry_run=True)
        if args.verify:
            return _verify_influx_counts(
                influx_url=args.influx_url,
                influx_token=args.influx_token,
                influx_org=args.influx_org,
                influx_bucket=args.influx_bucket,
            )
        return 0

    try:
        _write_points(
            all_points,
            influx_url=args.influx_url,
            influx_token=args.influx_token,
            influx_org=args.influx_org,
            influx_bucket=args.influx_bucket,
            summary=summary,
        )
    except Exception as exc:  # noqa: BLE001
        summary.write_points_failed = summary.write_points_attempted or len(all_points)
        _print_summary(summary, dry_run=False)
        print(f"error: {exc}")
        return 1

    _print_summary(summary, dry_run=False)
    if args.verify:
        verify_code = _verify_influx_counts(
            influx_url=args.influx_url,
            influx_token=args.influx_token,
            influx_org=args.influx_org,
            influx_bucket=args.influx_bucket,
        )
        if verify_code != 0:
            return verify_code
    print(f"completed_at_utc: {datetime.now(timezone.utc).isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
