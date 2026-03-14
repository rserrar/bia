from __future__ import annotations

import os
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class WorkerConfig:
    api_base_url: str
    api_path_prefix: str
    api_token: str
    code_version: str
    run_metadata: dict
    checkpoint_path: str
    heartbeat_interval_seconds: int
    max_generations: int
    auto_process_proposals_phase0: bool
    proposals_phase0_batch_size: int
    llm_enabled: bool
    llm_use_legacy_interface: bool
    llm_provider: str
    llm_endpoint: str
    llm_api_key: str
    llm_model: str
    llm_timeout_seconds: int
    llm_temperature: float
    llm_max_tokens: int
    llm_system_prompt: str
    llm_config_file: str
    llm_prompt_template_file: str
    llm_architecture_guide_file: str
    llm_experiment_config_file: str
    llm_num_new_models: int
    llm_num_reference_models: int
    verify_legacy_model_build: bool
    legacy_build_check_strict: bool
    legacy_model_json_path: str
    legacy_experiment_config_path: str
    legacy_builder_path: str


def load_worker_config() -> WorkerConfig:
    config_file = os.getenv("V2_LLM_CONFIG_FILE", "")
    file_settings: dict = {}
    if config_file.strip():
        config_path = Path(config_file.strip())
        if not config_path.is_absolute() and not config_path.exists():
            repo_root = Path(__file__).resolve().parents[3]
            config_path = (repo_root / config_path).resolve()
        if config_path.exists():
            try:
                file_settings = json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                file_settings = {}
    file_api_key = str(file_settings.get("openai_api_key", "")).strip()
    file_env_var = str(file_settings.get("openai_api_key_env_var", "")).strip()
    if file_api_key == "" and file_env_var:
        file_api_key = os.getenv(file_env_var, "").strip()

    return WorkerConfig(
        api_base_url=os.getenv("V2_API_BASE_URL", "http://localhost:8080"),
        api_path_prefix=os.getenv("V2_API_PATH_PREFIX", ""),
        api_token=os.getenv("V2_API_TOKEN", ""),
        code_version=os.getenv("V2_CODE_VERSION", "dev"),
        run_metadata={"executor": "colab"},
        checkpoint_path=os.getenv("V2_CHECKPOINT_PATH", "/content/drive/MyDrive/bia_v2/run_state.json"),
        heartbeat_interval_seconds=int(os.getenv("V2_HEARTBEAT_INTERVAL_SECONDS", "30")),
        max_generations=int(os.getenv("V2_MAX_GENERATIONS", "3")),
        auto_process_proposals_phase0=os.getenv("V2_AUTO_PROCESS_PROPOSALS_PHASE0", "true").lower() in {"1", "true", "yes"},
        proposals_phase0_batch_size=int(os.getenv("V2_PROPOSALS_PHASE0_BATCH_SIZE", "20")),
        llm_enabled=os.getenv("V2_LLM_ENABLED", "false").lower() in {"1", "true", "yes"},
        llm_use_legacy_interface=os.getenv("V2_LLM_USE_LEGACY_INTERFACE", "true").lower() in {"1", "true", "yes"},
        llm_provider=os.getenv("V2_LLM_PROVIDER", "mock"),
        llm_endpoint=os.getenv("V2_LLM_ENDPOINT", ""),
        llm_api_key=os.getenv("V2_LLM_API_KEY", file_api_key),
        llm_model=os.getenv("V2_LLM_MODEL", "gpt-5.3-codex"),
        llm_timeout_seconds=int(os.getenv("V2_LLM_TIMEOUT_SECONDS", "45")),
        llm_temperature=float(os.getenv("V2_LLM_TEMPERATURE", "0.2")),
        llm_max_tokens=int(os.getenv("V2_LLM_MAX_TOKENS", "700")),
        llm_system_prompt=os.getenv(
            "V2_LLM_SYSTEM_PROMPT",
            "Return only a JSON object with keys base_model_id and proposal.",
        ),
        llm_config_file=os.getenv("V2_LLM_CONFIG_FILE", "config/llm_settings.json"),
        llm_prompt_template_file=os.getenv("V2_LLM_PROMPT_TEMPLATE_FILE", "prompts/generate_new_models.txt"),
        llm_architecture_guide_file=os.getenv("V2_LLM_ARCHITECTURE_GUIDE_FILE", "prompts/instruccions.md"),
        llm_experiment_config_file=os.getenv("V2_LLM_EXPERIMENT_CONFIG_FILE", "/content/b-ia/config_experiment.json"),
        llm_num_new_models=int(os.getenv("V2_LLM_NUM_NEW_MODELS", "1")),
        llm_num_reference_models=int(os.getenv("V2_LLM_NUM_REFERENCE_MODELS", "3")),
        verify_legacy_model_build=os.getenv("V2_VERIFY_LEGACY_MODEL_BUILD", "").lower() in {"1", "true", "yes"},
        legacy_build_check_strict=os.getenv("V2_LEGACY_BUILD_CHECK_STRICT", "").lower() in {"1", "true", "yes"},
        legacy_model_json_path=os.getenv("V2_LEGACY_MODEL_JSON_PATH", "/content/b-ia/models/base/model_exemple_complex_v1.json"),
        legacy_experiment_config_path=os.getenv("V2_LEGACY_EXPERIMENT_CONFIG_PATH", "/content/b-ia/config_experiment.json"),
        legacy_builder_path=os.getenv("V2_LEGACY_BUILDER_PATH", "/content/b-ia/utils/model_builder.py"),
    )
