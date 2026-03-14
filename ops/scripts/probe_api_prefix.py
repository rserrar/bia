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


def main() -> int:
    api_base_url = os.getenv("V2_API_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
    token = os.getenv("V2_API_TOKEN", "")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    attempts: list[dict] = []
    for url in _candidate_urls(api_base_url, "/runs?limit=1"):
        request = urllib.request.Request(url=url, method="GET", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                content = response.read().decode("utf-8")
                payload = json.loads(content) if content else {}
                print(
                    json.dumps(
                        {
                            "ok": True,
                            "resolved_url": url,
                            "status": response.status,
                            "attempts": attempts,
                            "response_keys": sorted(payload.keys()) if isinstance(payload, dict) else [],
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0
        except urllib.error.HTTPError as error:
            attempts.append({"url": url, "status": error.code})
            continue
        except Exception as error:
            attempts.append({"url": url, "error": str(error)})
            continue

    print(json.dumps({"ok": False, "attempts": attempts}, ensure_ascii=False, indent=2))
    return 1


if __name__ == "__main__":
    sys.exit(main())
