[![License](https://img.shields.io/badge/License-BSD%203--Clause-red.svg)](https://github.com/imperial-qore/TranAD/blob/master/LICENSE)
![Python 3.7, 3.8](https://img.shields.io/badge/python-3.7%20%7C%203.8-blue.svg)
[![Hits](https://hits.seeyoufarm.com/api/count/incr/badge.svg?url=https%3A%2F%2Fgithub.com%2Fimperial-qore%2FTranAD&count_bg=%23FFC401&title_bg=%23555555&icon=&icon_color=%23E7E7E7&title=hits&edge_flat=false)](https://hits.seeyoufarm.com)

# TranAD
This repository supplements our paper "TranAD: Deep Transformer Networks for Anomaly Detection in Multivariate Time Series Data" accepted in VLDB 2022. This is a refactored version of the code used for results in the paper for ease of use. Follow the below steps to replicate each cell in the results table. The code is provided as-is. Due to limited resources, we are unable to provide support on any issues you may experience with installing or running the tool.

Our work has been discussed in the PodBean podcast! [See here](https://papersread.ai/e/tranad-deep-transformer-networks-for-anomaly-detection-in-multivariate-time-series-data-1663142096/). 

## Results
![Alt text](results/main.PNG?raw=true "results")

## Installation
This code needs Python-3.7 or higher.
```bash
pip3 install torch==1.8.1+cpu torchvision==0.9.1+cpu torchaudio===0.8.1 -f https://download.pytorch.org/whl/torch_stable.html
pip3 install -r requirements.txt
```

## Kafka Streaming (Local KRaft Broker)
The project now supports Kafka-based ingestion in addition to HTTP ingest.

1. Start local Kafka (from workspace root where `docker-compose.yml` exists):
```bash
docker compose up -d kafka
```

2. Start backend with Kafka consumer enabled:
```bash
set KAFKA_CONSUMER_ENABLED=true
set KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:29092
set KAFKA_TOPIC=telemetry-stream
python server.py
```

3. Start Kafka producer at 1 Hz (new script):
```bash
python kafka_producer.py --dataset SMD --topic telemetry-stream --hz 1 --loop
```

The consumer health is visible in `GET /status` under the `kafka` field.

## Synthetic Demo Dataset Generator (50 signals, 5 minutes)
Generate a custom demo dataset with a subtle correlation anomaly at 90 seconds:
```bash
python generate_synthetic_demo.py --signals 50 --seconds 300 --anomaly-second 90 --normalize
```

Outputs:
- `data/synthetic/demo_synthetic_50sig_5min.csv`
- `processed/synthetic/demo_synthetic_50sig_5min.npy`
- `processed/synthetic/demo_synthetic_50sig_5min_labels.npy`
- `data/synthetic/demo_synthetic_50sig_5min_meta.json`

To stream this demo to Kafka:
```bash
python kafka_producer.py --dataset demo --topic telemetry-stream --hz 1
```

## Synthetic Pipeline Dataset Generator (64 signals, production-style)
Generate a multivariate synthetic dataset tailored for end-to-end pipeline validation with point, contextual, collective/correlation-break, stuck-sensor, and burst-noise anomalies.

```bash
python generate_synthetic_pipeline_dataset.py --signals 64 --train-steps 12000 --test-steps 6000 --seed 77 --write-checkpoint
```

This writes directly to the files used by the backend synthetic tab route:
- `processed/synthetic/train.npy`
- `processed/synthetic/test.npy`
- `processed/synthetic/labels.npy`

Additional artifacts:
- `data/synthetic/pipeline_synthetic_test_64sig.csv`
- `data/synthetic/pipeline_synthetic_meta.json`
- `checkpoints/STP_TranAD_synthetic/model.ckpt` (dimension-compatible synthetic checkpoint)

Use it with simulator/producer by switching dataset to `synthetic` from the UI (or `/change_dataset`) and running:

```bash
python kafka_producer.py --dataset synthetic --topic telemetry-stream --hz 2 --loop
```

## ESP32 Integration (Synthetic Checkpoint Reuse)
The project now supports an `ESP32` dataset mode that reuses the synthetic checkpoint for prediction. This is intended for hardware-in-the-loop demos where an ESP32 publishes 50+ channel frames.

### 1) Enable ESP32 dataset mode
- Dashboard now includes an `ESP32` dataset tab.
- Backend dataset switching accepts `ESP32` and aliases model loading/checkpoint to synthetic artifacts.

Switch dataset to ESP32:
```bash
curl -X POST http://127.0.0.1:8000/change_dataset \
  -H "Content-Type: application/json" \
  -d '{"dataset":"ESP32"}'
```

### 2) Export synthetic replay data for ESP32
Generate an ESP32-friendly replay bundle from `processed/synthetic/test.npy`:
```bash
python scripts/export_esp32_replay.py --frames 512 --channels 64 --step-ms 500
```

You can also run the root launcher (same output):
```bash
python export_esp32_replay.py --frames 512 --channels 64 --step-ms 500
```

Outputs:
- `data/synthetic/esp32_replay.csv` (CSV with timestamp + channels)
- `data/synthetic/esp32_replay.h` (PROGMEM-ready quantized int16 table)
- `data/synthetic/esp32_replay_meta.json`

The generated header includes channel scales/offsets for dequantization on device:
- `value = q * scale[ch] + offset[ch]`

### 2.1) Arduino sketch (header replay publisher)
Sketch path:
- `esp32/TranAD_ESP32_Replay/TranAD_ESP32_Replay.ino`

Usage:
1. Generate replay header using step 2.
2. Copy `data/synthetic/esp32_replay.h` into `esp32/TranAD_ESP32_Replay/`.
3. Open sketch in Arduino IDE.
4. Install libraries:
   - `PubSubClient`
   - `ArduinoJson`
5. Set WiFi + broker values at top of sketch.
6. Flash to ESP32 and monitor serial logs.

Published MQTT schema (exact):
```json
{
  "timestamp_ms": 1710000000000,
  "source_id": "esp32-001",
  "seq_id": 1,
  "sensors": [0.1, 0.2, 0.3]
}
```

### 3) Run MQTT -> Kafka bridge
If your ESP32 publishes MQTT telemetry, run the bridge to feed Kafka:
```bash
python esp32_mqtt_kafka_bridge.py \
  --mqtt-host 127.0.0.1 \
  --mqtt-port 1883 \
  --mqtt-topic esp32/telemetry \
  --kafka-bootstrap-servers 127.0.0.1:29092 \
  --kafka-topic telemetry-stream \
  --dataset ESP32 \
  --expected-dimensions 64
```

Expected MQTT payload shape:
```json
{
  "timestamp_ms": 1710000000000,
  "sensors": [0.1, 0.2, 0.3],
  "source_id": "esp32-001",
  "seq_id": 1
}
```

Notes:
- `sensors` must be fixed-width and match active model dimensions (64 by default in this flow).
- If dimensions mismatch, messages are dropped by ingest guards.

### 4) Validate runtime state
```bash
curl http://127.0.0.1:8000/status
```

Check:
- `active_dataset` is `ESP32`
- `ingest.totals.accepted` increases
- `ingest.totals.dropped_dimension_mismatch` stays at `0`


## Phase 1 Rollout Flags (Non-Breaking)
Phase 1 introduces gated feature flags so we can ship incrementally without breaking existing clients.

Backend flags:
- `FEATURE_ANOMALY_SOURCE_TAB` (default `false`)
- `FEATURE_RL_POLICY_SUGGESTIONS` (default `false`)

Example:
```bash
set FEATURE_ANOMALY_SOURCE_TAB=true
set FEATURE_RL_POLICY_SUGGESTIONS=true
python server.py
```

Compatibility contract:
- Existing websocket payload fields remain unchanged.
- Existing endpoints (`/ingest`, `/feedback`, `/retrain/plan`, `/calibrate`) remain unchanged.
- Feature state is observable in `GET /status` under the `features` object.

When `FEATURE_ANOMALY_SOURCE_TAB=true`, websocket messages for anomalous ticks include an additional optional object:
- `anomaly_source.breakdown` (weights, z-scores, weighted component values, contribution percentages)
- `anomaly_source.correlation_change` (correlation-shift frobenius norm + top changed sensor pairs)

## Phase 3 Anomaly Investigation APIs
Additive APIs for historical anomaly exploration are now available:

- `GET /anomalies?dataset=SMD&severity_min=50&anomaly_type=point_anomaly&limit=100&offset=0`
- `GET /anomalies/{anomaly_id}`

Response payloads include severity, confidence, anomaly type, contributor ranking, score components, and optional `anomaly_source` details when enabled.

## Phase 5 InfluxDB Persistence (Telemetry + Governance)
The backend can now write streaming and governance events to InfluxDB with a non-blocking queue writer.

1. Start local services (from workspace root):
```bash
docker compose up -d kafka influxdb
```

2. Start backend with Influx enabled:
```bash
set INFLUX_ENABLED=true
set INFLUX_URL=http://127.0.0.1:8086
set INFLUX_TOKEN=catch-dev-token
set INFLUX_ORG=catch-org
set INFLUX_BUCKET=catch-telemetry
python server.py
```

3. Verify health in `GET /status` under `influx`.

Measurements emitted:
- `anomaly_scores`
- `anomaly_events`
- `operator_feedback`
- `drift_events`
- `ingest_quality`
- `policy_events`

Write failures are captured into `results/influx_deadletter.ndjson` for later replay.

## Phase 7 Backfill Baseline Operational History
Backfill existing feedback data and checkpoint-derived training metadata into InfluxDB:

1. Dry-run (no writes):
```bash
python scripts/backfill_influxdb.py --dry-run --preview
```

Optional verification-only check:
```bash
python scripts/backfill_influxdb.py --verify-only
```

2. Execute backfill:
```bash
set INFLUX_URL=http://127.0.0.1:8086
set INFLUX_TOKEN=catch-dev-token
set INFLUX_ORG=catch-org
set INFLUX_BUCKET=catch-telemetry
python scripts/backfill_influxdb.py
```

Execute and verify in one run:
```bash
python scripts/backfill_influxdb.py --verify
```

Backfilled measurements:
- `operator_feedback`
- `model_training` (checkpoint metadata)

Verification:
- Check script summary counts and non-zero `write_points_succeeded`.
- Confirm backend `GET /status` still reports healthy `influx` state.

## Phase 8 RL Suggestion-Only Policy Flow
Phase 8 introduces RL-driven policy suggestions without applying any parameter changes automatically.

Enable flag and start backend:
```bash
set FEATURE_RL_POLICY_SUGGESTIONS=true
set RL_POLICY_STATE_PATH=results/rl_policy_state.json
set RL_POLICY_LEARNING_RATE=0.12
set RL_POLICY_DISCOUNT=0.90
set RL_POLICY_EPSILON=0.05
python server.py
```

New endpoints:
- `GET /policy/suggest?explore=false` (generates manual-apply recommendation only)
- `POST /policy/reward` (records reward feedback for prior suggestion)
- `GET /policy/stats` (returns Q-table and pending-suggestion stats)

Safety contract:
- Suggestions do not mutate runtime thresholds or retrain criteria.
- Manual apply remains out of scope until Phase 9 guarded apply.

## Dataset Preprocessing
Preprocess all datasets using the command
```bash
python3 preprocess.py SMAP MSL SWaT WADI SMD MSDS UCR MBA NAB
```
Distribution rights to some datasets may not be available. Check the readme files in the `./data/` folder for more details. If you want to ignore a dataset, remove it from the above command to ensure that the preprocessing does not fail.

## Result Reproduction
To run a model on a dataset, run the following command:
```bash
python3 main.py --model <model> --dataset <dataset> --retrain
```
where `<model>` can be either of 'TranAD', 'GDN', 'MAD_GAN', 'MTAD_GAT', 'MSCRED', 'USAD', 'OmniAnomaly', 'LSTM_AD', and dataset can be one of 'SMAP', 'MSL', 'SWaT', 'WADI', 'SMD', 'MSDS', 'MBA', 'UCR' and 'NAB. To train with 20% data, use the following command 
```bash
python3 main.py --model <model> --dataset <dataset> --retrain --less
```
You can use the parameters in `src/params.json` to set values in `src/constants.py` for each file. 

> Note: to reproduce exact results of baselines, use their original codebases (links given in our paper) as the ones implemented in this repository are *not* the ones used in the paper, which used the original versions. The versions provided here are for use of initial comparison and may not be identical to the original versions.

For ablation studies, use the following models: 'TranAD_SelfConditioning', 'TranAD_Adversarial', 'TranAD_Transformer', 'TranAD_Basic'.

The output will provide anomaly detection and diagnosis scores and training time. For example:
```bash
$ python3 main.py --model TranAD --dataset SMAP --retrain 
Using backend: pytorch
Creating new model: TranAD
Training TranAD on SMAP
Epoch 0,        L1 = 0.09839354782306504
Epoch 1,        L1 = 0.039524692888342115
Epoch 2,        L1 = 0.022258711623482686
Epoch 3,        L1 = 0.01833707226553135
Epoch 4,        L1 = 0.016330517334598792
100%|███████████████████████████████████████████████████████████████████| 5/5 [00:03<00:00,  1.57it/s]
Training time:     3.1920 s
Testing TranAD on SMAP
{'FN': 0,
 'FP': 182,
 'Hit@100%': 1.0,
 'Hit@150%': 1.0,
 'NDCG@100%': 0.9999999999999999,
 'NDCG@150%': 0.9999999999999999,
 'TN': 7575,
 'TP': 748,
 'f1': 0.8915325929177795,
 'precision': 0.8043010666204187,
 'recall': 0.9999999866310163,
 'threshold': 0.16133320075167037}
```

All outputs can be run multiple times to ensure statistical significance. 

## Supplementary video

[![IMAGE ALT TEXT HERE](https://img.youtube.com/vi/b2fSzneXPsg/0.jpg)](https://www.youtube.com/watch?v=b2fSzneXPsg)

## Cite this work

Our paper is available in the Proceedings of VLDB: http://vldb.org/pvldb/vol15/p1201-tuli.pdf.
If you use this work, please cite using the following bibtex entry.
```bibtex
@article{tuli2022tranad,
  title={{TranAD: Deep Transformer Networks for Anomaly Detection in Multivariate Time Series Data}},
  author={Tuli, Shreshth and Casale, Giuliano and Jennings, Nicholas R},
  journal={Proceedings of VLDB},
  volume={15},
  number={6},
  pages={1201-1214},
  year={2022}
}
```

## License

BSD-3-Clause. 
Copyright (c) 2022, Shreshth Tuli.
All rights reserved.

See License file for more details.
