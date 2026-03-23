from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


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


def _request_json(api_base_url: str, path: str, token: str) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    last_error: Exception | None = None
    for url in _candidate_urls(api_base_url, path):
        req = urllib.request.Request(url=url, method="GET", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = resp.read().decode("utf-8")
                payload = json.loads(body) if body else {}
                return payload if isinstance(payload, dict) else {}
        except urllib.error.HTTPError as err:
            if err.code == 404:
                last_error = err
                continue
            detail = err.read().decode("utf-8")
            raise RuntimeError(f"GET {url} failed: {err.code} {detail}") from err
    if isinstance(last_error, urllib.error.HTTPError):
        detail = last_error.read().decode("utf-8")
        raise RuntimeError(f"GET {path} failed with 404 on all prefixes: {detail}") from last_error
    raise RuntimeError(f"GET {path} failed without response")


def main() -> int:
    api_base_url = os.getenv("V2_API_BASE_URL", "").rstrip("/")
    token = os.getenv("V2_API_TOKEN", "")
    limit = int(os.getenv("V2_SELECTION_PREVIEW_LIMIT", "200"))

    if api_base_url == "":
        raise RuntimeError("V2_API_BASE_URL is required")

    repo = _repo_root()
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    from shared.utils.selection_policy import default_policy_config, evaluate_reference_candidate

    payload = _request_json(api_base_url, f"/model-proposals?limit={max(1, limit)}", token)
    proposals = [p for p in payload.get("model_proposals", []) if isinstance(p, dict)]
    policy = default_policy_config()

    evaluated = [evaluate_reference_candidate(p, config=policy) for p in proposals]
    eligible = [e for e in evaluated if bool(e.get("eligible"))]
    rejected = [e for e in evaluated if not bool(e.get("eligible"))]
    eligible.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)

    output = {
        "policy_version": policy.get("policy_version"),
        "candidates": len(evaluated),
        "eligible": len(eligible),
        "rejected": len(rejected),
        "top_selected_preview": eligible[:10],
        "top_rejected_preview": rejected[:10],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
