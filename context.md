# CATCH STP-TranAD Implementation Context

## 1) Goal and Scope
This project evolved from a baseline TranAD-style anomaly detection setup into a production-oriented, streaming, explainable, and adaptive system.

Major objectives implemented:
- Real-time ingestion hardening for noisy telemetry.
- Forecast-aware anomaly detection instead of reconstruction-only scoring.
- Explainable alerts in backend payloads and frontend operator UX.
- Dynamic dataset hot-swap with Synthetic dataset support.
- Adaptive learning and governance loop with operator feedback capture, drift monitoring, and retrain recommendation signals.

Workspace areas used:
- TranAD-main: model, streaming backend, simulator, offline evaluation.
- Frontend: dashboard, explainability UI, operator feedback actions.

## 2) Final End-to-End System Architecture
Data flow:
1. Kafka-style simulator streams data to backend ingest endpoint.
2. Backend sanitizes input, validates timestamps, imputes missing values, and buffers sequence windows.
3. STP_TranAD runs one-step causal inference from historical window.
4. Backend computes three anomaly components:
   - Reconstruction component.
   - Forecast residual component.
   - Correlation-shift component.
5. Backend fuses normalized components into a single anomaly score and dynamic threshold.
6. Backend classifies anomaly state and produces explainability payload.
7. Frontend renders fused score timeline, per-sensor actual vs forecast, and investigation insights.
8. Operator can acknowledge or dismiss alerts, which is persisted as feedback.
9. Governance loop computes drift and raises retrain recommendation signals.
10. Optional guarded online calibration can adapt the model with rollback protection.

## 3) Proposed Neural Network Design (Implemented)
Model: STP_TranAD in TranAD-main/src/models.py

Core design:
- Input: multivariate sequence window with 100 timesteps.
- Patching:
  - patch_size = 5
  - n_patches = 20
  - patch projection maps each patch to feature embedding space.
- Spatial topology learning:
  - MultiheadAttention across features as pure PyTorch substitute for GAT behavior.
  - Feature merge to d_model.
- Temporal modeling:
  - PositionalEncoding on patch timeline.
  - Transformer encoder stack for sequence representation.
- Dual reconstruction branch:
  - Decoder 1 gives first reconstruction output x1.
  - Decoder 2 gives refined reconstruction output x2.
- Forecast branch:
  - Forecaster head predicts H = 10 horizon steps.
  - Forecast reshaped to horizon x batch x features.
- Learnable multi-task balancing:
  - log_vars parameter used to weight reconstruction, prior, and forecast losses.

Training-side behavior:
- Joint optimization includes reconstruction, prior-related, and forecast terms.
- Uncertainty weighting via log_vars reduces manual loss tuning burden.

Inference-side behavior:
- Online pipeline uses historical window to predict current point.
- Forecast head output is explicitly used in frontend and scoring logic.

## 4) Detailed Implementation by Phase

### Phase 1: Ingestion Reliability and Stream Stability
Implemented in TranAD-main/server.py and TranAD-main/kafka_simulator.py.

Backend ingestion hardening:
- Timestamp validation with max backward tolerance and skew tracking.
- Dimension mismatch detection and drop logic.
- NaN or invalid sensor value imputation using last valid values.
- Outlier detection using rolling z-score.
- Degraded-mode tagging when imputation ratio is high.
- Ingestion statistics counters for accepted and dropped data quality events.

Simulator hardening:
- Configurable stream cadence via STREAM_PERIOD_SEC.
- POST retry and backoff behavior.
- Runtime adaptation to active dataset via status polling.

### Phase 2: Fused Scoring (Recon + Forecast + Correlation)
Implemented in TranAD-main/server.py and aligned in TranAD-main/main.py.

Online scoring updates:
- Component score history buffers for recon, forecast, corr, and fused.
- Positive z-score normalization for each component.
- Weighted fusion with env-configurable weights.
- Dynamic threshold based on percentile after warmup window.
- Anomaly decision based on fused score vs threshold.

Offline alignment in evaluation:
- STP component extraction functions compute reconstruction arrays, forecast arrays, and correlation shifts.
- Fuse component arrays in offline evaluation using same conceptual weighting strategy.

### Phase 3: Explainability and Investigation UX
Implemented across TranAD-main/server.py and Frontend/src/App.tsx.

Backend explainability payload:
- Severity score and severity level.
- Confidence estimation.
- Anomaly type classification:
  - point_anomaly
  - contextual_anomaly
  - collective_anomaly
- Top contributing sensors with contribution percentages.
- Similar historical anomalies using vector similarity.
- Investigation hints for operator triage.

Frontend explainability UI:
- Displays severity, anomaly type, confidence, duration.
- Shows score components (recon, forecast, corr).
- Contributor cards for top sensors.
- Historical similar anomaly list.
- Investigation path hints panel.
- Dynamic threshold line on fused score chart.

### Dataset Expansion: Synthetic Dataset End-to-End
Implemented in server, simulator, and frontend.

Backend:
- Added synthetic in change_dataset allowlist.
- Added synthetic checkpoint and processed data path mapping.

Simulator:
- Added synthetic stream source routing to processed/synthetic/test.npy.

Frontend:
- Added Synthetic tab in dataset switch UI.

### Phase 4: Adaptive Learning and Governance
Implemented primarily in TranAD-main/server.py and integrated with Frontend/src/App.tsx.

Feedback persistence:
- SQLite-backed operator feedback store.
- Endpoints:
  - POST /feedback
  - GET /feedback/summary
