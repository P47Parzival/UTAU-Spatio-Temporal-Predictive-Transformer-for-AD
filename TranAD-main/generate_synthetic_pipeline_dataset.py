import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np


@dataclass
class GroupSlices:
    vibration: slice
    temperature: slice
    pressure: slice
    flow: slice
    electrical: slice


def _build_group_slices(num_signals: int) -> GroupSlices:
    # Keep a stable partition so anomaly regimes can target realistic subsystems.
    vib = max(8, int(round(num_signals * 0.25)))
    temp = max(8, int(round(num_signals * 0.20)))
    pressure = max(8, int(round(num_signals * 0.20)))
    flow = max(8, int(round(num_signals * 0.20)))

    assigned = vib + temp + pressure + flow
    electrical = max(8, num_signals - assigned)

    if vib + temp + pressure + flow + electrical > num_signals:
        overflow = vib + temp + pressure + flow + electrical - num_signals
        electrical = max(8, electrical - overflow)

    idx0 = 0
    idx1 = idx0 + vib
    idx2 = idx1 + temp
    idx3 = idx2 + pressure
    idx4 = idx3 + flow
    idx5 = num_signals

    # If any rounding drift remains, assign tail to electrical.
    idx4 = min(idx4, num_signals)
    idx5 = num_signals

    return GroupSlices(
        vibration=slice(idx0, idx1),
        temperature=slice(idx1, idx2),
        pressure=slice(idx2, idx3),
        flow=slice(idx3, idx4),
        electrical=slice(idx4, idx5),
    )


def _ar1_noise(rng: np.random.Generator, n_steps: int, n_dims: int, phi: float, sigma: float) -> np.ndarray:
    noise = np.zeros((n_steps, n_dims), dtype=np.float64)
    eps = rng.normal(0.0, sigma, size=(n_steps, n_dims))
    for t in range(1, n_steps):
        noise[t] = phi * noise[t - 1] + eps[t]
    return noise


def _build_base_series(n_steps: int, n_dims: int, seed: int) -> tuple[np.ndarray, GroupSlices]:
    rng = np.random.default_rng(seed)
    groups = _build_group_slices(n_dims)

    t = np.arange(n_steps, dtype=np.float64)

    # Latent factors inspired by benchmark telemetry behavior (SMD/SMAP/MSL/NAB styles).
    load = 0.9 * np.sin(2.0 * np.pi * t / 180.0) + 0.25 * np.sin(2.0 * np.pi * t / 37.0)
    ripple = 0.35 * np.sin(2.0 * np.pi * t / 8.0)
    ambient = 0.7 * np.sin(2.0 * np.pi * t / 720.0 + 0.4)

    # Slowly changing operating regime with smooth transitions.
    regime = np.zeros_like(t)
    regime_level = 0.0
    for start in range(0, n_steps, 600):
        regime_level += rng.normal(0.0, 0.25)
        end = min(start + 600, n_steps)
        regime[start:end] = regime_level
    regime = np.convolve(regime, np.ones(21, dtype=np.float64) / 21.0, mode="same")

    base = np.zeros((n_steps, n_dims), dtype=np.float64)
    phase = rng.uniform(0.0, 2.0 * np.pi, size=n_dims)
    amp = rng.uniform(0.5, 1.1, size=n_dims)
    bias = rng.uniform(0.3, 0.8, size=n_dims)

    noise = _ar1_noise(rng, n_steps, n_dims, phi=0.82, sigma=0.025)

    # Vibration-like channels: stronger high-frequency + load coupling.
    v = groups.vibration
    base[:, v] = (
        bias[v]
        + amp[v] * (1.3 * load[:, None] + 0.9 * ripple[:, None])
        + 0.25 * np.sin(2.0 * np.pi * t[:, None] / 21.0 + phase[v])
    )

    # Temperature channels: ambient + regime trend, smoother dynamics.
    te = groups.temperature
    base[:, te] = (
        bias[te]
        + amp[te] * (0.6 * load[:, None] + 1.2 * ambient[:, None] + 1.1 * regime[:, None])
        + 0.08 * np.sin(2.0 * np.pi * t[:, None] / 240.0 + phase[te])
    )

    # Pressure channels: load + periodic operation cycles.
    p = groups.pressure
    base[:, p] = (
        bias[p]
        + amp[p] * (1.0 * load[:, None] + 0.35 * ambient[:, None])
        + 0.30 * np.cos(2.0 * np.pi * t[:, None] / 55.0 + phase[p])
    )

    # Flow channels: tightly coupled to pressure and setpoint waves.
    f = groups.flow
    base[:, f] = (
        bias[f]
        + amp[f] * (0.85 * load[:, None] + 0.55 * np.sin(2.0 * np.pi * t[:, None] / 70.0 + phase[f]))
    )

    # Electrical channels: ripple + load with small random harmonic content.
    e = groups.electrical
    harmonics = (
        0.16 * np.sin(2.0 * np.pi * t[:, None] / 11.0 + phase[e])
        + 0.10 * np.cos(2.0 * np.pi * t[:, None] / 17.0 + phase[e])
    )
    base[:, e] = bias[e] + amp[e] * (1.1 * ripple[:, None] + 0.7 * load[:, None]) + harmonics

    data = base + noise
    return data, groups


