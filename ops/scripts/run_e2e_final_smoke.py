from __future__ import annotations

import json
import os
import re
import subprocess
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


def _request_json(method: str, api_base_url: str, path: str, token: str, payload: dict | None = None) -> tuple[dict, str]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    last_error: Exception | None = None
    for url in _candidate_urls(api_base_url, path):
        request = urllib.request.Request(url=url, method=method, headers=headers, data=body)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                content = response.read().decode("utf-8")
                parsed = json.loads(content) if content else {}
                if isinstance(parsed, dict):
                    parsed["_resolved_url"] = url
                return parsed, url
        except urllib.error.HTTPError as error:
            if error.code == 404:
                last_error = error
                continue
            detail = error.read().decode("utf-8")
            raise RuntimeError(f"{method} {url} failed: {error.code} {detail}") from error
    if isinstance(last_error, urllib.error.HTTPError):
        detail = last_error.read().decode("utf-8")
        raise RuntimeError(f"{method} {path} failed with 404 on all prefixes. Last detail: {detail}") from last_error
    raise RuntimeError(f"{method} {path} failed without response")


def _extract_last_json_block(text: str) -> dict:
    matches = re.findall(r"\{[\s\S]*\}", text)
    if not matches:
        raise RuntimeError("No JSON block found in output")
    return json.loads(matches[-1])


def _poll_until_trained(api_base_url: str, token: str, run_id: str, timeout_seconds: int) -> dict:
    started = time.time()
    last_seen: dict = {}
    while True:
        proposals_payload, _ = _request_json("GET", api_base_url, "/model-proposals?limit=400", token)
        proposals = [
            p for p in proposals_payload.get("model_proposals", [])
            if isinstance(p, dict) and p.get("source_run_id") == run_id
        ]
        trained = [p for p in proposals if p.get("status") == "trained"]

        summary, _ = _request_json("GET", api_base_url, f"/runs/{run_id}/summary", token)
        latest_artifact = summary.get("latest_artifact") if isinstance(summary.get("latest_artifact"), dict) else {}
        latest_event = summary.get("latest_event") if isinstance(summary.get("latest_event"), dict) else {}

        proposal_meta_ok = False
        selected_proposal: dict | None = None
        for item in trained:
            llm_metadata = item.get("llm_metadata") if isinstance(item.get("llm_metadata"), dict) else {}
            trained_uri = llm_metadata.get("trained_model_uri")
            training_kpis = llm_metadata.get("training_kpis")
            if isinstance(trained_uri, str) and trained_uri.strip() != "" and isinstance(training_kpis, dict) and len(training_kpis) > 0:
                proposal_meta_ok = True
                selected_proposal = item
                break

        artifact_ok = latest_artifact.get("artifact_type") == "trained_model"
        event_ok = latest_event.get("event_type") == "model_training_completed"
        if proposal_meta_ok and artifact_ok and event_ok:
            return {
                "trained_proposal": selected_proposal,
                "summary": summary,
                "all_run_proposals": proposals,
                "elapsed_seconds": round(time.time() - started, 2),
            }

        last_seen = {
            "proposals": len(proposals),
            "trained": len(trained),
            "latest_event_type": latest_event.get("event_type"),
            "latest_artifact_type": latest_artifact.get("artifact_type"),
        }
        if time.time() - started > timeout_seconds:
            raise TimeoutError(f"Timeout waiting trained metadata/artifact/event for run {run_id}. last_seen={last_seen}")
        time.sleep(5)


def main() -> int:
    repo = _repo_root()
    api_base_url = os.getenv("V2_API_BASE_URL", "").rstrip("/")
    api_token = os.getenv("V2_API_TOKEN", "")
    if api_base_url == "":
        raise RuntimeError("V2_API_BASE_URL is required")

    generations = int(os.getenv("V2_E2E_GENERATIONS", "1"))
    train_timeout_seconds = int(os.getenv("V2_E2E_TRAIN_TIMEOUT_SECONDS", "900"))

    trial_env = os.environ.copy()
    trial_env["V2_LLM_TRIAL_GENERATIONS"] = str(generations)

    print(f"[e2e] start LLM trial generations={generations}")
    trial = subprocess.run(
        [sys.executable, str(repo / "ops" / "scripts" / "run_llm_generation_trial.py")],
        cwd=str(repo),
        env=trial_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    print(trial.stdout)
    trial_json = _extract_last_json_block(trial.stdout)
    run_id = str(trial_json.get("run_id", "")).strip()
    if trial.returncode != 0 or not trial_json.get("ok"):
        raise RuntimeError(f"LLM trial failed: rc={trial.returncode}, result={trial_json}")
    if run_id == "":
        raise RuntimeError("run_id missing in LLM trial output")

    print(f"[e2e] run_id={run_id} -> start trainer")
    trainer_env = os.environ.copy()
    trainer = subprocess.Popen(
        [sys.executable, str(repo / "colab-worker" / "run_trainer.py")],
        cwd=str(repo),
        env=trainer_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        result = _poll_until_trained(api_base_url, api_token, run_id, timeout_seconds=train_timeout_seconds)
    finally:
        trainer.terminate()
        try:
            trainer.wait(timeout=10)
        except Exception:
            trainer.kill()

    trained_proposal = result.get("trained_proposal", {})
    summary = result.get("summary", {})
    output = {
        "ok": True,
        "run_id": run_id,
        "elapsed_seconds": result.get("elapsed_seconds"),
        "proposal_id": trained_proposal.get("proposal_id"),
        "proposal_status": trained_proposal.get("status"),
        "trained_model_uri": (trained_proposal.get("llm_metadata") or {}).get("trained_model_uri"),
        "training_kpis_keys": list(((trained_proposal.get("llm_metadata") or {}).get("training_kpis") or {}).keys()),
        "latest_event_type": (summary.get("latest_event") or {}).get("event_type"),
        "latest_artifact_type": (summary.get("latest_artifact") or {}).get("artifact_type"),
        "latest_artifact_uri": (summary.get("latest_artifact") or {}).get("uri"),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"[e2e] FAIL: {error}")
        raise
