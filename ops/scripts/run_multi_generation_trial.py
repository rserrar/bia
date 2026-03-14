from __future__ import annotations

import json
import os
import sys
import time
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


def _request_json(api_base_url: str, path: str, token: str) -> tuple[dict, str]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    last_error: Exception | None = None
    for url in _candidate_urls(api_base_url, path):
        request = urllib.request.Request(url=url, method="GET", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                content = response.read().decode("utf-8")
                payload = json.loads(content) if content else {}
                return payload, url
        except urllib.error.HTTPError as error:
            if error.code == 404:
                last_error = error
                continue
            detail = error.read().decode("utf-8")
            raise RuntimeError(f"GET {url} failed: {error.code} {detail}") from error
    if isinstance(last_error, urllib.error.HTTPError):
        detail = last_error.read().decode("utf-8")
        raise RuntimeError(f"GET {path} failed with 404 on all prefixes. Last detail: {detail}") from last_error
    raise RuntimeError(f"GET {path} failed without response")


def main() -> int:
    repo = _repo_root()
    worker_src = repo / "colab-worker" / "src"
    if str(worker_src) not in sys.path:
        sys.path.insert(0, str(worker_src))
    from run_worker import main as run_worker_main

    api_base_url = os.getenv("V2_API_BASE_URL", "").rstrip("/")
    api_token = os.getenv("V2_API_TOKEN", "")
    if api_base_url == "":
        raise RuntimeError("V2_API_BASE_URL is required")

    trial_generations = int(os.getenv("V2_TRIAL_MAX_GENERATIONS", "8"))
    heartbeat_seconds = int(os.getenv("V2_TRIAL_HEARTBEAT_SECONDS", "5"))
    code_version = os.getenv("V2_TRIAL_CODE_VERSION", "trial-multi-gen")
    verify_legacy = os.getenv("V2_TRIAL_VERIFY_LEGACY", "false")
    checkpoint_dir = os.getenv("V2_TRIAL_CHECKPOINT_DIR", str(repo / "colab-worker" / "checkpoints"))
    checkpoint_path = Path(checkpoint_dir) / f"trial_state_{int(time.time())}.json"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

    os.environ["V2_MAX_GENERATIONS"] = str(trial_generations)
    os.environ["V2_HEARTBEAT_INTERVAL_SECONDS"] = str(heartbeat_seconds)
    os.environ["V2_CODE_VERSION"] = code_version
    os.environ["V2_VERIFY_LEGACY_MODEL_BUILD"] = verify_legacy
    os.environ["V2_CHECKPOINT_PATH"] = str(checkpoint_path)

    run_worker_main()

    with checkpoint_path.open("r", encoding="utf-8") as file:
        state = json.load(file)
    run_id = str(state.get("run_id", ""))
    if run_id == "":
        raise RuntimeError("run_id not found in checkpoint")

    summary, resolved_url = _request_json(api_base_url, f"/runs/{run_id}/summary", api_token)
    run_payload = summary.get("run", {})
    counts = summary.get("counts", {})
    generation = int(run_payload.get("generation", -1))
    status = str(run_payload.get("status", ""))
    metrics_count = int(counts.get("metrics", 0))
    artifacts_count = int(counts.get("artifacts", 0))

    ok = status == "completed" and generation == trial_generations and metrics_count >= trial_generations and artifacts_count >= trial_generations
    output = {
        "ok": ok,
        "run_id": run_id,
        "trial_generations": trial_generations,
        "status": status,
        "generation": generation,
        "metrics_count": metrics_count,
        "artifacts_count": artifacts_count,
        "checkpoint_path": str(checkpoint_path),
        "summary_resolved_url": resolved_url,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
