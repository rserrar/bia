from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any


def _api_key() -> str:
    value = os.getenv("OPENAI_API_KEY", "").strip()
    if value != "":
        return value
    return os.getenv("V2_LLM_API_KEY", "").strip()


def _looks_placeholder(api_key: str) -> bool:
    upper = api_key.upper()
    markers = ["<", ">", "NOVA_CLAU", "LA_TEVA", "YOUR_", "*****", "XXXX"]
    return any(marker in upper for marker in markers)


def _request(method: str, path: str, api_key: str, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, str], Any]:
    url = f"https://api.openai.com{path}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url=url,
        method=method,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read().decode("utf-8")
            parsed = json.loads(raw) if raw.strip() else {}
            return response.status, dict(response.headers), parsed
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8")
        parsed: Any = {}
        if raw.strip():
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = {"raw": raw}
        return error.code, dict(error.headers), parsed


def _limit_headers(headers: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    keys = [
        "x-ratelimit-limit-requests",
        "x-ratelimit-remaining-requests",
        "x-ratelimit-reset-requests",
        "x-ratelimit-limit-tokens",
        "x-ratelimit-remaining-tokens",
        "x-ratelimit-reset-tokens",
        "retry-after",
    ]
    normalized = {k.lower(): v for k, v in headers.items()}
    for key in keys:
        if key in normalized:
            out[key] = normalized[key]
    return out


def _probe_model(api_key: str, model: str) -> dict[str, Any]:
    chat_payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Return short JSON only."},
            {"role": "user", "content": "{\"ping\": true}"},
        ],
        "max_tokens": 24,
        "temperature": 0.0,
    }
    started = time.time()
    status, headers, body = _request("POST", "/v1/chat/completions", api_key, chat_payload)
    endpoint_used = "/v1/chat/completions"
    error = body.get("error", {}) if isinstance(body, dict) else {}
    message = str(error.get("message", "") or "")
    not_chat_model = "not a chat model" in message.lower()
    unsupported_max_tokens = str(error.get("code", "") or "") == "unsupported_parameter" and "max_tokens" in message
    if unsupported_max_tokens:
        chat_payload_alt = {
            "model": model,
            "messages": [
                {"role": "system", "content": "Return short JSON only."},
                {"role": "user", "content": "{\"ping\": true}"},
            ],
            "max_completion_tokens": 24,
            "temperature": 0.0,
        }
        status, headers, body = _request("POST", "/v1/chat/completions", api_key, chat_payload_alt)
    if not_chat_model:
        completion_payload = {
            "model": model,
            "prompt": "Return short JSON only.\n\n{\"ping\": true}",
            "max_tokens": 24,
            "temperature": 0.0,
        }
        status, headers, body = _request("POST", "/v1/completions", api_key, completion_payload)
        endpoint_used = "/v1/completions"
    elapsed_ms = int((time.time() - started) * 1000)
    error = body.get("error", {}) if isinstance(body, dict) else {}
    return {
        "model": model,
        "endpoint_used": endpoint_used,
        "status_code": status,
        "ok": 200 <= status < 300,
        "latency_ms": elapsed_ms,
        "error_type": error.get("type"),
        "error_code": error.get("code"),
        "error_message": error.get("message"),
        "rate_limit_headers": _limit_headers(headers),
    }


def main() -> int:
    api_key = _api_key()
    if api_key == "":
        raise RuntimeError("OPENAI_API_KEY o V2_LLM_API_KEY és obligatori")
    if _looks_placeholder(api_key):
        raise RuntimeError(
            "La clau API sembla un placeholder. "
            "Posa la clau real a OPENAI_API_KEY (sense '<...>' ni text tipus LA_TEVA_CLAU)."
        )

    models_status, models_headers, models_body = _request("GET", "/v1/models", api_key)
    model_ids: list[str] = []
    if models_status == 200 and isinstance(models_body, dict):
        data = models_body.get("data", [])
        if isinstance(data, list):
            model_ids = sorted([str(item.get("id", "")) for item in data if isinstance(item, dict) and item.get("id")])

    probe_models_env = os.getenv("V2_OPENAI_PROBE_MODELS", "").strip()
    if probe_models_env != "":
        candidates = [item.strip() for item in probe_models_env.split(",") if item.strip() != ""]
    else:
        candidates = ["gpt-5.3-codex", "gpt-4o-mini", "gpt-4.1-mini"]

    probe_results = [_probe_model(api_key, model) for model in candidates]
    successful = [item for item in probe_results if item.get("ok")]
    output = {
        "ok": len(successful) > 0,
        "models_list_status": models_status,
        "models_list_count": len(model_ids),
        "models_list_rate_limit_headers": _limit_headers(models_headers),
        "models_sample": model_ids[:40],
        "probe_results": probe_results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