- Tracks labels for acknowledged and dismissed alerts, plus optional context.

Drift monitoring:
- Background governance loop computes drift metrics from fused score history.
- Baseline vs recent distribution shift measured as z_shift.
- Drift event trigger with cooldown.

Retrain recommendation state:
- Recommendation is raised when drift events or feedback volume crosses thresholds.
- Endpoints:
  - GET /retrain/plan
  - POST /retrain/mark_applied

Model governance metadata:
- Model registry tracks dataset, model version, checkpoint path, load time, calibration counters.
- Optional checkpoint registry selection logic for production version selection.

Guarded online calibration:
- Multi-step adaptation with warmup and finetune stages.
- Gradient clipping and early-stop behavior.
- Rollback to model and optimizer snapshots when adaptation diverges or degrades.

Frontend operator workflow integration:
- Acknowledge button submits positive anomaly feedback.
- Dismiss button submits negative feedback and requests calibration.
- Feedback status shown in UI.

## 5) Stability Fix Added After Phase 4
Issue observed:
- WebSocket crash after dataset hot-swap due to mixed-dimension historical vectors in similarity computation.
- Example mismatch: shape 30 vs shape 38.

Fix implemented in TranAD-main/server.py:
- Clear recent alert history and anomaly streak during ingestion state reset.
- Add shape guard inside cosine similarity function.
- Skip historical similarity candidates whose vector shape differs from current vector.

Result:
- Cross-dataset switching no longer crashes explainability similarity path.

## 6) Key Backend API Surface
Operational endpoints:
- POST /ingest
- GET /status
- POST /change_dataset
- POST /calibrate

Phase 4 endpoints:
- POST /feedback
- GET /feedback/summary
- GET /retrain/plan
- POST /retrain/mark_applied

WebSocket:
- WS /ws/stream for live telemetry, fused score, threshold, and explainability payload.

## 7) Configuration Knobs
Examples of important env controls in server:
- Fused scoring: weights, percentile threshold, warmup size.
- Drift governance: monitor interval, z threshold, cooldown.
- Feedback and retrain: database path, recommendation thresholds.
- Calibration: warmup steps, finetune steps, patience, tolerance.

Simulator controls:
- STREAM_PERIOD_SEC
- retry and backoff settings

## 8) Verification Guide (Phase 4)
1. Start backend and frontend.
2. Stream telemetry through simulator.
3. Switch datasets including Synthetic and confirm no websocket crash.
4. Trigger alert operations in UI:
   - Acknowledge alert.
   - Dismiss alert.
5. Verify feedback persistence via GET /feedback/summary.
6. Verify governance payload via GET /status and GET /retrain/plan.
7. Invoke calibration and confirm guarded response fields include rollback status.
8. Mark retrain applied with POST /retrain/mark_applied and verify recommendation reset.

## 9) Files with Major Changes
- TranAD-main/server.py
- TranAD-main/kafka_simulator.py
- TranAD-main/main.py
- Frontend/src/App.tsx

## 10) Copy-Paste Prompt for Nano Banana (Architecture Diagram)
Use this exact prompt:

Create a clean, technical neural network architecture diagram for a model named STP_TranAD (Spatio-Temporal Predictive Transformer for anomaly detection). Use a white or light background, high contrast text, and clear directional arrows. Make it publication-quality and suitable for an engineering design document.

Model details to visualize:
- Input tensor: multivariate time series window with shape (Seq=100, Batch, Features=F).
- Step 1 Patching:
  - Split sequence into patches of size 5, giving 20 patches.
  - Reshape to show patch tensor organization.
  - Linear patch projection from patch_size=5 to d_feat=16.
- Step 2 Spatial topology learning per patch:
  - Multihead self-attention across feature dimension (as pure PyTorch replacement for graph attention behavior).
  - Merge feature embeddings with linear layer to d_model=64.
- Step 3 Temporal encoder:
  - Add positional encoding over 20 patch tokens.
  - Transformer encoder with 2 layers, 8 heads, feedforward 256.
  - Output memory representation.
- Step 4 Dual reconstruction branch (Branch A):
  - Use last encoded token as decoder target.
  - Decoder 1 -> recon output x1 through linear+sigmoid to F features.
  - Decoder 2 -> refined recon output x2 through linear+sigmoid to F features.
- Step 5 Forecast branch (Branch B):
  - Forecaster MLP: Linear(64->128) -> ReLU -> Linear(128->F*H) -> Sigmoid.
  - Horizon H=10.
  - Reshape output to (H=10, Batch, Features=F).
- Step 6 Multi-task loss weighting block:
  - Show learnable log_vars for loss balancing of reconstruction, prior-related, and forecast losses.

Also add an inference scoring panel connected to outputs:
- Reconstruction error from x2.
- Forecast residual from forecast head.
- Correlation-shift score from recent sensor-correlation matrices.
- Positive z-normalization for each component.
- Weighted fusion: 0.55 recon + 0.30 forecast + 0.15 corr.
- Dynamic percentile thresholding and anomaly decision.

Layout requirements:
- Left to right flow.
- Branch A and Branch B visually separated then re-joined in scoring panel.
- Annotate tensor shapes near key transitions.
- Use subtle color coding by stage:
  - Input and patching,
  - spatial attention,
  - temporal transformer,
  - reconstruction branch,
  - forecast branch,
  - scoring and decision.
- Include a legend for symbols and abbreviations.
- Output as one single architecture figure.
