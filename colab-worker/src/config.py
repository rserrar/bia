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
    verify_legacy_model_build: bool
    legacy_build_check_strict: bool
    legacy_model_json_path: str
    legacy_experiment_config_path: str
    legacy_builder_path: str


def load_worker_config() -> WorkerConfig:
    return WorkerConfig(
        api_base_url=os.getenv("V2_API_BASE_URL", "http://localhost:8080"),
        api_token=os.getenv("V2_API_TOKEN", ""),
        code_version=os.getenv("V2_CODE_VERSION", "dev"),
        run_metadata={"executor": "colab"},
        checkpoint_path=os.getenv("V2_CHECKPOINT_PATH", "/content/drive/MyDrive/bia_v2/run_state.json"),
        heartbeat_interval_seconds=int(os.getenv("V2_HEARTBEAT_INTERVAL_SECONDS", "30")),
        max_generations=int(os.getenv("V2_MAX_GENERATIONS", "3")),
        verify_legacy_model_build=os.getenv("V2_VERIFY_LEGACY_MODEL_BUILD", "").lower() in {"1", "true", "yes"},
        legacy_build_check_strict=os.getenv("V2_LEGACY_BUILD_CHECK_STRICT", "").lower() in {"1", "true", "yes"},
        legacy_model_json_path=os.getenv("V2_LEGACY_MODEL_JSON_PATH", "/content/b-ia/models/base/model_exemple_complex_v1.json"),
        legacy_experiment_config_path=os.getenv("V2_LEGACY_EXPERIMENT_CONFIG_PATH", "/content/b-ia/config_experiment.json"),
        legacy_builder_path=os.getenv("V2_LEGACY_BUILDER_PATH", "/content/b-ia/utils/model_builder.py"),
    )