def _inject_anomalies(
    test_data: np.ndarray,
    groups: GroupSlices,
    seed: int,
) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    rng = np.random.default_rng(seed + 17)
    out = test_data.copy()
    labels = np.zeros_like(out, dtype=np.float64)
    windows = []

    n_steps, n_dims = out.shape
    idx = np.arange(n_steps)

    # Regime 1: point spikes (NAB-style abrupt outliers).
    w1 = (int(n_steps * 0.12), int(n_steps * 0.18))
    spike_dims = rng.choice(n_dims, size=min(10, n_dims), replace=False)
    spike_times = rng.integers(w1[0], w1[1], size=28)
    for t0 in spike_times:
        d = int(rng.choice(spike_dims))
        mag = (3.5 + rng.random()) * (np.std(out[:, d]) + 1e-6)
        out[t0, d] += mag
        labels[t0, d] = 1.0
    windows.append({"name": "point_spikes", "start": w1[0], "end": w1[1], "channels": [int(x) for x in spike_dims]})

    # Regime 2: contextual thermal drift (SMAP/MSL-style context-dependent shift).
    w2 = (int(n_steps * 0.28), int(n_steps * 0.40))
    temp_idx = np.arange(groups.temperature.start, groups.temperature.stop)
    if temp_idx.size > 0:
        ramp = np.clip((idx - w2[0]) / max(1, (w2[1] - w2[0])), 0.0, 1.0)
        drift_mag = 0.9 * np.std(out[:, temp_idx], axis=0)
        out[:, temp_idx] += ramp[:, None] * drift_mag[None, :]
        labels[w2[0]:w2[1], temp_idx] = 1.0
        windows.append({"name": "contextual_thermal_drift", "start": w2[0], "end": w2[1], "channels": [int(x) for x in temp_idx.tolist()]})

    # Regime 3: collective correlation break in vibration block.
    w3 = (int(n_steps * 0.48), int(n_steps * 0.58))
    vib_idx = np.arange(groups.vibration.start, groups.vibration.stop)
    if vib_idx.size > 4:
        half = vib_idx.size // 2
        a = vib_idx[:half]
        b = vib_idx[half:]
        phase_shift = np.sin(2.0 * np.pi * idx / 23.0 + np.pi)
        out[w3[0]:w3[1], b] = (
            0.7 * out[w3[0]:w3[1], b]
            + 0.3 * phase_shift[w3[0]:w3[1], None]
            - 0.2 * out[w3[0]:w3[1], a[: b.size]]
        )
        labels[w3[0]:w3[1], vib_idx] = 1.0
        windows.append({"name": "collective_correlation_break", "start": w3[0], "end": w3[1], "channels": [int(x) for x in vib_idx.tolist()]})

    # Regime 4: stuck-at fault in flow subsystem.
    w4 = (int(n_steps * 0.66), int(n_steps * 0.76))
    flow_idx = np.arange(groups.flow.start, groups.flow.stop)
    if flow_idx.size > 0:
        stuck_dims = rng.choice(flow_idx, size=max(3, flow_idx.size // 4), replace=False)
        for d in stuck_dims:
            out[w4[0]:w4[1], d] = out[w4[0], d]
        labels[w4[0]:w4[1], stuck_dims] = 1.0
        windows.append({"name": "stuck_sensor", "start": w4[0], "end": w4[1], "channels": [int(x) for x in stuck_dims.tolist()]})

    # Regime 5: intermittent electrical burst noise.
    w5 = (int(n_steps * 0.82), int(n_steps * 0.92))
    elec_idx = np.arange(groups.electrical.start, groups.electrical.stop)
    if elec_idx.size > 0:
        burst_dims = rng.choice(elec_idx, size=max(4, elec_idx.size // 2), replace=False)
        burst_noise = rng.normal(0.0, 2.6 * np.std(out[:, burst_dims], axis=0), size=(w5[1] - w5[0], burst_dims.size))
        out[w5[0]:w5[1], burst_dims] += burst_noise
        labels[w5[0]:w5[1], burst_dims] = 1.0
        windows.append({"name": "electrical_noise_burst", "start": w5[0], "end": w5[1], "channels": [int(x) for x in burst_dims.tolist()]})

    return out, labels, windows


def _scale_with_train_stats(train: np.ndarray, test: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    d_min = train.min(axis=0, keepdims=True)
    d_max = train.max(axis=0, keepdims=True)
    denom = np.maximum(d_max - d_min, 1e-8)

    train_scaled = np.clip((train - d_min) / denom, 0.0, 1.0)
    test_scaled = np.clip((test - d_min) / denom, 0.0, 1.0)
    return train_scaled, test_scaled


def _write_compat_checkpoint(checkpoint_path: Path, n_dims: int) -> Optional[str]:
    try:
        import torch
        argv_backup = list(sys.argv)
        sys.argv = [sys.argv[0]]
        from src.models import STP_TranAD
        sys.argv = argv_backup
    except Exception as exc:  # noqa: BLE001
        try:
            sys.argv = argv_backup
        except Exception:
            pass
        return f"checkpoint skipped (torch/model unavailable): {exc}"

    model = STP_TranAD(n_dims).double()
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-5, weight_decay=1e-5)
    payload = {
        "epoch": 0,
        "accuracy_list": [],
        "model_state_dict": model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
    }

    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(payload, str(checkpoint_path))
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate high-fidelity synthetic telemetry for end-to-end pipeline validation")
    parser.add_argument("--signals", type=int, default=64, help="Number of telemetry channels (must be > 50)")
    parser.add_argument("--train-steps", type=int, default=12000, help="Training sequence length")
    parser.add_argument("--test-steps", type=int, default=6000, help="Testing/streaming sequence length")
    parser.add_argument("--seed", type=int, default=77)
    parser.add_argument("--write-checkpoint", action="store_true", help="Write a synthetic-compatible STP_TranAD checkpoint")

    parser.add_argument("--train-out", default="processed/synthetic/train.npy")
    parser.add_argument("--test-out", default="processed/synthetic/test.npy")
    parser.add_argument("--labels-out", default="processed/synthetic/labels.npy")
    parser.add_argument("--test-csv-out", default="data/synthetic/pipeline_synthetic_test_64sig.csv")
    parser.add_argument("--meta-out", default="data/synthetic/pipeline_synthetic_meta.json")
    parser.add_argument("--checkpoint-out", default="checkpoints/STP_TranAD_synthetic/model.ckpt")
    args = parser.parse_args()

    if args.signals <= 50:
        raise ValueError("signals must be > 50 for this pipeline dataset")
    if args.train_steps < 2000 or args.test_steps < 2000:
        raise ValueError("train-steps and test-steps should each be >= 2000")

    total_steps = int(args.train_steps + args.test_steps)
    base, groups = _build_base_series(total_steps, int(args.signals), int(args.seed))

    train_raw = base[: args.train_steps]
    test_nominal = base[args.train_steps :]
    test_anom, labels, windows = _inject_anomalies(test_nominal, groups, int(args.seed))

    train_scaled, test_scaled = _scale_with_train_stats(train_raw, test_anom)

    train_path = Path(args.train_out)
    test_path = Path(args.test_out)
    labels_path = Path(args.labels_out)
    csv_path = Path(args.test_csv_out)
    meta_path = Path(args.meta_out)

    train_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.parent.mkdir(parents=True, exist_ok=True)
    labels_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.parent.mkdir(parents=True, exist_ok=True)

    np.save(train_path, train_scaled.astype(np.float64))
    np.save(test_path, test_scaled.astype(np.float64))
    np.save(labels_path, labels.astype(np.float64))
    np.savetxt(csv_path, test_scaled, delimiter=",")

    checkpoint_message = None
    if args.write_checkpoint:
        checkpoint_message = _write_compat_checkpoint(Path(args.checkpoint_out), int(args.signals))

    channel_groups = {
        "vibration": [groups.vibration.start, groups.vibration.stop],
        "temperature": [groups.temperature.start, groups.temperature.stop],
        "pressure": [groups.pressure.start, groups.pressure.stop],
        "flow": [groups.flow.start, groups.flow.stop],
        "electrical": [groups.electrical.start, groups.electrical.stop],
    }

    point_labels_per_timestep = labels.max(axis=1)
    meta = {
        "description": "Industrial multivariate synthetic dataset for STP-TranAD pipeline validation",
        "source_inspiration": {
            "benchmarks": ["SMD", "SMAP", "MSL", "NAB"],
            "public_references": [
                "https://github.com/NetManAIOps/OmniAnomaly",
                "https://github.com/numenta/NAB",
                "https://github.com/khundman/telemanom",
            ],
            "anomaly_taxonomy": ["point", "contextual", "collective/correlation", "stuck-sensor", "noise-burst"],
        },
        "sampling_hz": 1,
        "signals": int(args.signals),
        "train_steps": int(args.train_steps),
        "test_steps": int(args.test_steps),
        "channel_groups": channel_groups,
        "anomaly_windows": windows,
        "summary": {
            "test_anomalous_points": int(point_labels_per_timestep.sum()),
            "test_anomalous_ratio": float(point_labels_per_timestep.mean()),
        },
        "outputs": {
            "train_npy": str(train_path.as_posix()),
            "test_npy": str(test_path.as_posix()),
            "labels_npy": str(labels_path.as_posix()),
            "test_csv": str(csv_path.as_posix()),
            "checkpoint": str(Path(args.checkpoint_out).as_posix()) if args.write_checkpoint else None,
        },
        "notes": {
            "labels_format": "(test_steps, signals) with 1.0 for anomalous channel/time and 0.0 otherwise",
            "stream_ready": "processed/synthetic/test.npy is directly consumable by simulator/producer synthetic route",
            "checkpoint_message": checkpoint_message,
        },
    }

    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    print("Synthetic pipeline dataset generated successfully")
    print(f"train shape: {train_scaled.shape}")
    print(f"test shape:  {test_scaled.shape}")
    print(f"labels shape:{labels.shape}")
    print(f"train out: {train_path}")
    print(f"test out:  {test_path}")
    print(f"labels out:{labels_path}")
    print(f"meta out:  {meta_path}")
    if args.write_checkpoint:
        if checkpoint_message:
            print(f"checkpoint note: {checkpoint_message}")
        else:
            print(f"checkpoint out: {Path(args.checkpoint_out)}")


if __name__ == "__main__":
    main()
