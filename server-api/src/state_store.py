from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any


class JsonStateStore:
    def __init__(self, file_path: str | Path) -> None:
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        if not self.file_path.exists():
            self._write({"runs": {}, "events": [], "metrics": [], "artifacts": []})

    def _read(self) -> dict[str, Any]:
        with self.file_path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def _write(self, data: dict[str, Any]) -> None:
        with self.file_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False)

    def read_all(self) -> dict[str, Any]:
        with self._lock:
            return self._read()

    def upsert_run(self, run_payload: dict[str, Any]) -> None:
        with self._lock:
            data = self._read()
            data["runs"][run_payload["run_id"]] = run_payload
            self._write(data)

    def append_event(self, payload: dict[str, Any]) -> None:
        with self._lock:
            data = self._read()
            data["events"].append(payload)
            self._write(data)

    def append_metric(self, payload: dict[str, Any]) -> None:
        with self._lock:
            data = self._read()
            data["metrics"].append(payload)
            self._write(data)

    def append_artifact(self, payload: dict[str, Any]) -> None:
        with self._lock:
            data = self._read()
            data["artifacts"].append(payload)
            self._write(data)
