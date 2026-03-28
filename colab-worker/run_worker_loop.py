from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, TextIO, cast

from src.api_client import ApiClient
from src.config import load_worker_config


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _worker_id() -> str:
    return os.getenv("V2_WORKER_ID", f"colab_worker_{int(time.time())}")


def _build_client() -> ApiClient:
    config = load_worker_config()
    return ApiClient(
        base_url=config.api_base_url,
        token=config.api_token,
        timeout_seconds=config.api_timeout_seconds,
        connect_timeout_seconds=config.api_connect_timeout_seconds,
        read_timeout_seconds=config.api_read_timeout_seconds,
        max_retries=config.api_max_retries,
        circuit_breaker_threshold=config.api_circuit_breaker_threshold,
        circuit_breaker_cooldown_seconds=config.api_circuit_breaker_cooldown_seconds,
        api_path_prefix=config.api_path_prefix,
    )


def _run_command(command: list[str], extra_env: dict[str, str]) -> tuple[int, str]:
    env = os.environ.copy()
    env.update(extra_env)
    proc = subprocess.run(command, cwd=str(_repo_root()), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
    return proc.returncode, proc.stdout[-4000:]


def _run_command_with_progress(
    client: ApiClient,
    request_id: str,
    worker_id: str,
    command: list[str],
    extra_env: dict[str, str],
    initial_summary: dict[str, Any],
    heartbeat_interval_seconds: int = 8,
) -> tuple[int, str, dict[str, Any]]:
    env = os.environ.copy()
    env.update(extra_env)
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        command,
        cwd=str(_repo_root()),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    stdout = cast(TextIO, proc.stdout)

    lines_queue: queue.Queue[str | None] = queue.Queue()
    collected_lines: list[str] = []
    summary = dict(initial_summary)
    summary.setdefault("run_ids", [])
    summary.setdefault("stage", "starting")
    summary.setdefault("stage_label", "Inicialitzant execució")
    last_heartbeat = 0.0

    def _reader() -> None:
        try:
            for line in stdout:
                lines_queue.put(line)
        finally:
            lines_queue.put(None)

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()

    def _merge_summary(update: dict[str, Any]) -> None:
        nonlocal summary
        merged = dict(summary)
        merged.update(update)
        run_ids: list[str] = []
        existing_run_ids = summary.get("run_ids", [])
        updated_run_ids = update.get("run_ids", [])
        for raw_run_id in (existing_run_ids if isinstance(existing_run_ids, list) else []) + (updated_run_ids if isinstance(updated_run_ids, list) else []):
            if isinstance(raw_run_id, str) and raw_run_id.strip() != "" and raw_run_id not in run_ids:
                run_ids.append(raw_run_id)
        current_run_id = str(update.get("current_run_id", update.get("run_id", summary.get("current_run_id", ""))))
        if current_run_id.strip() != "" and current_run_id not in run_ids:
            run_ids.append(current_run_id)
        merged["run_ids"] = run_ids
        if current_run_id.strip() != "":
            merged["current_run_id"] = current_run_id
            merged["run_id"] = current_run_id
        summary = merged

    def _progress_from_line(line: str) -> dict[str, Any] | None:
        stripped = line.strip()
        if stripped == "":
            return None
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                payload = json.loads(stripped)
            except Exception:
                payload = None
            if isinstance(payload, dict):
                if bool(payload.get("progress_event")):
                    return {k: v for k, v in payload.items() if k != "progress_event"}
                if isinstance(payload.get("run_id"), str) and payload.get("run_id"):
                    return {
                        "run_id": payload.get("run_id"),
                        "current_run_id": payload.get("run_id"),
                        "run_ids": [payload.get("run_id")],
                        "generations_completed": payload.get("generations_completed", payload.get("generations", 0)),
                        "models_generated": payload.get("models_generated", payload.get("proposals_created", 0)),
                        "models_trained": payload.get("models_trained", payload.get("trained_total", 0)),
                        "latest_event_type": payload.get("latest_event_type"),
                        "latest_event_label": payload.get("latest_event_label"),
                        "stage": payload.get("stage", "running"),
                        "stage_label": payload.get("stage_label", "Execució en curs"),
                        "elapsed_seconds": payload.get("elapsed_seconds"),
                    }
        run_id_match = re.search(r"run_id=([A-Za-z0-9_\-]+)", stripped)
        if run_id_match:
            run_id = run_id_match.group(1)
            return {"run_id": run_id, "current_run_id": run_id, "run_ids": [run_id]}
        return None

    while True:
        now = time.time()
        if now - last_heartbeat >= heartbeat_interval_seconds:
            summary["heartbeat_sent_at"] = int(now)
            client.heartbeat_execution_request(request_id, worker_id, result_summary=summary)
            last_heartbeat = now

        try:
            item = lines_queue.get(timeout=1)
        except queue.Empty:
            if proc.poll() is not None:
                break
            continue

        if item is None:
            break
        collected_lines.append(item)
        progress_update = _progress_from_line(item)
        if progress_update is not None:
            _merge_summary(progress_update)

    return_code = proc.wait()
    raw_output = "".join(collected_lines)
    output_tail = _compact_output_tail(raw_output)
    final_json = _extract_last_json_block(raw_output[-12000:])
    if final_json:
        _merge_summary(final_json)
    return return_code, output_tail, summary


def _extract_last_json_block(text: str) -> dict[str, object]:
    matches = re.findall(r"\{[\s\S]*\}", text)
    for candidate in reversed(matches):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            continue
    return {}


def _compact_output_tail(text: str, max_tail_lines: int = 12, max_interesting_lines: int = 12) -> str:
    lines = [line.rstrip() for line in text.splitlines() if line.strip() != ""]
    if not lines:
        return ""
    noise_markers = (
        "cuda",
        "tensorflow/core/platform/cpu_feature_guard",
        "computation_placer",
        "could not find cuda drivers",
        "attempting to register factory",
        '"progress_event": true',
    )
    interesting: list[str] = []
    tail: list[str] = []
    for line in lines:
        lowered = line.lower()
        if any(marker in lowered for marker in noise_markers):
            continue
        if any(marker in lowered for marker in ("error", "fail", "checkpoint", "trainer", "proposal", "run_id=", '"ok"', '"run_id"', "champion")):
            interesting.append(line)
        tail.append(line)
    selected: list[str] = []
    for line in interesting[-max_interesting_lines:] + tail[-max_tail_lines:]:
        if line not in selected:
            selected.append(line)
    return "\n".join(selected)[-5000:]


def _as_positive_int(value: object, default: int = 1) -> int:
    if isinstance(value, bool):
        return max(1, default)
    if isinstance(value, int):
        return max(1, value)
    if isinstance(value, float):
        return max(1, int(value))
    if isinstance(value, str):
        try:
            return max(1, int(value.strip() or str(default)))
        except Exception:
            return max(1, default)
    return max(1, default)


def _execute_request(client: ApiClient, request_id: str, request: dict, worker_id: str) -> tuple[bool, dict]:
    request_type = str(request.get("type", "")).strip()
    config_raw = request.get("config")
    config: dict[str, object] = config_raw if isinstance(config_raw, dict) else {}
    profile = str(config.get("profile", "small_test"))
    generations_int = _as_positive_int(config.get("generations", 1), 1)
    models_per_generation_int = _as_positive_int(config.get("models_per_generation", 1), 1)
    generations = str(generations_int)
    models_per_generation = str(models_per_generation_int)
    extra_env = {
        "V2_SELECTION_POLICY_PROFILE": profile,
        "V2_LLM_TRIAL_GENERATIONS": generations,
        "V2_E2E_GENERATIONS": generations,
        "V2_LLM_NUM_NEW_MODELS": models_per_generation,
        "V2_MODELS_PER_GENERATION": models_per_generation,
        "V2_CHAMPION_SCOPE": str(config.get("champion_scope", os.getenv("V2_CHAMPION_SCOPE", "run"))),
        "V2_SUPERVISOR_AUTO_FEED": "true" if bool(config.get("auto_feed", False)) else "false",
        "V2_RESUME_ENABLED": "true" if bool(config.get("resume_enabled", True)) else "false",
        "V2_MAX_RESUME_ATTEMPTS": os.getenv("V2_MAX_RESUME_ATTEMPTS", "2") if bool(config.get("resume_enabled", True)) else "0",
    }
    base_summary: dict[str, Any] = {
        "type": request_type,
        "profile": profile,
        "stage": "queued_for_execution",
        "stage_label": "Esperant arrencada del worker executor",
        "generations_total": generations_int,
        "generations_completed": 0,
        "models_per_generation": models_per_generation_int,
        "models_generated": 0,
        "models_trained": 0,
        "run_ids": [],
    }

    if request_type == "smoke_run":
        rc, out, summary = _run_command_with_progress(client, request_id, worker_id, [sys.executable, str(_repo_root() / "ops" / "scripts" / "run_e2e_final_smoke.py")], extra_env, base_summary)
        return rc == 0, {**summary, "output_tail": out}
    if request_type == "integration_matrix":
        extra_env.update(
            {
                "V2_MATRIX_MODE": "run",
                "V2_MATRIX_RUNS": str(config.get("runs", 3)),
                "V2_MATRIX_PROFILES": str(config.get("profiles", profile)),
                "V2_MATRIX_GENERATIONS": generations,
            }
        )
        rc, out, summary = _run_command_with_progress(client, request_id, worker_id, [sys.executable, str(_repo_root() / "ops" / "scripts" / "run_integration_matrix.py")], extra_env, {**base_summary, "stage": "running_matrix", "stage_label": "Executant bateria d'integració"})
        return rc == 0, {**summary, "output_tail": out}
    if request_type == "cleanup":
        extra_env["V2_CLEANUP_MODE"] = str(config.get("cleanup_mode", "apply"))
        rc, out, summary = _run_command_with_progress(client, request_id, worker_id, [sys.executable, str(_repo_root() / "ops" / "scripts" / "cleanup_inconsistent_state.py")], extra_env, {**base_summary, "stage": "cleanup", "stage_label": "Netegant estats inconsistents"})
        return rc == 0, {**summary, "output_tail": out}
    if request_type == "resume_training":
        rc, out, summary = _run_command_with_progress(client, request_id, worker_id, [sys.executable, str(_repo_root() / "colab-worker" / "run_trainer.py")], extra_env, {**base_summary, "stage": "resume_training", "stage_label": "Reprenent entrenaments pendents"})
        return rc == 0, {**summary, "output_tail": out}
    if request_type == "micro_training":
        rc, out, summary = _run_command_with_progress(client, request_id, worker_id, [sys.executable, str(_repo_root() / "ops" / "scripts" / "run_e2e_final_smoke.py")], extra_env, {**base_summary, "stage": "micro_training", "stage_label": "Executant micro training"})
        return rc == 0, {**summary, "output_tail": out}
    return False, {"type": request_type, "error": "unsupported_request_type"}


def main() -> int:
    client = _build_client()
    worker_id = _worker_id()
    stale_after_seconds = int(os.getenv("V2_EXECUTION_REQUEST_STALE_AFTER_SECONDS", "120"))
    poll_seconds = int(os.getenv("V2_EXECUTION_REQUEST_POLL_SECONDS", "10"))

    print(f"[worker-loop] worker_id={worker_id}")
    while True:
        try:
            pending = client.list_pending_execution_requests(limit=1, stale_after_seconds=stale_after_seconds)
            if not pending:
                time.sleep(max(2, poll_seconds))
                continue
            request = pending[0]
            request_id = str(request.get("request_id", "")).strip()
            if request_id == "":
                time.sleep(max(2, poll_seconds))
                continue
            claimed = client.claim_execution_request(request_id, worker_id, stale_after_seconds=stale_after_seconds)
            client.start_execution_request(request_id, worker_id)
            ok, result = _execute_request(client, request_id, claimed, worker_id)
            client.heartbeat_execution_request(request_id, worker_id, result_summary=result)
            if ok:
                client.complete_execution_request(request_id, result_summary=result)
            else:
                client.fail_execution_request(request_id, error_summary=str(result.get("error", "execution_failed")), result_summary=result)
        except KeyboardInterrupt:
            return 0
        except Exception as error:
            print(f"[worker-loop] error: {error}")
            time.sleep(max(2, poll_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
