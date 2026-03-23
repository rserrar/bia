from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _start_trainer(repo_root: Path, trainer_log_file: Path) -> subprocess.Popen[str]:
    trainer_log_file.parent.mkdir(parents=True, exist_ok=True)
    log_handle = open(trainer_log_file, "a", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, str(repo_root / "colab-worker" / "run_trainer.py")],
        cwd=str(repo_root),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return process


def _run_health_check(repo_root: Path) -> tuple[bool, dict]:
    proc = subprocess.run(
        [sys.executable, str(repo_root / "ops" / "scripts" / "p0_health_check.py")],
        cwd=str(repo_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    payload = {}
    try:
        payload = json.loads(proc.stdout)
    except Exception:
        payload = {"ok": False, "raw_output": proc.stdout[-2000:]}
    return proc.returncode == 0 and bool(payload.get("ok")), payload


def main() -> int:
    repo_root = _repo_root()
    check_interval = int(os.getenv("V2_SUPERVISOR_CHECK_INTERVAL_SECONDS", "300"))
    restart_delay = int(os.getenv("V2_SUPERVISOR_RESTART_DELAY_SECONDS", "10"))
    max_restarts = int(os.getenv("V2_SUPERVISOR_MAX_RESTARTS", "50"))

    trainer_log_file = Path(
        os.getenv(
            "V2_SUPERVISOR_TRAINER_LOG_FILE",
            str(repo_root / "colab-worker" / "checkpoints" / "trainer_supervisor_trainer.log"),
        )
    )
    supervisor_log_file = Path(
        os.getenv(
            "V2_SUPERVISOR_LOG_FILE",
            str(repo_root / "colab-worker" / "checkpoints" / "trainer_supervisor.log"),
        )
    )
    supervisor_log_file.parent.mkdir(parents=True, exist_ok=True)

    restarts = 0
    process = _start_trainer(repo_root, trainer_log_file)
    last_check_ts = 0.0

    print(f"[supervisor] started trainer pid={process.pid}")
    with open(supervisor_log_file, "a", encoding="utf-8") as slog:
        def _log(entry: dict) -> None:
            line = json.dumps(entry, ensure_ascii=False)
            slog.write(line + "\n")
            slog.flush()
            print(line)

        _log({"ts": _utc_now(), "event": "trainer_started", "pid": process.pid})

        try:
            while True:
                code = process.poll()
                if code is not None:
                    restarts += 1
                    _log({"ts": _utc_now(), "event": "trainer_exited", "code": code, "restarts": restarts})
                    if restarts > max_restarts:
                        _log({"ts": _utc_now(), "event": "supervisor_stopping", "reason": "max_restarts_exceeded"})
                        return 1
                    time.sleep(max(1, restart_delay))
                    process = _start_trainer(repo_root, trainer_log_file)
                    _log({"ts": _utc_now(), "event": "trainer_restarted", "pid": process.pid, "restarts": restarts})

                now = time.time()
                if now - last_check_ts >= max(30, check_interval):
                    ok, payload = _run_health_check(repo_root)
                    _log(
                        {
                            "ts": _utc_now(),
                            "event": "health_check",
                            "status": "PASS" if ok else "FAIL",
                            "summary": {
                                "runs_count": payload.get("runs_count"),
                                "proposals_count": payload.get("proposals_count"),
                                "error": payload.get("error"),
                            },
                        }
                    )
                    last_check_ts = now

                time.sleep(2)
        except KeyboardInterrupt:
            _log({"ts": _utc_now(), "event": "supervisor_interrupted"})
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except Exception:
                    process.kill()
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
