from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class CheckpointStore:
    def __init__(self, checkpoint_path: str) -> None:
        self.path = Path(checkpoint_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def save(self, payload: dict[str, Any]) -> None:
        with self.path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2, ensure_ascii=False)
