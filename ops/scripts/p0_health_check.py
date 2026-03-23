from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone


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


def _request_json(method: str, api_base_url: str, path: str, token: str) -> tuple[dict, str]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    last_error: Exception | None = None
    for url in _candidate_urls(api_base_url, path):
        req = urllib.request.Request(url=url, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                payload_raw = resp.read().decode("utf-8")
                payload = json.loads(payload_raw) if payload_raw else {}
                return payload if isinstance(payload, dict) else {}, url
        except urllib.error.HTTPError as err:
            if err.code == 404:
                last_error = err
                continue
            detail = err.read().decode("utf-8")
            raise RuntimeError(f"{method} {url} failed: {err.code} {detail}") from err
    if isinstance(last_error, urllib.error.HTTPError):
        detail = last_error.read().decode("utf-8")
        raise RuntimeError(f"{method} {path} failed with 404 on all prefixes: {detail}") from last_error
    raise RuntimeError(f"{method} {path} failed without response")


def _parse_iso(ts: str) -> float:
    if not ts:
        return 0.0
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def run_check() -> dict:
    api_base_url = os.getenv("V2_API_BASE_URL", "").rstrip("/")
    token = os.getenv("V2_API_TOKEN", "")
    stale_minutes = int(os.getenv("V2_P0_STALE_PROPOSAL_MINUTES", "30"))
    now_ts = time.time()

    checks: list[dict] = []
    if api_base_url == "":
        result = {
            "ok": False,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "checks": [{"name": "api_base_url_configured", "ok": False}],
            "error": "V2_API_BASE_URL is required",
        }
        return result

    runs_payload, resolved_runs_url = _request_json("GET", api_base_url, "/runs?limit=5", token)
    proposals_payload, resolved_proposals_url = _request_json("GET", api_base_url, "/model-proposals?limit=400", token)

    runs = [r for r in runs_payload.get("runs", []) if isinstance(r, dict)]
    proposals = [p for p in proposals_payload.get("model_proposals", []) if isinstance(p, dict)]

    checks.append({"name": "api_reachable", "ok": True, "resolved_runs_url": resolved_runs_url})
    checks.append({"name": "model_proposals_reachable", "ok": True, "resolved_model_proposals_url": resolved_proposals_url})

    pending = [p for p in proposals if str(p.get("status", "")).strip() in {"accepted", "validated_phase0"}]
    stale_pending = []
    for item in pending:
        updated_at = str(item.get("updated_at", ""))
        age_minutes = (now_ts - _parse_iso(updated_at)) / 60.0
        if age_minutes > stale_minutes:
            stale_pending.append(
                {
                    "proposal_id": item.get("proposal_id"),
                    "status": item.get("status"),
                    "age_minutes": round(age_minutes, 2),
                }
            )

    checks.append(
        {
            "name": "stale_pending_proposals",
            "ok": len(stale_pending) == 0,
            "stale_count": len(stale_pending),
            "stale_threshold_minutes": stale_minutes,
            "samples": stale_pending[:5],
        }
    )

    trained_count = len([p for p in proposals if str(p.get("status", "")).strip() == "trained"])
    checks.append({"name": "trained_models_seen", "ok": trained_count >= 0, "count": trained_count})

    return {
        "ok": all(bool(c.get("ok")) for c in checks),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "runs_count": len(runs),
        "proposals_count": len(proposals),
        "checks": checks,
    }


def main() -> int:
    try:
        result = run_check()
    except Exception as error:
        result = {
            "ok": False,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(error),
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
