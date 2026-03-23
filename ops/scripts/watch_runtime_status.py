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
        request = urllib.request.Request(url=url, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload_raw = response.read().decode("utf-8")
                payload = json.loads(payload_raw) if payload_raw else {}
                return payload if isinstance(payload, dict) else {}, url
        except urllib.error.HTTPError as error:
            if error.code == 404:
                last_error = error
                continue
            detail = error.read().decode("utf-8")
            raise RuntimeError(f"{method} {url} failed: {error.code} {detail}") from error
    if isinstance(last_error, urllib.error.HTTPError):
        detail = last_error.read().decode("utf-8")
        raise RuntimeError(f"{method} {path} failed with 404 on all prefixes: {detail}") from last_error
    raise RuntimeError(f"{method} {path} failed without response")


def _latest_run_id(api_base_url: str, token: str) -> str:
    payload, _ = _request_json("GET", api_base_url, "/runs?limit=1", token)
    runs = [r for r in payload.get("runs", []) if isinstance(r, dict)]
    if len(runs) == 0:
        return ""
    return str(runs[0].get("run_id", "")).strip()


def main() -> int:
    api_base_url = os.getenv("V2_API_BASE_URL", "").rstrip("/")
    token = os.getenv("V2_API_TOKEN", "")
    watch_run_id = os.getenv("V2_WATCH_RUN_ID", "").strip()
    interval = max(2, int(os.getenv("V2_WATCH_INTERVAL_SECONDS", "5")))

    if api_base_url == "":
        raise RuntimeError("V2_API_BASE_URL is required")

    if watch_run_id == "":
        watch_run_id = _latest_run_id(api_base_url, token)

    print(json.dumps({"watch_started_at": datetime.now(timezone.utc).isoformat(), "run_id": watch_run_id, "interval_seconds": interval}, ensure_ascii=False))

    while True:
        if watch_run_id == "":
            watch_run_id = _latest_run_id(api_base_url, token)
            if watch_run_id == "":
                print(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "status": "idle", "detail": "no_runs"}, ensure_ascii=False))
                time.sleep(interval)
                continue

        run_payload, _ = _request_json("GET", api_base_url, f"/runs/{watch_run_id}", token)
        summary_payload, _ = _request_json("GET", api_base_url, f"/runs/{watch_run_id}/summary", token)
        proposals_payload, _ = _request_json("GET", api_base_url, "/model-proposals?limit=400", token)

        run_proposals = [
            p for p in proposals_payload.get("model_proposals", [])
            if isinstance(p, dict) and str(p.get("source_run_id", "")) == watch_run_id
        ]
        by_status: dict[str, int] = {}
        for proposal in run_proposals:
            status = str(proposal.get("status", "unknown"))
            by_status[status] = by_status.get(status, 0) + 1

        latest_event = summary_payload.get("latest_event") if isinstance(summary_payload.get("latest_event"), dict) else {}
        latest_artifact = summary_payload.get("latest_artifact") if isinstance(summary_payload.get("latest_artifact"), dict) else {}

        line = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "run_id": watch_run_id,
            "run_status": run_payload.get("status"),
            "generation": run_payload.get("generation"),
            "proposals_total": len(run_proposals),
            "proposals_by_status": by_status,
            "latest_event": latest_event.get("event_type"),
            "latest_event_label": latest_event.get("label"),
            "latest_artifact": latest_artifact.get("artifact_type"),
        }
        print(json.dumps(line, ensure_ascii=False))
        time.sleep(interval)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print(json.dumps({"watch_stopped": True, "ts": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False))
