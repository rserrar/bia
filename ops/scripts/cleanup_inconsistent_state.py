from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any


def _normalize_prefix(prefix: str) -> str:
    value = (prefix or "").strip()
    if value == "":
        return ""
    if not value.startswith("/"):
        value = "/" + value
    return value.rstrip("/")


def _candidate_urls(api_base_url: str, path: str) -> list[str]:
    configured = _normalize_prefix(os.getenv("V2_API_PATH_PREFIX", ""))
    seen: set[str] = set()
    urls: list[str] = []
    for prefix in [configured, "", "/public/index.php", "/public"]:
        normalized = _normalize_prefix(prefix)
        if normalized in seen:
            continue
        seen.add(normalized)
        urls.append(f"{api_base_url}{normalized}{path}")
    return urls


def _request_json(method: str, api_base_url: str, path: str, token: str, payload: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    last_error: Exception | None = None
    for url in _candidate_urls(api_base_url, path):
        req = urllib.request.Request(url=url, method=method, headers=headers, data=body)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                parsed = json.loads(raw) if raw else {}
                if isinstance(parsed, dict):
                    return parsed, url
                return {}, url
        except urllib.error.HTTPError as err:
            if err.code == 404:
                last_error = err
                continue
            detail = err.read().decode("utf-8")
            raise RuntimeError(f"{method} {url} failed: {err.code} {detail}") from err
    if isinstance(last_error, urllib.error.HTTPError):
        detail = last_error.read().decode("utf-8")
        raise RuntimeError(f"{method} {path} failed with 404 on all prefixes. Last detail: {detail}") from last_error
    raise RuntimeError(f"{method} {path} failed without response")


def _parse_iso_to_ts(value: str) -> float:
    if value.strip() == "":
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _age_minutes(value: str) -> float:
    ts = _parse_iso_to_ts(value)
    if ts <= 0:
        return 999999.0
    return max(0.0, (datetime.now(timezone.utc).timestamp() - ts) / 60.0)


def _run_cleanup(api_base_url: str, token: str, apply_changes: bool) -> dict[str, Any]:
    stale_run_minutes = int(os.getenv("V2_CLEANUP_STALE_RUN_MINUTES", "10"))
    stale_retry_minutes = int(os.getenv("V2_CLEANUP_STALE_RETRY_MINUTES", "20"))
    stale_training_minutes = int(os.getenv("V2_CLEANUP_STALE_TRAINING_MINUTES", "20"))
    stale_phase0_minutes = int(os.getenv("V2_CLEANUP_STALE_PHASE0_MINUTES", "10"))
    stale_accepted_minutes = int(os.getenv("V2_CLEANUP_STALE_ACCEPTED_MINUTES", "20"))

    runs_payload, _ = _request_json("GET", api_base_url, "/runs?limit=500", token)
    proposals_payload, _ = _request_json("GET", api_base_url, "/model-proposals?limit=1000", token)
    runs = [r for r in runs_payload.get("runs", []) if isinstance(r, dict)]
    proposals = [p for p in proposals_payload.get("model_proposals", []) if isinstance(p, dict)]
    runs_by_id = {str(r.get("run_id", "")): r for r in runs}

    detected: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if apply_changes:
        watchdog_result, _ = _request_json(
            "POST",
            api_base_url,
            "/maintenance/watchdog",
            token,
            {"stale_after_seconds": stale_run_minutes * 60},
        )
        applied.append({"action": "maintenance_watchdog", "result": watchdog_result})
    else:
        detected.append({"action": "maintenance_watchdog", "stale_after_minutes": stale_run_minutes})

    stale_retry_runs = []
    for run in runs:
        run_id = str(run.get("run_id", "")).strip()
        status = str(run.get("status", "")).strip()
        if run_id == "" or status != "retrying":
            continue
        age = _age_minutes(str(run.get("updated_at", "")))
        if age > stale_retry_minutes:
            stale_retry_runs.append({"run_id": run_id, "status": status, "age_minutes": round(age, 2)})

    for item in stale_retry_runs:
        detected.append({"action": "mark_run_failed", **item})
        if apply_changes:
            _request_json("POST", api_base_url, f"/runs/{item['run_id']}/status", token, {"status": "failed"})
            _request_json(
                "POST",
                api_base_url,
                f"/runs/{item['run_id']}/events",
                token,
                {
                    "event_type": "cleanup_run_marked_failed",
                    "label": f"Run {item['run_id']} marcat com failed per stale retrying",
                    "details": {"age_minutes": item["age_minutes"], "cleanup_at": _now_iso()},
                },
            )
            applied.append({"action": "mark_run_failed", **item})

    stale_training = []
    stale_phase0 = []
    stale_accepted = []
    stale_validated = []
    for proposal in proposals:
        proposal_id = str(proposal.get("proposal_id", "")).strip()
        status = str(proposal.get("status", "")).strip()
        run_id = str(proposal.get("source_run_id", "")).strip()
        age = _age_minutes(str(proposal.get("updated_at", "")))
        run_status = str((runs_by_id.get(run_id) or {}).get("status", "")).strip()
        if status == "training" and age > stale_training_minutes:
            stale_training.append({"proposal_id": proposal_id, "run_id": run_id, "age_minutes": round(age, 2)})
        elif status == "queued_phase0" and age > stale_phase0_minutes and run_status in {"completed", "failed", "cancelled"}:
            stale_phase0.append({"proposal_id": proposal_id, "run_id": run_id, "age_minutes": round(age, 2)})
        elif status == "accepted" and age > stale_accepted_minutes:
            stale_accepted.append({"proposal_id": proposal_id, "run_id": run_id, "age_minutes": round(age, 2)})
        elif status == "validated_phase0" and age > stale_accepted_minutes:
            stale_validated.append({"proposal_id": proposal_id, "run_id": run_id, "age_minutes": round(age, 2)})

    for item in stale_training:
        detected.append({"action": "requeue_training_proposal", **item})
        if apply_changes:
            _request_json(
                "POST",
                api_base_url,
                f"/model-proposals/{item['proposal_id']}/status",
                token,
                {
                    "status": "accepted",
                    "metadata_updates": {
                        "cleanup_reason": "stale_training_requeued",
                        "cleanup_at": _now_iso(),
                        "cleanup_previous_status": "training",
                        "training_interrupted_at": _now_iso(),
                    },
                },
            )
            if item["run_id"]:
                _request_json(
                    "POST",
                    api_base_url,
                    f"/runs/{item['run_id']}/events",
                    token,
                    {
                        "event_type": "cleanup_proposal_requeued",
                        "label": f"Proposta {item['proposal_id']} reencuada per stale training",
                        "details": {"age_minutes": item["age_minutes"], "cleanup_at": _now_iso()},
                    },
                )
                _request_json(
                    "POST",
                    api_base_url,
                    f"/runs/{item['run_id']}/events",
                    token,
                    {
                        "event_type": "training_interrupted",
                        "label": f"Entrenament interromput per stale training a {item['proposal_id']}",
                        "details": {"proposal_id": item["proposal_id"], "age_minutes": item["age_minutes"], "cleanup_at": _now_iso()},
                    },
                )
            applied.append({"action": "requeue_training_proposal", **item})

    if len(stale_phase0) > 0:
        detected.append({"action": "reprocess_phase0_queue", "count": len(stale_phase0), "samples": stale_phase0[:10]})
        if apply_changes:
            result, _ = _request_json(
                "POST",
                api_base_url,
                "/maintenance/process-model-proposals-phase0",
                token,
                {"limit": max(20, len(stale_phase0))},
            )
            applied.append({"action": "reprocess_phase0_queue", "result": result})

    for item in stale_accepted:
        warnings.append({"type": "stale_accepted", **item, "policy": "auditable_only"})
    for item in stale_validated:
        warnings.append({"type": "stale_validated_phase0", **item, "policy": "auditable_only"})

    return {
        "ok": True,
        "mode": "apply" if apply_changes else "dry-run",
        "timestamp": _now_iso(),
        "thresholds": {
            "stale_run_minutes": stale_run_minutes,
            "stale_retry_minutes": stale_retry_minutes,
            "stale_training_minutes": stale_training_minutes,
            "stale_phase0_minutes": stale_phase0_minutes,
            "stale_accepted_minutes": stale_accepted_minutes,
        },
        "summary": {
            "runs_total": len(runs),
            "proposals_total": len(proposals),
            "stale_retry_runs": len(stale_retry_runs),
            "stale_training_proposals": len(stale_training),
            "stale_phase0_proposals": len(stale_phase0),
            "stale_accepted_proposals": len(stale_accepted),
            "stale_validated_phase0_proposals": len(stale_validated),
        },
        "detected": detected,
        "warnings": warnings,
        "applied": applied,
    }


def main() -> int:
    api_base_url = os.getenv("V2_API_BASE_URL", "").rstrip("/")
    token = os.getenv("V2_API_TOKEN", "")
    mode = os.getenv("V2_CLEANUP_MODE", "dry-run").strip().lower()

    if mode not in {"dry-run", "apply"}:
        raise RuntimeError("V2_CLEANUP_MODE must be dry-run or apply")
    if api_base_url == "":
        raise RuntimeError("V2_API_BASE_URL is required")

    result = _run_cleanup(api_base_url, token, apply_changes=(mode == "apply"))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
