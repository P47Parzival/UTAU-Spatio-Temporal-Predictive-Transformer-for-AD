import argparse
import importlib
import io
import json
import os
from contextlib import redirect_stderr

import numpy as np

_SCIPY_SIGNAL = None
_SCIPY_IMPORT_TRIED = False


def try_get_scipy_signal():
    global _SCIPY_SIGNAL, _SCIPY_IMPORT_TRIED
    if _SCIPY_IMPORT_TRIED:
        return _SCIPY_SIGNAL

    _SCIPY_IMPORT_TRIED = True
    try:
        # Some environments emit binary-compatibility traces on stderr; silence and fallback.
        with redirect_stderr(io.StringIO()):
            _SCIPY_SIGNAL = importlib.import_module("scipy.signal")
    except Exception:
        _SCIPY_SIGNAL = None
    return _SCIPY_SIGNAL


def sawtooth_wave(x: np.ndarray, width: float = 0.6, use_scipy: bool = True) -> np.ndarray:
    if use_scipy:
        scipy_signal = try_get_scipy_signal()
        if scipy_signal is not None:
            return scipy_signal.sawtooth(x, width=width)

    # NumPy fallback for environments where SciPy binary wheels are incompatible.
    width = float(np.clip(width, 1e-6, 1.0 - 1e-6))
    phase = (x / (2.0 * np.pi)) % 1.0
    up = (phase / width) * 2.0 - 1.0
    down = ((1.0 - phase) / (1.0 - width)) * 2.0 - 1.0
    return np.where(phase < width, up, down)


def build_base_series(num_steps: int, num_signals: int, seed: int, use_scipy: bool) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(num_steps, dtype=np.float64)

    # Latent industrial factors: rotating machinery load, AC ripple, and slower regime drift.
    latent_rpm = 0.90 * np.sin(2 * np.pi * t / 47.0) + 0.20 * np.sin(2 * np.pi * t / 13.0)
    latent_ac = 0.55 * np.sin(2 * np.pi * t / 5.0) + 0.10 * sawtooth_wave(2 * np.pi * t / 19.0, width=0.6, use_scipy=use_scipy)
    latent_regime = np.cumsum(rng.normal(0.0, 0.012, size=num_steps))
    latent_regime = (latent_regime - latent_regime.mean()) / (latent_regime.std() + 1e-8)

    factors = np.stack([latent_rpm, latent_ac, latent_regime], axis=1)
    mix = rng.normal(0.0, 1.0, size=(num_signals, 3))

    per_signal_bias = rng.uniform(0.35, 0.75, size=(1, num_signals))
    per_signal_amp = rng.uniform(0.45, 0.95, size=(1, num_signals))
    phase_1 = rng.uniform(0.0, 2 * np.pi, size=(1, num_signals))
    phase_2 = rng.uniform(0.0, 2 * np.pi, size=(1, num_signals))

    mixed = factors @ mix.T
    periodic = (
        0.25 * np.sin(2 * np.pi * t[:, None] / 31.0 + phase_1)
        + 0.18 * np.cos(2 * np.pi * t[:, None] / 9.0 + phase_2)
    )
    noise = rng.normal(0.0, 0.035, size=(num_steps, num_signals))

    data = per_signal_bias + per_signal_amp * mixed + periodic + noise
    return data


def inject_correlation_anomaly(data: np.ndarray, anomaly_start: int) -> tuple[np.ndarray, np.ndarray]:
    out = data.copy()
    num_steps = out.shape[0]
    t = np.arange(num_steps, dtype=np.float64)

    ramp = np.clip((t - anomaly_start) / 24.0, 0.0, 1.0)

    # Signal 12 (index 11): amplitude attenuation with slight anti-phase perturbation.
    s12 = out[:, 11]
    s12_baseline = np.mean(s12[max(0, anomaly_start - 60):anomaly_start])
    attenuation = 1.0 - 0.42 * ramp
    out[:, 11] = s12_baseline + (s12 - s12_baseline) * attenuation
    out[:, 11] += 0.055 * np.sin(2 * np.pi * t / 8.0 + 1.1) * ramp

    # Signal 4 (index 3): subtle baseline rise with low slope.
    s4_std = np.std(out[:anomaly_start, 3]) + 1e-8
    out[:, 3] += ramp * (0.22 * s4_std)

    labels = np.zeros_like(out)
    labels[anomaly_start:, 11] = 1.0
    labels[anomaly_start:, 3] = 1.0
    return out, labels


