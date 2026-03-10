from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class WorkerConfig:
    api_base_url: str
    api_token: str
    code_version: str
    run_metadata: dict
    checkpoint_path: str
    heartbeat_interval_seconds: int
    max_generations: int


def load_worker_config() -> WorkerConfig:
    return WorkerConfig(
        api_base_url=os.getenv("V2_API_BASE_URL", "http://localhost:8080"),
        api_token=os.getenv("V2_API_TOKEN", ""),
        code_version=os.getenv("V2_CODE_VERSION", "dev"),
        run_metadata={"executor": "colab"},
        checkpoint_path=os.getenv("V2_CHECKPOINT_PATH", "/content/drive/MyDrive/bia_v2/run_state.json"),
        heartbeat_interval_seconds=int(os.getenv("V2_HEARTBEAT_INTERVAL_SECONDS", "30")),
        max_generations=int(os.getenv("V2_MAX_GENERATIONS", "3")),
    )
