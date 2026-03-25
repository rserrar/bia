from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


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


def _request_json(method: str, api_base_url: str, path: str, token: str) -> tuple[dict[str, Any], str]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    last_error: Exception | None = None
    for url in _candidate_urls(api_base_url, path):
        req = urllib.request.Request(url=url, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                parsed = json.loads(raw) if raw else {}
                return parsed if isinstance(parsed, dict) else {}, url
        except urllib.error.HTTPError as err:
            if err.code == 404:
                last_error = err
                continue
            detail = err.read().decode("utf-8")
            raise RuntimeError(f"{method} {url} failed: {err.code} {detail}") from err
    if isinstance(last_error, urllib.error.HTTPError):
        detail = last_error.read().decode("utf-8")
        raise RuntimeError(f"{method} {path} failed with 404 on all prefixes. Last detail: {detail}") from last_error
    raise RuntimeError(f"{method} {path} failed without response")


def _download_bytes(api_base_url: str, path: str, token: str) -> tuple[bytes, str]:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    last_error: Exception | None = None
    for url in _candidate_urls(api_base_url, path):
        req = urllib.request.Request(url=url, method="GET", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read(), url
        except urllib.error.HTTPError as err:
            if err.code == 404:
                last_error = err
                continue
            detail = err.read().decode("utf-8")
            raise RuntimeError(f"GET {url} failed: {err.code} {detail}") from err
    if isinstance(last_error, urllib.error.HTTPError):
        detail = last_error.read().decode("utf-8")
        raise RuntimeError(f"GET {path} failed with 404 on all prefixes. Last detail: {detail}") from last_error
    raise RuntimeError(f"GET {path} failed without response")


def main() -> int:
    api_base_url = os.getenv("V2_API_BASE_URL", "").rstrip("/")
    token = os.getenv("V2_API_TOKEN", "")
    proposal_id = os.getenv("V2_VERIFY_PROPOSAL_ID", "").strip()
    run_id = os.getenv("V2_VERIFY_RUN_ID", "").strip()
    output_dir = Path(os.getenv("V2_VERIFY_ARTIFACT_OUTPUT_DIR", "ops/reports/downloaded_artifacts"))

    if api_base_url == "":
        raise RuntimeError("V2_API_BASE_URL is required")

    if proposal_id == "":
        if run_id == "":
            runs_payload, _ = _request_json("GET", api_base_url, "/runs?limit=1", token)
            runs = [r for r in runs_payload.get("runs", []) if isinstance(r, dict)]
            if len(runs) == 0:
                raise RuntimeError("No runs available")
            run_id = str(runs[0].get("run_id", "")).strip()
        champion_payload, _ = _request_json("GET", api_base_url, f"/champion/run/{run_id}?top_n=1", token)
        champion = champion_payload.get("champion") if isinstance(champion_payload.get("champion"), dict) else {}
        proposal = champion.get("proposal") if isinstance(champion.get("proposal"), dict) else {}
        proposal_id = str(proposal.get("proposal_id", "")).strip()
        if proposal_id == "":
            raise RuntimeError("Could not resolve proposal_id from run champion")

    artifacts_payload, _ = _request_json("GET", api_base_url, f"/models/{proposal_id}/artifacts", token)
    artifacts = [a for a in artifacts_payload.get("artifacts", []) if isinstance(a, dict)]
    downloadable = [a for a in artifacts if str(a.get("download_url", "")).strip() != ""]
    if len(downloadable) == 0:
        raise RuntimeError(f"No downloadable artifacts found for {proposal_id}")

    output_dir.mkdir(parents=True, exist_ok=True)
    downloads = []
    for artifact in downloadable:
        artifact_id = str(artifact.get("artifact_id", "")).strip()
        download_path = str(artifact.get("download_url", "")).strip()
        content, resolved_url = _download_bytes(api_base_url, download_path, token)
        target = output_dir / f"{proposal_id}_{artifact_id or 'artifact'}.bin"
        target.write_bytes(content)
        downloads.append(
            {
                "artifact_id": artifact_id,
                "artifact_type": artifact.get("artifact_type"),
                "availability_status": artifact.get("availability_status"),
                "resolved_url": resolved_url,
                "saved_to": str(target),
                "size_bytes": len(content),
            }
        )

    payload = {
        "ok": True,
        "proposal_id": proposal_id,
        "run_id": run_id,
        "artifacts_total": len(artifacts),
        "downloaded": downloads,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