def normalize_per_signal(data: np.ndarray) -> np.ndarray:
    d_min = np.min(data, axis=0, keepdims=True)
    d_max = np.max(data, axis=0, keepdims=True)
    return (data - d_min) / (d_max - d_min + 1e-8)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate 50-signal synthetic industrial demo dataset")
    parser.add_argument("--signals", type=int, default=50)
    parser.add_argument("--seconds", type=int, default=300, help="Total duration at 1-second granularity")
    parser.add_argument("--anomaly-second", type=int, default=90)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--normalize", action="store_true", help="Normalize output to [0,1] per signal")
    parser.add_argument("--no-scipy", action="store_true", help="Force NumPy-only waveform generation")
    parser.add_argument("--csv-out", default="data/synthetic/demo_synthetic_50sig_5min.csv")
    parser.add_argument("--npy-out", default="processed/synthetic/demo_synthetic_50sig_5min.npy")
    parser.add_argument("--labels-out", default="processed/synthetic/demo_synthetic_50sig_5min_labels.npy")
    parser.add_argument("--meta-out", default="data/synthetic/demo_synthetic_50sig_5min_meta.json")
    args = parser.parse_args()

    if args.signals < 13:
        raise ValueError("signals must be >= 13 because anomaly references Signal 12")
    if args.anomaly_second < 0 or args.anomaly_second >= args.seconds:
        raise ValueError("anomaly-second must be within dataset duration")

    base = build_base_series(args.seconds, args.signals, args.seed, use_scipy=(not args.no_scipy))
    data, labels = inject_correlation_anomaly(base, args.anomaly_second)

    if args.normalize:
        data = normalize_per_signal(data)

    os.makedirs(os.path.dirname(args.csv_out), exist_ok=True)
    os.makedirs(os.path.dirname(args.npy_out), exist_ok=True)
    os.makedirs(os.path.dirname(args.labels_out), exist_ok=True)
    os.makedirs(os.path.dirname(args.meta_out), exist_ok=True)

    np.savetxt(args.csv_out, data, delimiter=",")
    np.save(args.npy_out, data)
    np.save(args.labels_out, labels)

    pre_corr = float(np.corrcoef(data[:args.anomaly_second, 3], data[:args.anomaly_second, 11])[0, 1])
    post_corr = float(np.corrcoef(data[args.anomaly_second:, 3], data[args.anomaly_second:, 11])[0, 1])

    metadata = {
        "description": "Synthetic industrial telemetry demo with subtle correlation anomaly",
        "sampling_hz": 1,
        "duration_seconds": args.seconds,
        "num_signals": args.signals,
        "anomaly_start_second": args.anomaly_second,
        "anomaly_details": {
            "signal_12": "Flow-rate amplitude attenuation",
            "signal_4": "Motor-temp baseline rise",
            "type": "correlation_break",
        },
        "correlation_s4_s12_before": pre_corr,
        "correlation_s4_s12_after": post_corr,
        "outputs": {
            "csv": args.csv_out,
            "npy": args.npy_out,
            "labels_npy": args.labels_out,
        },
    }

    with open(args.meta_out, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    print("Generated synthetic demo dataset:")
    print(f"  data shape: {data.shape}")
    print(f"  anomaly second: {args.anomaly_second}")
    print(f"  corr(s4,s12) before: {pre_corr:.4f}")
    print(f"  corr(s4,s12) after : {post_corr:.4f}")
    print(f"  csv: {args.csv_out}")
    print(f"  npy: {args.npy_out}")
    print(f"  labels: {args.labels_out}")
    print(f"  meta: {args.meta_out}")


if __name__ == "__main__":
    main()
