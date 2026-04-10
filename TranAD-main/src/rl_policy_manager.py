import json
import random
import time
from pathlib import Path
from typing import Any, Optional


class RLPolicyManager:
    ACTIONS = [
        "hold",
        "threshold_up_small",
        "threshold_down_small",
        "threshold_up_medium",
        "threshold_down_medium",
        "retrain_feedback_up",
        "retrain_feedback_down",
        "drift_z_up",
        "drift_z_down",
    ]

    def __init__(
        self,
        state_path: str,
        learning_rate: float = 0.12,
        discount_factor: float = 0.90,
        epsilon: float = 0.05,
        random_seed: int = 17,
    ):
        self.state_path = Path(state_path)
        self.learning_rate = float(learning_rate)
        self.discount_factor = float(discount_factor)
        self.epsilon = float(epsilon)
        self.random = random.Random(random_seed)

        self.q_table: dict[str, dict[str, float]] = {}
        self.pending: dict[str, dict[str, Any]] = {}
        self.action_counts: dict[str, int] = {a: 0 for a in self.ACTIONS}
        self.suggestion_seq = 0
        self.last_error = ""

        self._load()

    def _load(self):
        if not self.state_path.exists():
            return
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            self.q_table = {
                str(state): {str(action): float(value) for action, value in action_map.items()}
                for state, action_map in payload.get("q_table", {}).items()
            }
            self.pending = {
                str(k): dict(v) for k, v in payload.get("pending", {}).items()
            }
            loaded_counts = payload.get("action_counts", {})
            for action in self.ACTIONS:
                self.action_counts[action] = int(loaded_counts.get(action, 0))
            self.suggestion_seq = int(payload.get("suggestion_seq", 0))
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)

    def _save(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "q_table": self.q_table,
            "pending": self.pending,
            "action_counts": self.action_counts,
            "suggestion_seq": self.suggestion_seq,
            "updated_at_ms": int(time.time() * 1000),
        }
        self.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _ensure_state(self, state_key: str):
        if state_key not in self.q_table:
            self.q_table[state_key] = {a: 0.0 for a in self.ACTIONS}

    @staticmethod
    def _bucket(value: float, low: float, high: float) -> str:
        if value < low:
            return "low"
        if value < high:
            return "mid"
        return "high"

    def build_state_key(self, metrics: dict[str, Any]) -> str:
        drift_z = float(metrics.get("drift_z", 0.0) or 0.0)
        anomaly_rate = float(metrics.get("anomaly_rate_recent", 0.0) or 0.0)
        feedback_total = float(metrics.get("feedback_total", 0.0) or 0.0)
        confirmed = float(metrics.get("feedback_confirmed", 0.0) or 0.0)
        dismissed = float(metrics.get("feedback_dismissed", 0.0) or 0.0)
        denom = max(1.0, confirmed + dismissed)
        confirmation_ratio = confirmed / denom

        drift_bucket = self._bucket(drift_z, 1.5, 3.0)
        anomaly_bucket = self._bucket(anomaly_rate, 0.10, 0.25)
        feedback_bucket = self._bucket(feedback_total, 20.0, 60.0)
        confidence_bucket = self._bucket(confirmation_ratio, 0.45, 0.70)

        return (
            f"drift:{drift_bucket}|"
            f"anom:{anomaly_bucket}|"
            f"fb:{feedback_bucket}|"
            f"confirm:{confidence_bucket}"
        )

    def _choose_action(self, state_key: str, explore: bool) -> str:
        self._ensure_state(state_key)
        q_state = self.q_table[state_key]
        do_explore = bool(explore and self.random.random() < self.epsilon)
        if do_explore:
            return self.random.choice(self.ACTIONS)

        best_action = "hold"
        best_value = q_state.get(best_action, -1e9)
        for action in self.ACTIONS:
            value = q_state.get(action, 0.0)
            if value > best_value:
                best_value = value
                best_action = action
        return best_action

    def _recommendation_from_action(self, action: str, current_policy: dict[str, float]) -> dict[str, Any]:
        threshold = float(current_policy.get("fused_threshold_default", 1.5))
        retrain_feedback = float(current_policy.get("retrain_min_feedback", 40))
        drift_z = float(current_policy.get("drift_z_threshold", 2.5))

        threshold_delta = 0.0
        retrain_delta = 0.0
        drift_delta = 0.0

        if action == "threshold_up_small":
            threshold_delta = +0.05
        elif action == "threshold_down_small":
            threshold_delta = -0.05
        elif action == "threshold_up_medium":
            threshold_delta = +0.10
        elif action == "threshold_down_medium":
            threshold_delta = -0.10
        elif action == "retrain_feedback_up":
            retrain_delta = +5.0
        elif action == "retrain_feedback_down":
            retrain_delta = -5.0
        elif action == "drift_z_up":
            drift_delta = +0.10
        elif action == "drift_z_down":
            drift_delta = -0.10

        suggested_threshold = min(3.0, max(0.5, threshold + threshold_delta))
        suggested_retrain_feedback = int(min(200, max(10, round(retrain_feedback + retrain_delta))))
        suggested_drift_z = min(5.0, max(1.0, drift_z + drift_delta))

        return {
            "action": action,
            "current_policy": {
                "fused_threshold_default": threshold,
                "retrain_min_feedback": int(round(retrain_feedback)),
                "drift_z_threshold": drift_z,
            },
            "suggested_policy": {
                "fused_threshold_default": suggested_threshold,
                "retrain_min_feedback": suggested_retrain_feedback,
                "drift_z_threshold": suggested_drift_z,
            },
            "deltas": {
                "fused_threshold_default": threshold_delta,
                "retrain_min_feedback": int(round(retrain_delta)),
                "drift_z_threshold": drift_delta,
            },
            "manual_apply_required": True,
        }

    def suggest(self, metrics: dict[str, Any], current_policy: dict[str, float], explore: bool = False) -> dict[str, Any]:
        state_key = self.build_state_key(metrics)
        action = self._choose_action(state_key, explore=explore)
        recommendation = self._recommendation_from_action(action, current_policy)

        self.suggestion_seq += 1
        suggestion_id = f"rl-suggestion-{self.suggestion_seq}"
        recommendation.update(
            {
                "suggestion_id": suggestion_id,
                "state_key": state_key,
                "explore": bool(explore),
                "created_at_ms": int(time.time() * 1000),
                "reason": "RL suggestion generated. Manual apply required in later guarded phase.",
            }
        )

        self.pending[suggestion_id] = {
            "state_key": state_key,
            "action": action,
            "created_at_ms": recommendation["created_at_ms"],
            "current_policy": dict(recommendation.get("current_policy", {})),
            "suggested_policy": dict(recommendation.get("suggested_policy", {})),
            "deltas": dict(recommendation.get("deltas", {})),
            "manual_apply_required": bool(recommendation.get("manual_apply_required", True)),
            "reason": str(recommendation.get("reason", "")),
        }
        self.action_counts[action] += 1
        self._save()
        return recommendation

    def get_pending(self, suggestion_id: str) -> Optional[dict[str, Any]]:
        pending = self.pending.get(str(suggestion_id))
        if pending is None:
            return None
        return dict(pending)

    def record_reward(
        self,
        suggestion_id: str,
        reward: float,
        next_metrics: dict[str, Any],
        note: str = "",
    ) -> dict[str, Any]:
        pending = self.pending.get(suggestion_id)
        if pending is None:
            raise KeyError("suggestion_id_not_found")

        state_key = str(pending["state_key"])
        action = str(pending["action"])
        next_state_key = self.build_state_key(next_metrics)

        self._ensure_state(state_key)
        self._ensure_state(next_state_key)

        old_q = float(self.q_table[state_key].get(action, 0.0))
        max_next = max(self.q_table[next_state_key].values()) if self.q_table[next_state_key] else 0.0

        updated_q = old_q + self.learning_rate * ((float(reward) + self.discount_factor * max_next) - old_q)
        self.q_table[state_key][action] = float(updated_q)

        del self.pending[suggestion_id]
        self._save()

        return {
            "suggestion_id": suggestion_id,
            "state_key": state_key,
            "next_state_key": next_state_key,
            "action": action,
            "reward": float(reward),
            "old_q": old_q,
            "updated_q": float(updated_q),
            "note": note,
        }

    def get_stats(self) -> dict[str, Any]:
        populated_states = 0
        for _, actions in self.q_table.items():
            if any(abs(v) > 1e-12 for v in actions.values()):
                populated_states += 1

        return {
            "states": len(self.q_table),
            "states_with_nonzero_q": populated_states,
            "pending_suggestions": len(self.pending),
            "action_counts": self.action_counts,
            "learning_rate": self.learning_rate,
            "discount_factor": self.discount_factor,
            "epsilon": self.epsilon,
            "last_error": self.last_error,
        }
