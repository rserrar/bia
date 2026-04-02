from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable


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
    decoder = json.JSONDecoder()
    last_payload: dict[str, Any] | None = None
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            parsed, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if text[index + end :].strip() != "":
            continue
        if isinstance(parsed, dict):
            last_payload = parsed
    if last_payload is None:
        raise RuntimeError("No JSON block found in output")
    return last_payload


def _emit_progress(payload: dict[str, Any]) -> None:
    print(json.dumps({"progress_event": True, **payload}, ensure_ascii=False), flush=True)


def _run_and_stream(command: list[str], cwd: Path, env: dict[str, str]) -> tuple[int, str]:
    proc = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    lines: list[str] = []
    for line in proc.stdout:
        lines.append(line)
        print(line, end="")
    return proc.wait(), "".join(lines)


def _stream_process_output(proc: subprocess.Popen[str], prefix: str) -> None:
    assert proc.stdout is not None
    for line in proc.stdout:
        print(f"{prefix}{line}", end="")


def _poll_until_trained(
    api_base_url: str,
    token: str,
    run_id: str,
    timeout_seconds: int,
    expected_models_total: int | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict:
    started = time.time()
    generations_total = max(1, int(os.getenv("V2_E2E_GENERATIONS", "1")))
    models_per_generation = max(1, int(os.getenv("V2_LLM_NUM_NEW_MODELS", os.getenv("V2_MODELS_PER_GENERATION", "1"))))
    expected_models_total = expected_models_total or (generations_total * models_per_generation)
    last_seen: dict = {}
    while True:
        run_payload, _ = _request_json("GET", api_base_url, f"/runs/{run_id}", token)
        timeline_payload, _ = _request_json("GET", api_base_url, f"/runs/{run_id}/timeline?limit=25", token)
        references_payload, _ = _request_json("GET", api_base_url, f"/runs/{run_id}/references?limit=5", token)
        proposals_payload, _ = _request_json("GET", api_base_url, "/model-proposals?limit=400", token)
        proposals = [
            p for p in proposals_payload.get("model_proposals", [])
            if isinstance(p, dict) and p.get("source_run_id") == run_id
        ]
        trained = [p for p in proposals if p.get("status") == "trained"]
        rejected = [p for p in proposals if p.get("status") == "rejected"]
        terminal = [p for p in proposals if p.get("status") in {"trained", "rejected"}]
        active = [
            p for p in proposals
            if p.get("status") in {"draft", "queued_phase0", "validated_phase0", "accepted", "training"}
        ]

        summary, _ = _request_json("GET", api_base_url, f"/runs/{run_id}/summary", token)
        latest_artifact_raw = summary.get("latest_artifact")
        latest_artifact: dict[str, Any] = dict(latest_artifact_raw) if isinstance(latest_artifact_raw, dict) else {}
        latest_event_raw = summary.get("latest_event")
        latest_event: dict[str, Any] = dict(latest_event_raw) if isinstance(latest_event_raw, dict) else {}

        proposal_meta_ok = False
        selected_proposal: dict | None = None
        for item in trained:
            llm_metadata_raw = item.get("llm_metadata")
            llm_metadata: dict[str, Any] = dict(llm_metadata_raw) if isinstance(llm_metadata_raw, dict) else {}
            trained_uri = llm_metadata.get("trained_model_uri")
            training_kpis = llm_metadata.get("training_kpis")
            if isinstance(trained_uri, str) and trained_uri.strip() != "" and isinstance(training_kpis, dict) and len(training_kpis) > 0:
                proposal_meta_ok = True
                selected_proposal = item
                break

        artifact_type = str(latest_artifact.get("artifact_type", ""))
        event_type = str(latest_event.get("event_type", ""))
        artifact_ok = artifact_type in {"trained_model", "champion_model"}
        run_completed_ok = str(run_payload.get("status", "")) == "completed"
        terminal_event_types = {"model_training_completed", "champion_selected", "champion_kept", "champion_selection_skipped"}
        timeline_items = timeline_payload.get("timeline", []) if isinstance(timeline_payload, dict) else []
        terminal_event_seen = any(
            isinstance(item, dict) and str(item.get("type", "")) in terminal_event_types
            for item in timeline_items
        )
        event_ok = event_type in terminal_event_types or terminal_event_seen

        progress_payload = {
            "stage": "training_in_progress",
            "stage_label": "Entrenant models i esperant artifact final",
            "run_id": run_id,
            "current_run_id": run_id,
            "run_ids": [run_id],
            "run_status": run_payload.get("status"),
            "generations_total": generations_total,
            "generations_completed": int(run_payload.get("generation", 0) or 0),
            "models_generated": len(proposals),
            "models_trained": len(trained),
            "models_rejected": len(rejected),
            "models_expected_total": expected_models_total,
            "latest_event_type": latest_event.get("event_type"),
            "latest_event_label": latest_event.get("label"),
            "latest_artifact_type": latest_artifact.get("artifact_type"),
            "terminal_event_seen": terminal_event_seen,
            "reference_context": {
                "reference_models_count": int(references_payload.get("reference_models_count", 0) or 0),
                "fallback_used": bool(references_payload.get("fallback_used", False)),
                "references": references_payload.get("references", []),
            },
            "elapsed_seconds": round(time.time() - started, 2),
        }
        if on_progress is not None:
            on_progress(progress_payload)

        all_expected_generated = len(proposals) >= expected_models_total
        all_models_terminal = len(terminal) >= expected_models_total and len(active) == 0
        success_ready = proposal_meta_ok and all_expected_generated and all_models_terminal and ((artifact_ok and event_ok) or run_completed_ok)
        if success_ready:
            return {
                "trained_proposal": selected_proposal or (trained[0] if trained else {}),
                "summary": summary,
                "run": run_payload,
                "references": references_payload,
                "all_run_proposals": proposals,
                "elapsed_seconds": round(time.time() - started, 2),
            }

        last_seen = {
            "proposals": len(proposals),
            "trained": len(trained),
            "rejected": len(rejected),
            "expected_models_total": expected_models_total,
            "active": len(active),
            "latest_event_type": latest_event.get("event_type"),
            "latest_artifact_type": latest_artifact.get("artifact_type"),
            "terminal_event_seen": terminal_event_seen,
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
    models_per_generation = int(os.getenv("V2_LLM_NUM_NEW_MODELS", os.getenv("V2_MODELS_PER_GENERATION", "1")))

    print(f"[e2e] start runtime trial generations={generations}")
    _emit_progress({
        "stage": "starting_trial",
        "stage_label": "Inicialitzant runtime amb controller, trainer i watchdog",
        "generations_total": generations,
        "generations_completed": 0,
        "models_generated": 0,
        "models_trained": 0,
        "models_per_generation": models_per_generation,
    })
    trial_rc, trial_stdout = _run_and_stream(
        [sys.executable, str(repo / "ops" / "scripts" / "run_llm_generation_trial.py")],
        cwd=repo,
        env=trial_env,
    )
    trial_json = _extract_last_json_block(trial_stdout)
    run_id = str(trial_json.get("run_id", "")).strip()
    if run_id == "":
        if bool(trial_json.get("stop_worker_loop")):
            _emit_progress({
                "stage": "llm_rate_limited",
                "stage_label": "Rate limit de l'LLM; aturant worker de Colab",
                "stop_worker_loop": True,
                "fatal_error": "llm_rate_limited",
                "error": trial_json.get("error", "llm_rate_limited"),
            })
        raise RuntimeError("run_id missing in LLM trial output")
    trial_expected_models = int(trial_json.get("expected_models_total", generations * models_per_generation) or (generations * models_per_generation))
    trial_created_models = int(trial_json.get("proposals_created", 0) or 0)
    partial_generation = (trial_rc != 0 or not trial_json.get("ok")) and trial_created_models > 0
    effective_expected_models = trial_created_models if partial_generation else trial_expected_models
    if (trial_rc != 0 or not trial_json.get("ok")) and not partial_generation:
        raise RuntimeError(f"LLM trial failed: rc={trial_rc}, result={trial_json}")

    _emit_progress({
        "stage": "generation_phase_completed",
        "stage_label": "Generacions completades; esperant tancament de training en paral·lel" if not partial_generation else "Generació parcial; continuant amb els models disponibles",
        "run_id": run_id,
        "current_run_id": run_id,
        "run_ids": [run_id],
        "generations_total": generations,
        "generations_completed": int(trial_json.get("generations", generations) or generations),
        "models_generated": trial_created_models,
        "models_trained": 0,
        "latest_event_type": trial_json.get("latest_event_type"),
        "latest_event_label": trial_json.get("latest_event_label"),
        "partial_generation": partial_generation,
        "effective_expected_models_total": effective_expected_models,
        "llm_error_events": int(trial_json.get("llm_error_events", 0) or 0),
    })

    result = _poll_until_trained(
        api_base_url,
        api_token,
        run_id,
        timeout_seconds=train_timeout_seconds,
        expected_models_total=effective_expected_models,
        on_progress=_emit_progress,
    )

    trained_proposal = result.get("trained_proposal", {})
    summary = result.get("summary", {})
    run_payload = result.get("run", {}) if isinstance(result.get("run"), dict) else {}
    references_payload = result.get("references", {}) if isinstance(result.get("references"), dict) else {}
    output = {
        "ok": True,
        "run_id": run_id,
        "run_ids": [run_id],
        "current_run_id": run_id,
        "stage": "completed",
        "stage_label": "Execució completada correctament",
        "generations_total": generations,
        "generations_completed": int(run_payload.get("generation", generations) or generations),
        "models_generated": len(result.get("all_run_proposals", []) or []),
        "models_trained": len([
            proposal for proposal in (result.get("all_run_proposals", []) or [])
            if isinstance(proposal, dict) and proposal.get("status") == "trained"
        ]),
        "elapsed_seconds": result.get("elapsed_seconds"),
        "partial_generation": partial_generation,
        "effective_expected_models_total": effective_expected_models,
        "llm_error_events": int(trial_json.get("llm_error_events", 0) or 0),
        "llm_error_samples": trial_json.get("llm_error_samples", []),
        "proposal_id": trained_proposal.get("proposal_id"),
        "proposal_status": trained_proposal.get("status"),
        "trained_model_uri": (trained_proposal.get("llm_metadata") or {}).get("trained_model_uri"),
        "training_kpis_keys": list(((trained_proposal.get("llm_metadata") or {}).get("training_kpis") or {}).keys()),
        "latest_event_type": (summary.get("latest_event") or {}).get("event_type"),
        "latest_artifact_type": (summary.get("latest_artifact") or {}).get("artifact_type"),
        "latest_artifact_uri": (summary.get("latest_artifact") or {}).get("uri"),
        "reference_context": {
            "reference_models_count": int(references_payload.get("reference_models_count", 0) or 0),
            "reference_policy_version": references_payload.get("reference_policy_version"),
            "fallback_used": bool(references_payload.get("fallback_used", False)),
            "references": references_payload.get("references", []),
        },
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"[e2e] FAIL: {error}")
        raise
