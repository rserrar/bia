from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def request_json(method: str, url: str, payload: dict | None = None, token: str = "") -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url=url, method=method, data=body, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            content = response.read().decode("utf-8")
            return json.loads(content) if content else {}
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8")
        raise RuntimeError(f"{method} {url} failed: {error.code} {detail}") from error


def main() -> int:
    api_base_url = os.getenv("V2_API_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
    token = os.getenv("V2_API_TOKEN", "")
    stale_after_seconds = int(os.getenv("V2_WATCHDOG_STALE_SECONDS", "120"))
    result = request_json(
        "POST",
        f"{api_base_url}/maintenance/watchdog",
        {"stale_after_seconds": stale_after_seconds},
        token=token,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
