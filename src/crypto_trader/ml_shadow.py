# Post-cost validation, shadow predictions and deterministic promotion (LEARNING_ONLY).
from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from pathlib import Path

MIN_SHADOW_SAMPLES = 30
MIN_AUC = 0.55
MIN_MEAN_NET_BPS = 0.0


def post_cost_validation(
    metrics: dict, *, min_auc: float = MIN_AUC, min_mean_net_bps: float = MIN_MEAN_NET_BPS
) -> dict:
    wf = metrics.get("walk_forward", {})
    reasons = []
    if wf.get("fold_count", 0) < 2:
        reasons.append("insufficient_walk_forward_folds")
    if wf.get("auc", 0.0) < min_auc:
        reasons.append(f"auc_below_min:{wf.get('auc', 0.0)}<{min_auc}")
    if wf.get("mean_net_bps_valid", 0.0) <= min_mean_net_bps:
        reasons.append(f"net_edge_not_positive:{wf.get('mean_net_bps_valid', 0.0)}")
    return {"passed": not reasons, "reasons": reasons, "metrics": wf}


class ShadowStore:
    """Append-only shadow predictions; no order/risk/sizing authority."""

    def __init__(self, path) -> None:
        self.path = Path(path)

    def _load(self) -> list:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]

    def record(
        self,
        *,
        model_id: str,
        model_version: str,
        symbol: str,
        probability: float,
        expected_edge: float,
        confidence: float | None = None,
        feature_version: str = "scan-features-v1",
        timestamp: str | None = None,
    ) -> dict:
        row = {
            "prediction_id": "sh-" + secrets.token_hex(8),
            "model_id": model_id,
            "model_version": model_version,
            "symbol": symbol,
            "timestamp": timestamp or datetime.now(UTC).isoformat(),
            "prediction": "LONG" if probability >= 0.5 else "SHORT",
            "probability": probability,
            "confidence": confidence,
            "expected_edge": expected_edge,
            "feature_version": feature_version,
            "outcome_net_bps": None,
            "outcome_ts": None,
            "authority": "LEARNING_ONLY",
            "is_order": False,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        return row

    def attach_outcome(
        self, prediction_id: str, net_bps: float, outcome_ts: str | None = None
    ) -> bool:
        rows = self._load()
        found = False
        for row in rows:
            if row["prediction_id"] == prediction_id:
                row["outcome_net_bps"] = net_bps
                row["outcome_ts"] = outcome_ts or datetime.now(UTC).isoformat()
                found = True
        if found:
            self.path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
        return found

    def summary(self, model_id: str, model_version: str) -> dict:
        rows = [
            r
            for r in self._load()
            if r["model_id"] == model_id
            and r["model_version"] == model_version
            and r["outcome_net_bps"] is not None
        ]
        nets = [float(r["outcome_net_bps"]) for r in rows]
        wins = sum(1 for n in nets if n > 0)
        return {
            "samples": len(nets),
            "mean_net_bps": sum(nets) / len(nets) if nets else 0.0,
            "win_rate": wins / len(nets) if nets else 0.0,
        }


def decide_promotion(
    *,
    post_cost_passed: bool,
    fold_count: int,
    shadow_summary: dict,
    min_shadow: int = MIN_SHADOW_SAMPLES,
    min_mean_net: float = MIN_MEAN_NET_BPS,
) -> str:
    if not post_cost_passed or fold_count < 2:
        return "REJECT"
    if shadow_summary.get("samples", 0) < min_shadow:
        return "CONTINUE_SHADOW"
    if (
        shadow_summary.get("mean_net_bps", 0.0) > min_mean_net
        and shadow_summary.get("win_rate", 0.0) >= 0.5
    ):
        return "PROMOTE"
    return "REJECT"
