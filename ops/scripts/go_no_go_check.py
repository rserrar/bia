from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


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
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
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
    api_base_url = os.getenv("V2_API_BASE_URL", "").rstrip("/")
    token = os.getenv("V2_API_TOKEN", "")
    checkpoint_path = os.getenv("V2_CHECKPOINT_PATH", "")
    verify_legacy = os.getenv("V2_VERIFY_LEGACY_MODEL_BUILD", "").lower() in {"1", "true", "yes"}
    legacy_model_json_path = os.getenv("V2_LEGACY_MODEL_JSON_PATH", "")
    legacy_experiment_config_path = os.getenv("V2_LEGACY_EXPERIMENT_CONFIG_PATH", "")
    legacy_builder_path = os.getenv("V2_LEGACY_BUILDER_PATH", "")

    checks: list[dict] = []

    checks.append({"name": "api_base_url_configured", "ok": bool(api_base_url)})
    checks.append({"name": "checkpoint_path_configured", "ok": bool(checkpoint_path)})

    api_reachable = False
    api_error = ""
    if api_base_url:
        try:
            request_json(
                "POST",
                api_base_url,
                "/runs",
                {"code_version": "go-no-go-check", "metadata": {"source": "ops/scripts/go_no_go_check.py"}},
                token=token,
            )
            api_reachable = True
        except Exception as error:
            api_error = str(error)
    checks.append({"name": "api_reachable_with_token", "ok": api_reachable, "error": api_error or None})

    if verify_legacy:
        checks.append(
            {
                "name": "legacy_model_json_exists",
                "ok": Path(legacy_model_json_path).exists(),
                "path": legacy_model_json_path,
            }
        )
        checks.append(
            {
                "name": "legacy_experiment_config_exists",
                "ok": Path(legacy_experiment_config_path).exists(),
                "path": legacy_experiment_config_path,
            }
        )
        checks.append(
            {
                "name": "legacy_builder_exists",
                "ok": Path(legacy_builder_path).exists(),
                "path": legacy_builder_path,
            }
        )

    ok = all(bool(check.get("ok")) for check in checks)
    print(json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
