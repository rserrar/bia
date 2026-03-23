from __future__ import annotations

from typing import Any


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        raw = value.strip()
        if raw == "":
            return None
        try:
            return float(raw)
        except Exception:
            return None
    return None


def default_policy_config() -> dict[str, Any]:
    return {
        "policy_version": "selection_policy_v1",
        "weights": {
            "loss": 0.55,
            "time": 0.15,
            "stability": 0.20,
            "quality": 0.10,
        },
        "loss_cap": 200000.0,
        "time_cap_seconds": 1800.0,
        "hard_time_limit_seconds": 3600.0,
        "allowed_statuses": {"trained", "accepted", "validated_phase0"},
    }


def evaluate_reference_candidate(proposal: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = config or default_policy_config()
    weights = policy.get("weights", {}) if isinstance(policy.get("weights"), dict) else {}
    w_loss = float(weights.get("loss", 0.55))
    w_time = float(weights.get("time", 0.15))
    w_stability = float(weights.get("stability", 0.20))
    w_quality = float(weights.get("quality", 0.10))

    allowed_statuses = set(policy.get("allowed_statuses", {"trained", "accepted", "validated_phase0"}))
    status = str(proposal.get("status", "")).strip()
    proposal_id = str(proposal.get("proposal_id", "")).strip()
    source_run_id = str(proposal.get("source_run_id", "")).strip()

    llm_metadata_raw = proposal.get("llm_metadata")
    llm_metadata: dict[str, Any] = llm_metadata_raw if isinstance(llm_metadata_raw, dict) else {}
    training_kpis_raw = llm_metadata.get("training_kpis")
    kpi_eval_raw = llm_metadata.get("kpi_evaluation")
    training_kpis: dict[str, Any] = training_kpis_raw if isinstance(training_kpis_raw, dict) else {}
    kpi_eval: dict[str, Any] = kpi_eval_raw if isinstance(kpi_eval_raw, dict) else {}

    val_loss = _to_float(training_kpis.get("val_loss_total"))
    if val_loss is None:
        val_loss = _to_float(kpi_eval.get("val_loss_total"))

    training_time = _to_float(training_kpis.get("training_time_seconds"))
    if training_time is None:
        training_time = _to_float(llm_metadata.get("training_time"))

    kpi_result = str(llm_metadata.get("kpi_result", "")).strip()

    constraints_failed: list[str] = []
    if status not in allowed_statuses:
        constraints_failed.append("status_not_allowed")
    if val_loss is None:
        constraints_failed.append("missing_val_loss_total")
    if kpi_result == "rejected_by_loss":
        constraints_failed.append("kpi_rejected")

    loss_cap = float(policy.get("loss_cap", 200000.0))
    time_cap_seconds = float(policy.get("time_cap_seconds", 1800.0))
    hard_time_limit_seconds = float(policy.get("hard_time_limit_seconds", 3600.0))

    normalized_loss = 0.0
    if val_loss is not None and loss_cap > 0:
        normalized_loss = max(0.0, 1.0 - min(val_loss, loss_cap) / loss_cap)

    normalized_time = 0.5
    if training_time is not None and time_cap_seconds > 0:
        normalized_time = max(0.0, 1.0 - min(training_time, time_cap_seconds) / time_cap_seconds)

    if status == "trained":
        normalized_stability = 1.0
    elif status == "accepted":
        normalized_stability = 0.75
    else:
        normalized_stability = 0.55

    if kpi_result == "promoted":
        normalized_quality = 1.0
    elif kpi_result == "":
        normalized_quality = 0.7
    else:
        normalized_quality = 0.5

    raw_score = 100.0 * (
        w_loss * normalized_loss
        + w_time * normalized_time
        + w_stability * normalized_stability
        + w_quality * normalized_quality
    )

    penalties: list[dict[str, Any]] = []
    final_score = raw_score
    if training_time is not None and training_time > hard_time_limit_seconds:
        penalties.append({"name": "hard_time_limit", "points": 15.0})
        final_score -= 15.0

    final_score = max(0.0, round(final_score, 4))
    eligible = len(constraints_failed) == 0

    if not eligible:
        selection_reason = "ineligible_due_to_constraints"
    elif status == "trained":
        selection_reason = "eligible_trained_candidate"
    else:
        selection_reason = "eligible_pretrained_candidate"

    return {
        "policy_version": str(policy.get("policy_version", "selection_policy_v1")),
        "proposal_id": proposal_id,
        "source_run_id": source_run_id,
        "status": status,
        "eligible": eligible,
        "score": final_score,
        "selection_reason": selection_reason,
        "constraints_failed": constraints_failed,
        "score_breakdown": {
            "weights": {
                "loss": w_loss,
                "time": w_time,
                "stability": w_stability,
                "quality": w_quality,
            },
            "normalized": {
                "loss": round(normalized_loss, 6),
                "time": round(normalized_time, 6),
                "stability": round(normalized_stability, 6),
                "quality": round(normalized_quality, 6),
            },
            "raw_score": round(raw_score, 4),
            "penalties": penalties,
            "final_score": final_score,
            "metrics_used": {
                "val_loss_total": val_loss,
                "training_time_seconds": training_time,
                "kpi_result": kpi_result,
            },
        },
    }
