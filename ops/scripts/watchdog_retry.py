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
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    last_error: Exception | None = None
    for url in _candidate_urls(api_base_url, path):
        request = urllib.request.Request(url=url, method=method, data=body, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                content = response.read().decode("utf-8")
                result = json.loads(content) if content else {}
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
    stale_after_seconds = int(os.getenv("V2_WATCHDOG_STALE_SECONDS", "120"))
    result = request_json(
        "POST",
        api_base_url,
        "/maintenance/watchdog",
        {"stale_after_seconds": stale_after_seconds},
        token=token,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
