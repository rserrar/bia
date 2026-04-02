from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from src.api_client import ApiClient
from src.config import load_worker_config


def _runtime_state_path() -> Path:
    default_path = Path(os.getenv("V2_CHECKPOINT_PATH", "/content/drive/MyDrive/bia_v2/run_state.json")).parent / "runtime_processes.json"
    return Path(os.getenv("V2_RUNTIME_PROCESS_STATE_PATH", str(default_path)))


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _read_run_id() -> str:
    checkpoint_path = Path(os.getenv("V2_CHECKPOINT_PATH", "/content/drive/MyDrive/bia_v2/run_state.json"))
    state = _read_json(checkpoint_path)
    return str(state.get("run_id", "")).strip()


def _parse_timestamp(raw: object) -> float | None:
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if text == "":
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _pid_changed_or_dead(info: dict[str, Any], known_pid: int | None) -> bool:
    current_pid = info.get("pid")
    alive = bool(info.get("alive"))
    if known_pid is None:
        return False
    return current_pid != known_pid or not alive


def main() -> int:
    print("Iniciant V2 Runtime Watchdog...")
    config = load_worker_config()
    api = ApiClient(
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
    state_path = _runtime_state_path()
    poll_seconds = max(5, int(os.getenv("V2_WATCHDOG_POLL_SECONDS", "15")))
    trainer_stall_seconds = max(60, int(os.getenv("V2_TRAINER_STALL_WARNING_SECONDS", "900")))

    known_controller_pid: int | None = None
    known_trainer_pid: int | None = None
    reported_dead_controller: set[int] = set()
    reported_dead_trainer: set[int] = set()
    reported_stalled_proposals: set[str] = set()

    while True:
        try:
            process_state = _read_json(state_path)
            run_id = _read_run_id()
            controller_info = process_state.get("controller") if isinstance(process_state.get("controller"), dict) else {}
            trainer_info = process_state.get("trainer") if isinstance(process_state.get("trainer"), dict) else {}

            controller_pid_raw = controller_info.get("pid")
            trainer_pid_raw = trainer_info.get("pid")
            controller_pid = int(controller_pid_raw) if isinstance(controller_pid_raw, int) else None
            trainer_pid = int(trainer_pid_raw) if isinstance(trainer_pid_raw, int) else None

            if run_id != "":
                if known_controller_pid is not None and _pid_changed_or_dead(controller_info, known_controller_pid) and known_controller_pid not in reported_dead_controller:
                    reported_dead_controller.add(known_controller_pid)
                    api.add_event(
                        run_id,
                        "controller_process_unhealthy",
                        "Watchdog ha detectat controller mort o reemplaçat",
                        {"controller_pid": known_controller_pid},
                    )
                if known_trainer_pid is not None and _pid_changed_or_dead(trainer_info, known_trainer_pid) and known_trainer_pid not in reported_dead_trainer:
                    reported_dead_trainer.add(known_trainer_pid)
                    api.add_event(
                        run_id,
                        "trainer_process_restarted",
                        "Watchdog ha detectat trainer mort o reiniciat",
                        {
                            "trainer_pid": known_trainer_pid,
                            "restart_count": trainer_info.get("restart_count", 0),
                        },
                    )

            if controller_pid is not None:
                known_controller_pid = controller_pid
            if trainer_pid is not None:
                known_trainer_pid = trainer_pid

            if run_id == "":
                time.sleep(poll_seconds)
                continue

            try:
                proposals = api.list_model_proposals(limit=300)
            except Exception:
                proposals = []
            now_ts = time.time()
            active_stalled: set[str] = set()
            for proposal in proposals:
                if str(proposal.get("source_run_id", "")).strip() != run_id:
                    continue
                if str(proposal.get("status", "")).strip() != "training":
                    continue
                llm_metadata = proposal.get("llm_metadata") if isinstance(proposal.get("llm_metadata"), dict) else {}
                proposal_id = str(proposal.get("proposal_id", "")).strip()
                last_event_ts = _parse_timestamp(llm_metadata.get("last_training_event_at"))
                if proposal_id == "" or last_event_ts is None:
                    continue
                age = now_ts - last_event_ts
                if age < trainer_stall_seconds:
                    continue
                active_stalled.add(proposal_id)
                if proposal_id in reported_stalled_proposals:
                    continue
                reported_stalled_proposals.add(proposal_id)
                api.add_event(
                    run_id,
                    "trainer_progress_stalled_warning",
                    f"Watchdog alerta de possible stall a {proposal_id}",
                    {
                        "proposal_id": proposal_id,
                        "seconds_since_last_training_event": round(age, 1),
                        "trainer_stall_warning_seconds": trainer_stall_seconds,
                    },
                )
            reported_stalled_proposals.intersection_update(active_stalled)
        except KeyboardInterrupt:
            return 0
        except Exception as error:
            print(f"⚠️ Watchdog error: {error}")
        time.sleep(poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
