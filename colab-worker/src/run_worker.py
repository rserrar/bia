from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _runtime_process_state_path() -> Path:
    checkpoint_path = Path(os.getenv("V2_CHECKPOINT_PATH", "/content/drive/MyDrive/bia_v2/run_state.json"))
    checkpoint_dir = checkpoint_path.parent
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    return checkpoint_dir / "runtime_processes.json"


def _pid_is_alive(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _terminate_process(process: subprocess.Popen[bytes] | None, label: str) -> None:
    if process is None or process.poll() is not None:
        return
    print(f"🛑 Runtime launcher: aturant {label} (PID {process.pid})...")
    try:
        if os.name == "nt":
            process.terminate()
        else:
            os.kill(process.pid, signal.SIGTERM)
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
    except Exception as error:
        print(f"⚠️ Runtime launcher: error aturant {label}: {error}")


def _write_process_state(path: Path, controller: subprocess.Popen[bytes] | None, trainer: subprocess.Popen[bytes] | None, watchdog: subprocess.Popen[bytes] | None, trainer_restarts: int) -> None:
    payload = {
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "controller": {
            "pid": controller.pid if controller and controller.poll() is None else None,
            "alive": bool(controller and controller.poll() is None),
        },
        "trainer": {
            "pid": trainer.pid if trainer and trainer.poll() is None else None,
            "alive": bool(trainer and trainer.poll() is None),
            "restart_count": trainer_restarts,
        },
        "watchdog": {
            "pid": watchdog.pid if watchdog and watchdog.poll() is None else None,
            "alive": bool(watchdog and watchdog.poll() is None),
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def _spawn(role: str, script_path: Path, extra_env: dict[str, str]) -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    env.update(extra_env)
    env["V2_RUNTIME_ROLE"] = role
    process = subprocess.Popen(
        [sys.executable, str(script_path)],
        cwd=str(_repo_root()),
        env=env,
        stdout=None,
        stderr=None,
    )
    print(f"🚀 Runtime launcher: {role} iniciat amb PID {process.pid}")
    return process


def main() -> int:
    repo_root = _repo_root()
    state_path = _runtime_process_state_path()
    common_env = {
        "V2_RUNTIME_PROCESS_STATE_PATH": str(state_path),
    }
    controller_script = repo_root / "colab-worker" / "run_controller.py"
    trainer_script = repo_root / "colab-worker" / "run_trainer.py"
    watchdog_script = repo_root / "colab-worker" / "run_watchdog.py"

    controller: subprocess.Popen[bytes] | None = None
    trainer: subprocess.Popen[bytes] | None = None
    watchdog: subprocess.Popen[bytes] | None = None
    trainer_restarts = 0

    try:
        trainer = _spawn("trainer", trainer_script, common_env)
        controller = _spawn("controller", controller_script, common_env)
        watchdog = _spawn("watchdog", watchdog_script, common_env)
        _write_process_state(state_path, controller, trainer, watchdog, trainer_restarts)

        while True:
            controller_alive = controller.poll() is None if controller else False
            trainer_alive = trainer.poll() is None if trainer else False
            watchdog_alive = watchdog.poll() is None if watchdog else False

            if not controller_alive:
                controller_rc = controller.returncode if controller else 1
                print(f"ℹ️ Runtime launcher: controller finalitzat amb codi {controller_rc}")
                _write_process_state(state_path, controller, trainer, watchdog, trainer_restarts)
                return int(controller_rc or 0)

            if not trainer_alive:
                trainer_restarts += 1
                print(f"⚠️ Runtime launcher: trainer mort; reinici #{trainer_restarts}")
                trainer = _spawn("trainer", trainer_script, common_env)

            if not watchdog_alive:
                print("⚠️ Runtime launcher: watchdog mort; reiniciant...")
                watchdog = _spawn("watchdog", watchdog_script, common_env)

            _write_process_state(state_path, controller, trainer, watchdog, trainer_restarts)
            time.sleep(max(5, int(os.getenv("V2_RUNTIME_LAUNCHER_POLL_SECONDS", "10"))))
    except KeyboardInterrupt:
        print("\n👋 Runtime launcher aturat manualment.")
        return 0
    finally:
        _write_process_state(state_path, controller, trainer, watchdog, trainer_restarts)
        _terminate_process(watchdog, "watchdog")
        _terminate_process(trainer, "trainer")
        _terminate_process(controller, "controller")
        _write_process_state(state_path, controller, trainer, watchdog, trainer_restarts)


if __name__ == "__main__":
    raise SystemExit(main())
