from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def request_json(method: str, url: str, payload: dict | None = None, token: str = "") -> dict:
    body = None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url=url, method=method, data=body, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            response_body = response.read().decode("utf-8")
            return json.loads(response_body) if response_body else {}
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8")
        raise RuntimeError(f"{method} {url} failed: {error.code} {detail}") from error


def main() -> int:
    api_base_url = os.getenv("V2_API_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
    token = os.getenv("V2_API_TOKEN", "")

    run = request_json(
        "POST",
        f"{api_base_url}/runs",
        {"code_version": "smoke-test", "metadata": {"source": "ops/scripts/smoke_test_api.py"}},
        token=token,
    )
    run_id = run["run_id"]

    request_json("POST", f"{api_base_url}/runs/{run_id}/heartbeat", token=token)
    request_json("POST", f"{api_base_url}/runs/{run_id}/status", {"status": "running", "generation": 1}, token=token)
    request_json(
        "POST",
        f"{api_base_url}/runs/{run_id}/events",
        {"event_type": "smoke", "label": "Event de prova", "details": {"ok": True}},
        token=token,
    )
    request_json(
        "POST",
        f"{api_base_url}/runs/{run_id}/metrics",
        {"model_id": "smoke_model", "generation": 1, "metrics": {"val_loss_total": 0.123}},
        token=token,
    )
    request_json(
        "POST",
        f"{api_base_url}/runs/{run_id}/artifacts",
        {"artifact_type": "checkpoint", "uri": "drive://smoke/checkpoint.json", "storage": "drive"},
        token=token,
    )
    summary = request_json("GET", f"{api_base_url}/runs/{run_id}/summary", token=token)
    print(json.dumps({"ok": True, "run_id": run_id, "summary": summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
