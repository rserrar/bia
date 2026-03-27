from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

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


def _execute_request(request: dict, worker_id: str) -> tuple[bool, dict]:
    request_type = str(request.get("type", "")).strip()
    config_raw = request.get("config")
    config: dict[str, object] = config_raw if isinstance(config_raw, dict) else {}
    profile = str(config.get("profile", "small_test"))
    generations = str(config.get("generations", 1))
    models_per_generation = str(config.get("models_per_generation", 1))
    extra_env = {
        "V2_SELECTION_POLICY_PROFILE": profile,
        "V2_LLM_TRIAL_GENERATIONS": generations,
        "V2_E2E_GENERATIONS": generations,
        "V2_LLM_NUM_NEW_MODELS": models_per_generation,
        "V2_CHAMPION_SCOPE": str(config.get("champion_scope", os.getenv("V2_CHAMPION_SCOPE", "run"))),
        "V2_SUPERVISOR_AUTO_FEED": "true" if bool(config.get("auto_feed", False)) else "false",
    }

    if request_type == "smoke_run":
        rc, out = _run_command([sys.executable, str(_repo_root() / "ops" / "scripts" / "run_e2e_final_smoke.py")], extra_env)
        parsed = _extract_last_json_block(out)
        return rc == 0, {"type": request_type, "profile": profile, "generations_completed": int(generations), "models_per_generation": int(models_per_generation), **parsed, "output_tail": out}
    if request_type == "integration_matrix":
        extra_env.update(
            {
                "V2_MATRIX_MODE": "run",
                "V2_MATRIX_RUNS": str(config.get("runs", 3)),
                "V2_MATRIX_PROFILES": str(config.get("profiles", profile)),
                "V2_MATRIX_GENERATIONS": generations,
            }
        )
        rc, out = _run_command([sys.executable, str(_repo_root() / "ops" / "scripts" / "run_integration_matrix.py")], extra_env)
        parsed = _extract_last_json_block(out)
        return rc == 0, {"type": request_type, "profile": profile, "generations_completed": int(generations), "models_per_generation": int(models_per_generation), **parsed, "output_tail": out}
    if request_type == "cleanup":
        extra_env["V2_CLEANUP_MODE"] = str(config.get("cleanup_mode", "apply"))
        rc, out = _run_command([sys.executable, str(_repo_root() / "ops" / "scripts" / "cleanup_inconsistent_state.py")], extra_env)
        parsed = _extract_last_json_block(out)
        return rc == 0, {"type": request_type, **parsed, "output_tail": out}
    if request_type == "resume_training":
        rc, out = _run_command([sys.executable, str(_repo_root() / "colab-worker" / "run_trainer.py")], extra_env)
        return rc == 0, {"type": request_type, "generations_completed": 0, "models_per_generation": int(models_per_generation), "output_tail": out}
    if request_type == "micro_training":
        rc, out = _run_command([sys.executable, str(_repo_root() / "ops" / "scripts" / "run_e2e_final_smoke.py")], extra_env)
        parsed = _extract_last_json_block(out)
        return rc == 0, {"type": request_type, "profile": profile, "generations_completed": int(generations), "models_per_generation": int(models_per_generation), **parsed, "output_tail": out}
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
            ok, result = _execute_request(claimed, worker_id)
            client.heartbeat_execution_request(request_id, worker_id)
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
