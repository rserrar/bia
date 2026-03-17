from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


def _resolve_repo_path(path_str: str, repo_root: Path) -> Path:
    raw = Path(path_str.strip())
    if raw.is_absolute():
        if raw.exists():
            return raw
        normalized = str(raw).replace("\\", "/")
        if "/V2/" in normalized:
            fallback = Path(normalized.replace("/V2/", "/", 1))
            if fallback.exists():
                return fallback
        return raw
    candidate = (repo_root / raw).resolve()
    if candidate.exists():
        return candidate
    normalized_rel = str(raw).replace("\\", "/")
    if normalized_rel.startswith("V2/"):
        fallback = (repo_root / normalized_rel[3:]).resolve()
        if fallback.exists():
            return fallback
    return candidate


@dataclass
class WorkerConfig:
    api_base_url: str
    api_path_prefix: str
    api_token: str
    api_timeout_seconds: int
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
    llm_fix_error_prompt_file: str
    llm_architecture_guide_file: str
    llm_experiment_config_file: str
    llm_num_new_models: int
    llm_num_reference_models: int
    llm_min_interval_seconds: int
    llm_repair_on_validation_error: bool
    verify_legacy_model_build: bool
    legacy_build_check_strict: bool
    legacy_model_json_path: str
    legacy_experiment_config_path: str
    legacy_builder_path: str


def load_worker_config() -> WorkerConfig:
    repo_root = Path(__file__).resolve().parents[2]
    config_file = os.getenv("V2_LLM_CONFIG_FILE", "")
    file_settings: dict = {}
    if config_file.strip():
        config_path = _resolve_repo_path(config_file, repo_root)
        if config_path.exists():
            try:
                file_settings = json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                file_settings = {}
    file_api_key = str(file_settings.get("openai_api_key", "")).strip()
    file_env_var = str(file_settings.get("openai_api_key_env_var", "")).strip()
    if file_api_key == "" and file_env_var:
        file_api_key = os.getenv(file_env_var, "").strip()

    raw_endpoint = os.getenv("V2_LLM_ENDPOINT", "")
    cleaned_endpoint = raw_endpoint.strip().replace("`", "").strip().strip("'").strip('"').strip()
    cleaned_endpoint = cleaned_endpoint.rstrip(",").strip()
    if "," in cleaned_endpoint and cleaned_endpoint.startswith("http"):
        parts = [part.strip() for part in cleaned_endpoint.split(",") if part.strip() != ""]
        if len(parts) > 0:
            cleaned_endpoint = parts[0]

    return WorkerConfig(
        api_base_url=os.getenv("V2_API_BASE_URL", "http://localhost:8080"),
        api_path_prefix=os.getenv("V2_API_PATH_PREFIX", ""),
        api_token=os.getenv("V2_API_TOKEN", ""),
        api_timeout_seconds=int(os.getenv("V2_API_TIMEOUT_SECONDS", "20")),
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
        llm_endpoint=cleaned_endpoint,
        llm_api_key=os.getenv("V2_LLM_API_KEY", file_api_key),
        llm_model=os.getenv("V2_LLM_MODEL", "gpt-5.4"),
        llm_timeout_seconds=int(os.getenv("V2_LLM_TIMEOUT_SECONDS", "45")),
        llm_temperature=float(os.getenv("V2_LLM_TEMPERATURE", "0.2")),
        llm_max_tokens=int(os.getenv("V2_LLM_MAX_TOKENS", "700")),
        llm_system_prompt=os.getenv(
            "V2_LLM_SYSTEM_PROMPT",
            "Return only a JSON object with keys base_model_id and proposal.",
        ),
        llm_config_file=os.getenv("V2_LLM_CONFIG_FILE", "config/llm_settings.json"),
        llm_prompt_template_file=os.getenv("V2_LLM_PROMPT_TEMPLATE_FILE", "prompts/generate_new_models.txt"),
        llm_fix_error_prompt_file=os.getenv("V2_LLM_FIX_ERROR_PROMPT_FILE", "prompts/fix_model_error.txt"),
        llm_architecture_guide_file=os.getenv("V2_LLM_ARCHITECTURE_GUIDE_FILE", "prompts/instruccions.md"),
        llm_experiment_config_file=os.getenv("V2_LLM_EXPERIMENT_CONFIG_FILE", "configs/experiment_config.json"),
        llm_num_new_models=int(os.getenv("V2_LLM_NUM_NEW_MODELS", "1")),
        llm_num_reference_models=int(os.getenv("V2_LLM_NUM_REFERENCE_MODELS", "3")),
        llm_min_interval_seconds=int(os.getenv("V2_LLM_MIN_INTERVAL_SECONDS", "20")),
        llm_repair_on_validation_error=os.getenv("V2_LLM_REPAIR_ON_VALIDATION_ERROR", "true").lower() in {"1", "true", "yes"},
        verify_legacy_model_build=os.getenv("V2_VERIFY_LEGACY_MODEL_BUILD", "").lower() in {"1", "true", "yes"},
        legacy_build_check_strict=os.getenv("V2_LEGACY_BUILD_CHECK_STRICT", "").lower() in {"1", "true", "yes"},
        legacy_model_json_path=os.getenv("V2_LEGACY_MODEL_JSON_PATH", "models/base/model_exemple_complex_v1.json"),
        legacy_experiment_config_path=os.getenv("V2_LEGACY_EXPERIMENT_CONFIG_PATH", "configs/experiment_config.json"),
        legacy_builder_path=os.getenv("V2_LEGACY_BUILDER_PATH", "shared/utils/model_builder.py"),
    )
