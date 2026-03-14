from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


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


def request_json(method: str, api_base_url: str, path: str, payload: dict | None = None, token: str = "") -> dict:
    body = None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    last_error: Exception | None = None
    for url in _candidate_urls(api_base_url, path):
        request = urllib.request.Request(url=url, method=method, data=body, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                response_body = response.read().decode("utf-8")
                result = json.loads(response_body) if response_body else {}
                if isinstance(result, dict):
                    result["_resolved_url"] = url
                return result
        except urllib.error.HTTPError as error:
            if error.code == 404:
                last_error = error
                continue
            detail = error.read().decode("utf-8")
            raise RuntimeError(f"{method} {url} failed: {error.code} {detail}") from error
    if isinstance(last_error, urllib.error.HTTPError):
        detail = last_error.read().decode("utf-8")
        raise RuntimeError(
            f"{method} {path} failed with 404 on all prefixes. "
            f"Configura V2_API_PATH_PREFIX. Last detail: {detail}"
        ) from last_error
    raise RuntimeError(f"{method} {path} failed without response")


def main() -> int:
    api_base_url = os.getenv("V2_API_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
    token = os.getenv("V2_API_TOKEN", "")

    run = request_json(
        "POST",
        api_base_url,
        "/runs",
        {"code_version": "smoke-test", "metadata": {"source": "ops/scripts/smoke_test_api.py"}},
        token=token,
    )
    run_id = run["run_id"]

    request_json("POST", api_base_url, f"/runs/{run_id}/heartbeat", token=token)
    request_json("POST", api_base_url, f"/runs/{run_id}/status", {"status": "running", "generation": 1}, token=token)
    request_json(
        "POST",
        api_base_url,
        f"/runs/{run_id}/events",
        {"event_type": "smoke", "label": "Event de prova", "details": {"ok": True}},
        token=token,
    )
    request_json(
        "POST",
        api_base_url,
        f"/runs/{run_id}/metrics",
        {"model_id": "smoke_model", "generation": 1, "metrics": {"val_loss_total": 0.123}},
        token=token,
    )
    request_json(
        "POST",
        api_base_url,
        f"/runs/{run_id}/artifacts",
        {"artifact_type": "checkpoint", "uri": "drive://smoke/checkpoint.json", "storage": "drive"},
        token=token,
    )
    proposal = request_json(
        "POST",
        api_base_url,
        "/model-proposals",
        {
            "source_run_id": run_id,
            "base_model_id": "smoke_model",
            "proposal": {"layers_delta": {"dense_units": 64}},
            "llm_metadata": {"provider": "smoke", "model": "none"},
        },
        token=token,
    )
    proposal_id = proposal["proposal_id"]
    request_json("POST", api_base_url, f"/model-proposals/{proposal_id}/enqueue-phase0", token=token)
    processing = request_json(
        "POST",
        api_base_url,
        "/maintenance/process-model-proposals-phase0",
        {"limit": 10},
        token=token,
    )
    proposals = request_json("GET", api_base_url, "/model-proposals?limit=10", token=token)
    proposal_detail = request_json("GET", api_base_url, f"/model-proposals/{proposal_id}", token=token)
    if proposal_detail.get("status") != "validated_phase0":
        raise RuntimeError(f"proposal not auto-validated: {proposal_detail}")
    summary = request_json("GET", api_base_url, f"/runs/{run_id}/summary", token=token)
    print(
        json.dumps(
            {
                "ok": True,
                "run_id": run_id,
                "summary": summary,
                "proposal_id": proposal_id,
                "proposal_detail": proposal_detail,
                "proposals_count": len(proposals.get("model_proposals", [])),
                "processing": processing,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
