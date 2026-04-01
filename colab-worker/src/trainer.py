import time
import os
import json
import gc
import hashlib
import importlib
import logging
import threading
import traceback
import numpy as np
from pathlib import Path
from typing import Any, Optional, cast

try:
    import resource
except ImportError:
    resource = None

from shared.utils.selection_policy import evaluate_reference_candidate, load_policy_config_from_env

try:
    import tensorflow as tf
    from tensorflow.keras.callbacks import Callback as _ImportedKerasCallback
    KerasCallback = cast(Any, _ImportedKerasCallback)
except ImportError:
    tf = None

    class KerasCallback:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            pass

        model: Any = None

from src.api_client import ApiClient

try:
    from .llm_client import LlmConfig, LlmProposalClient
except ImportError:
    from llm_client import LlmConfig, LlmProposalClient


def _resolve_repo_path(path_str: str, repo_root: Path) -> Path:
    raw = Path(path_str.strip())
    if raw.is_absolute():
        if raw.exists():
            return raw
        normalized = str(raw).replace("\\", "/")
        marker = "/V2/"
        if marker in normalized:
            candidate = Path(normalized.replace(marker, "/", 1))
            if candidate.exists():
                return candidate
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

# A callback that prints out epoch progression visibly and gracefully stops 
# the training if it exceeds a specified max time limit.
class TrainerFeedbackAndLimitCallback(KerasCallback):  # type: ignore[misc]
    def __init__(
        self,
        proposal_id: str,
        max_training_seconds: int = 0,
        api_client: ApiClient | None = None,
        run_id: str = "",
    ):
        super().__init__()
        self.proposal_id = proposal_id
        self.max_training_seconds = max_training_seconds
        self.start_time = 0.0
        self.api = api_client
        self.run_id = run_id
        self.heartbeat_seconds = max(5, int(os.getenv("V2_TRAINING_HEARTBEAT_SECONDS", "30")))
        self.last_heartbeat_ts = 0.0
        self.stopped_by_time_limit = False
        self.stop_reason = ""
        self._current_epoch = 0

    def _emit_event(self, event_type: str, label: str, details: dict[str, Any] | None = None) -> None:
        if self.api is None or self.run_id.strip() == "":
            return
        try:
            self.api.add_event(self.run_id, event_type, label, details or {})
        except Exception:
            return

    def on_train_begin(self, logs=None):
        self.start_time = time.time()
        self.last_heartbeat_ts = self.start_time
        self.stopped_by_time_limit = False
        self.stop_reason = ""
        print(f"\n🚀 Inciant entrenament pesat pel model {self.proposal_id}")
        if self.max_training_seconds > 0:
            print(f"⏱️ Límit establert a: {self.max_training_seconds} segons.")
        self._emit_event(
            "model_training_started",
            f"Entrenament iniciat per {self.proposal_id}",
            {"proposal_id": self.proposal_id, "max_training_seconds": self.max_training_seconds},
        )

    def on_epoch_begin(self, epoch, logs=None):
        self._current_epoch = int(epoch)
        print(f"🔄 Model {self.proposal_id} - Començant època {epoch + 1}...")
        self._emit_event(
            "model_training_epoch_start",
            f"Model {self.proposal_id} · inici època {epoch + 1}",
            {"proposal_id": self.proposal_id, "epoch": int(epoch + 1)},
        )

    def _stop_for_time_limit(self, elapsed: float, epoch: int, batch: int) -> None:
        if self.stopped_by_time_limit:
            return
        self.stopped_by_time_limit = True
        self.stop_reason = "max_training_seconds_exceeded"
        print(
            f"🛑 ATENCIÓ: Temps límit d'entrenament superat en mig d'època "
            f"({elapsed:.1f}s > {self.max_training_seconds}s). S'interromp l'entrenament."
        )
        self._emit_event(
            "model_training_stopped_by_time_limit",
            f"Model {self.proposal_id} aturat per límit de temps",
            {
                "proposal_id": self.proposal_id,
                "elapsed_seconds": round(float(elapsed), 2),
                "max_training_seconds": self.max_training_seconds,
                "epoch": int(epoch + 1),
                "batch": int(batch + 1),
            },
        )
        model = getattr(self, "model", None)
        if model is not None:
            model.stop_training = True

    def on_train_batch_end(self, batch, logs=None):
        now = time.time()
        elapsed = now - self.start_time
        epoch = int(getattr(self, "_current_epoch", 0))
        if self.max_training_seconds > 0 and elapsed > self.max_training_seconds:
            self._stop_for_time_limit(elapsed, epoch, int(batch))
            return
        if now - self.last_heartbeat_ts < self.heartbeat_seconds:
            return
        self.last_heartbeat_ts = now
        params = getattr(self, "params", {}) if isinstance(getattr(self, "params", {}), dict) else {}
        steps = int(params.get("steps", 0) or 0)
        details = {
            "proposal_id": self.proposal_id,
            "epoch": int(epoch + 1),
            "batch": int(batch + 1),
            "steps": steps,
            "elapsed_seconds": round(float(elapsed), 2),
        }
        self._emit_event(
            "model_training_heartbeat",
            f"Model {self.proposal_id} segueix entrenant",
            details,
        )
        if self.api is not None:
            try:
                self.api.update_proposal_status(
                    self.proposal_id,
                    "training",
                    {
                        "last_training_event_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
                        "last_training_heartbeat_elapsed_seconds": round(float(elapsed), 2),
                    },
                )
            except Exception:
                pass

    def on_epoch_end(self, epoch, logs=None):
        elapsed = time.time() - self.start_time
        metrics_str = " | ".join([f"{k}: {v:.4f}" for k, v in (logs or {}).items()])
        print(f"✅ Època {epoch + 1} completada - {metrics_str} - Temps transcòrregut: {elapsed:.1f}s")
        metrics_payload: dict[str, Any] = {}
        for key, value in (logs or {}).items():
            try:
                metrics_payload[str(key)] = float(value)
            except Exception:
                metrics_payload[str(key)] = str(value)
        self._emit_event(
            "model_training_epoch_end",
            f"Model {self.proposal_id} · fi època {epoch + 1}",
            {
                "proposal_id": self.proposal_id,
                "epoch": int(epoch + 1),
                "elapsed_seconds": round(float(elapsed), 2),
                "metrics": metrics_payload,
            },
        )

        if self.max_training_seconds > 0 and elapsed > self.max_training_seconds:
            self._stop_for_time_limit(elapsed, int(epoch), -1)


class TrainingCheckpointCallback(KerasCallback):  # type: ignore[misc]
    def __init__(
        self,
        proposal_id: str,
        run_id: str,
        checkpoint_path: Path,
        api_client: ApiClient,
        every_epochs: int,
        training_config_hash: str,
    ):
        super().__init__()
        self.proposal_id = proposal_id
        self.run_id = run_id
        self.checkpoint_path = checkpoint_path
        self.api = api_client
        self.every_epochs = max(1, every_epochs)
        self.training_config_hash = training_config_hash

    def on_train_begin(self, logs=None):
        try:
            self.api.update_proposal_status(
                self.proposal_id,
                "training",
                {
                    "last_training_event_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
                    "training_config_hash": self.training_config_hash,
                },
            )
        except Exception:
            return

    def on_epoch_end(self, epoch, logs=None):
        current_epoch = int(epoch + 1)
        try:
            self.api.update_proposal_status(
                self.proposal_id,
                "training",
                {
                    "last_epoch_completed": current_epoch,
                    "last_training_event_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
                    "resumable": True,
                    "training_config_hash": self.training_config_hash,
                },
            )
        except Exception:
            return
        if current_epoch % self.every_epochs != 0:
            return
        model = getattr(self, "model", None)
        if model is None:
            return
        try:
            model.save_weights(str(self.checkpoint_path))
            artifact = self.api.upload_artifact_file(
                self.run_id,
                artifact_type="checkpoint",
                file_path=str(self.checkpoint_path),
                metadata={
                    "proposal_id": self.proposal_id,
                    "epoch": current_epoch,
                    "checkpoint_uri": str(self.checkpoint_path),
                    "training_config_hash": self.training_config_hash,
                },
            )
            artifact_metadata = artifact.get("metadata", {}) if isinstance(artifact, dict) and isinstance(artifact.get("metadata"), dict) else {}
            self.api.update_proposal_status(
                self.proposal_id,
                "training",
                {
                    "last_epoch_completed": current_epoch,
                    "last_checkpoint_artifact_id": artifact_metadata.get("artifact_id"),
                    "last_checkpoint_epoch": current_epoch,
                    "last_checkpoint_local_path": str(self.checkpoint_path),
                    "resume_checkpoint_uri": artifact_metadata.get("artifact_id"),
                    "last_checkpoint_saved_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
                    "resumable": True,
                    "training_config_hash": self.training_config_hash,
                },
            )
            self.api.add_event(
                self.run_id,
                "training_checkpoint_saved",
                f"Checkpoint guardat per {self.proposal_id} a l'època {current_epoch}",
                {
                    "proposal_id": self.proposal_id,
                    "epoch": current_epoch,
                    "checkpoint_artifact_id": artifact_metadata.get("artifact_id"),
                },
            )
        except Exception:
            return

class ModelTrainerEngine:
    def __init__(self, api_client: ApiClient, config: dict[str, Any]):
        self.api = api_client
        self.trainer_id = "colab_trainer_" + str(int(time.time()))
        self.repo_root = Path(__file__).resolve().parents[2]
        
        # We need the old V1 builder / evaluator helpers
        import sys
        if str(self.repo_root) not in sys.path:
            sys.path.insert(0, str(self.repo_root))
            
        self.config = config
        self.max_seconds_per_model = int(config.get("max_training_seconds", 0))
        self.max_epochs_per_model = max(0, int(config.get("max_epochs", 0)))
        self.execution_request_id = str(config.get("execution_request_id", "")).strip()
        self.selection_policy_config = load_policy_config_from_env()
        self.champion_scope = os.getenv("V2_CHAMPION_SCOPE", "run").strip().lower()
        if self.champion_scope not in {"run", "global"}:
            self.champion_scope = "run"
        self.checkpoint_every_epochs = max(1, int(os.getenv("V2_CHECKPOINT_EVERY_EPOCHS", "1")))
        self.resume_enabled = os.getenv("V2_RESUME_ENABLED", "true").lower() in {"1", "true", "yes"}
        self.max_resume_attempts = max(0, int(os.getenv("V2_MAX_RESUME_ATTEMPTS", "2")))
        self._experiment_config_cache: dict[str, Any] | None = None
        self._all_data_cache: dict[str, Any] | None = None
        self._legacy_utils_cache: tuple[Any, Any, Any, Any, Any] | None = None
        self._data_cache_lock = threading.Lock()
        self._data_prewarm_started = False
        self._data_prewarm_completed = False
        self._split_indices_cache: tuple[Any, Any, Any] | None = None
        self._scaled_input_cache: dict[str, tuple[Any, Any, Any]] = {}
        self.llm = LlmProposalClient(
            LlmConfig(
                enabled=os.getenv("V2_LLM_ENABLED", "false").lower() in {"1", "true", "yes"},
                use_legacy_interface=os.getenv("V2_LLM_USE_LEGACY_INTERFACE", "true").lower() in {"1", "true", "yes"},
                provider=os.getenv("V2_LLM_PROVIDER", "mock"),
                endpoint=os.getenv("V2_LLM_ENDPOINT", ""),
                api_key=os.getenv("V2_LLM_API_KEY", ""),
                model=os.getenv("V2_LLM_MODEL", "gpt-5.4"),
                fallback_provider=os.getenv("V2_LLM_FALLBACK_PROVIDER", ""),
                fallback_endpoint=os.getenv("V2_LLM_FALLBACK_ENDPOINT", ""),
                fallback_api_key=os.getenv("V2_LLM_FALLBACK_API_KEY", os.getenv("GEMINI_API_KEY", "")),
                fallback_model=os.getenv("V2_LLM_FALLBACK_MODEL", "gemini-3-flash-preview"),
                timeout_seconds=int(os.getenv("V2_LLM_TIMEOUT_SECONDS", "90")),
                temperature=float(os.getenv("V2_LLM_TEMPERATURE", "0.2")),
                max_tokens=int(os.getenv("V2_LLM_MAX_TOKENS", "6000")),
                system_prompt=os.getenv("V2_LLM_SYSTEM_PROMPT", "Return only a JSON object with keys base_model_id and proposal."),
                prompt_template_file=os.getenv("V2_LLM_PROMPT_TEMPLATE_FILE", "prompts/generate_new_models.txt"),
                fix_error_prompt_file=os.getenv("V2_LLM_FIX_ERROR_PROMPT_FILE", "prompts/fix_model_error.txt"),
                architecture_guide_file=os.getenv("V2_LLM_ARCHITECTURE_GUIDE_FILE", "prompts/instruccions.md"),
                experiment_config_file=os.getenv("V2_LLM_EXPERIMENT_CONFIG_FILE", "configs/experiment_config.json"),
                num_new_models=int(os.getenv("V2_LLM_NUM_NEW_MODELS", "1")),
                num_reference_models=int(os.getenv("V2_LLM_NUM_REFERENCE_MODELS", "3")),
                repair_on_validation_error=os.getenv("V2_LLM_REPAIR_ON_VALIDATION_ERROR", "true").lower() in {"1", "true", "yes"},
            )
        )

    def _load_legacy_training_utils(self) -> tuple[Any, Any, Any, Any, Any]:
        if self._legacy_utils_cache is not None:
            return cast(tuple[Any, Any, Any, Any, Any], self._legacy_utils_cache)
        try:
            from shared.utils.data_loading_utils import load_all_raw_data_sources, derive_additional_features_and_targets
            from shared.utils.data_preparation_utils import prepare_model_specific_inputs_outputs, split_and_scale_data
            from shared.utils.model_builder import build_model_from_json_definition
        except ModuleNotFoundError:
            data_loading_utils = importlib.import_module("utils.data_loading_utils")
            data_preparation_utils = importlib.import_module("utils.data_preparation_utils")
            model_builder_module = importlib.import_module("utils.model_builder")
            load_all_raw_data_sources = data_loading_utils.load_all_raw_data_sources
            derive_additional_features_and_targets = data_loading_utils.derive_additional_features_and_targets
            prepare_model_specific_inputs_outputs = data_preparation_utils.prepare_model_specific_inputs_outputs
            split_and_scale_data = data_preparation_utils.split_and_scale_data
            build_model_from_json_definition = model_builder_module.build_model_from_json_definition
        self._legacy_utils_cache = cast(tuple[Any, Any, Any, Any, Any], (
            load_all_raw_data_sources,
            derive_additional_features_and_targets,
            prepare_model_specific_inputs_outputs,
            split_and_scale_data,
            build_model_from_json_definition,
        ))
        return cast(tuple[Any, Any, Any, Any, Any], self._legacy_utils_cache)

    def _load_training_data_context(self) -> tuple[dict[str, Any], dict[str, Any]]:
        with self._data_cache_lock:
            if self._experiment_config_cache is not None and self._all_data_cache is not None:
                return self._experiment_config_cache, self._all_data_cache

            (
                load_all_raw_data_sources,
                derive_additional_features_and_targets,
                _prepare_model_specific_inputs_outputs,
                _split_and_scale_data,
                _build_model_from_json_definition,
            ) = self._load_legacy_training_utils()

            print("📊 Carregant el fitxer de configuració de l'experiment (cache warmup)...")
            experiment_path = Path(
                os.getenv(
                    "V2_LEGACY_EXPERIMENT_CONFIG_PATH",
                    str(self.repo_root / "configs" / "experiment_config.json"),
                )
            )
            experiment_path = _resolve_repo_path(str(experiment_path), self.repo_root)
            with open(experiment_path, "r", encoding="utf-8") as f:
                exp_config = json.load(f)

            base_data_dir = self.repo_root / exp_config.get("data_dir", "data")
            input_cfg = exp_config.get("input_features_config", [])
            output_cfg = exp_config.get("output_targets_config", [])

            print("🔨 Carregant dades font només una vegada per la sessió del trainer...")
            raw_sources = load_all_raw_data_sources(
                exp_config.get("data_paths", {}),
                input_cfg,
                output_cfg,
                base_data_dir=str(base_data_dir),
            )
            all_data = derive_additional_features_and_targets(raw_sources, input_cfg, output_cfg)
            self._experiment_config_cache = exp_config
            self._all_data_cache = all_data
            
            # Step 2: Global pre-scaling after loading data
            try:
                print("⚖️ Iniciant pre-escalat global de dades per a tots els inputs i targets...")
                self._prewarm_all_scaled_data(exp_config, all_data)
                print("✅ Pre-escalat global completat.")
            except Exception as pe:
                print(f"⚠️ Error durant el pre-escalat global: {pe}")

            self._data_prewarm_completed = True
            return exp_config, all_data

    def _prewarm_all_scaled_data(self, exp_config: dict[str, Any], all_data: dict[str, Any]) -> None:
        (
            _, _, _, split_and_scale_data, _
        ) = self._load_legacy_training_utils()
        
        # We need sample count to get split indices
        first_key = next(iter(all_data)) if all_data else None
        if not first_key:
            return
        n_samples = all_data[first_key].shape[0]
        
        # Use a dummy model def to get a stable seed from experiment config
        dummy_model_def = {"training_config": {"seed": exp_config.get("global_seed", 42)}}
        split_indices = self._get_or_build_split_indices(n_samples, exp_config, dummy_model_def)
        
        # 1. Warm up input features
        input_cfg = exp_config.get("input_features_config", [])
        for feat in input_cfg:
            name = feat.get("feature_name")
            if not name or name not in all_data:
                continue
            # We treat each feature as a single input to warm up the cache
            arr = all_data[name]
            if arr.size == 0:
                continue
            
            # Use feature_name as cache key prefix
            cache_key = f"{name}:global"
            if cache_key in self._scaled_input_cache:
                continue
                
            split_and_scale_data(
                [arr], [np.zeros((n_samples, 1), dtype=np.float32)], 
                ["input"], exp_config, dummy_model_def,
                split_indices=split_indices,
                scaled_input_cache=self._scaled_input_cache,
                input_cache_keys=[cache_key]
            )

        # 2. Warm up output targets (optional but useful if they are many)
        output_cfg = exp_config.get("output_targets_config", [])
        for target in output_cfg:
            name = target.get("target_name")
            if not name or name not in all_data:
                continue
            arr = all_data[name]
            if arr.size == 0:
                continue
            
            cache_key = f"{name}:global"
            if cache_key in self._scaled_input_cache:
                continue
                
            # For targets we might not need scaling in some models, 
            # but pre-scaling them doesn't hurt if we use the same cache mechanism
            split_and_scale_data(
                [arr], [np.zeros((n_samples, 1), dtype=np.float32)], 
                ["target"], exp_config, dummy_model_def,
                split_indices=split_indices,
                scaled_input_cache=self._scaled_input_cache,
                input_cache_keys=[cache_key]
            )

    def _start_background_data_prewarm(self) -> None:
        if self._data_prewarm_started:
            return
        self._data_prewarm_started = True

        def _runner() -> None:
            try:
                print("🧠 Precarregant dades d'entrenament en segon pla mentre arriben propostes LLM...")
                self._load_training_data_context()
                print("✅ Cache de dades d'entrenament preparada.")
            except Exception as error:
                self._data_prewarm_started = False
                print(f"⚠️ No s'ha pogut precarregar la cache de dades: {error}")

        threading.Thread(target=_runner, daemon=True, name="trainer-data-prewarm").start()

    def _release_training_memory(self, *objects: Any) -> None:
        for obj in objects:
            if isinstance(obj, list):
                obj.clear()
            elif isinstance(obj, dict):
                obj.clear()
        if tf is not None:
            try:
                tf.keras.backend.clear_session()
            except Exception:
                pass
        gc.collect()

    def _get_or_build_split_indices(self, n_samples: int, experiment_config: dict[str, Any], model_json_definition: dict[str, Any]) -> tuple[Any, Any, Any]:
        if self._split_indices_cache is not None:
            return self._split_indices_cache
        try:
            import numpy as np
            from sklearn.model_selection import train_test_split
        except Exception as error:
            raise RuntimeError(f"Missing numpy/sklearn for split indices: {error}") from error

        eval_params = experiment_config.get("evaluator_params", {}) if isinstance(experiment_config, dict) else {}
        val_split = float(eval_params.get("validation_split", 0.15))
        test_split = float(eval_params.get("test_split", 0.10))
        seed = int(model_json_definition.get("training_config", {}).get("seed", experiment_config.get("global_seed", 42)))
        indices = np.arange(n_samples)
        train_val_idx, test_idx = train_test_split(indices, test_size=test_split, random_state=seed, shuffle=True)
        if val_split > 0 and len(train_val_idx) >= 2:
            effective_val = val_split / max(1e-6, (1.0 - test_split))
            effective_val = min(max(effective_val, 0.0), 0.9)
            train_idx, val_idx = train_test_split(train_val_idx, test_size=effective_val, random_state=seed, shuffle=True)
        else:
            train_idx = train_val_idx
            val_idx = np.array([], dtype=int)
        self._split_indices_cache = (train_idx, val_idx, test_idx)
        print(f"🧮 Split indices cachejats: train={len(train_idx)} val={len(val_idx)} test={len(test_idx)}")
        return self._split_indices_cache

    def _resolve_input_cache_keys(self, all_data: dict[str, Any], model_definition: dict[str, Any]) -> list[str]:
        keys: list[str] = []
        architecture_raw = model_definition.get("architecture_definition")
        architecture = architecture_raw if isinstance(architecture_raw, dict) else {}
        for input_conf in architecture.get("used_inputs", []) if isinstance(architecture.get("used_inputs"), list) else []:
            if not isinstance(input_conf, dict):
                continue
            source_feature_name = str(input_conf.get("source_feature_name", "")).strip()
            input_layer_name = str(input_conf.get("input_layer_name", "")).strip()
            if source_feature_name == "" or input_layer_name == "":
                continue
            arr = all_data.get(source_feature_name)
            if arr is None or getattr(arr, "size", 0) == 0:
                continue
            keys.append(f"{source_feature_name}:global")
        return keys

    def _runtime_training_limits(self) -> tuple[int, int]:
        max_epochs = self.max_epochs_per_model
        max_training_seconds = self.max_seconds_per_model
        if self.execution_request_id == "":
            return max_epochs, max_training_seconds
        try:
            request = self.api.get_execution_request(self.execution_request_id)
            raw_config = request.get("config")
            config = raw_config if isinstance(raw_config, dict) else {}
            max_epochs = max(0, int(config.get("max_epochs", max_epochs) or 0))
            max_training_seconds = max(0, int(config.get("max_training_seconds", max_training_seconds) or 0))
        except Exception:
            return max_epochs, max_training_seconds
        return max_epochs, max_training_seconds

    def _attempt_repair_failed_proposal(self, proposal: dict[str, Any], run_id: str, error_message: str) -> bool:
        if not self.llm.config.enabled:
            return False
        llm_metadata_raw = proposal.get("llm_metadata")
        llm_metadata = llm_metadata_raw if isinstance(llm_metadata_raw, dict) else {}
        repair_depth = int(llm_metadata.get("repair_depth", 0) or 0)
        if repair_depth >= 1:
            return False
        lowered = error_message.lower()
        non_repairable_markers = [
            "cuda",
            "cudnn",
            "out of memory",
            "oom",
            "resource exhausted",
            "no module named",
            "permission denied",
            "file not found",
            "404 client error",
            "401 client error",
            "403 client error",
            "429 client error",
            "rate limit",
            "keyboardinterrupt",
            "connection aborted",
            "connection refused",
            "name resolution",
        ]
        if any(marker in lowered for marker in non_repairable_markers):
            return False

        candidate_payload = proposal.get("proposal") if isinstance(proposal.get("proposal"), dict) else {}
        original_candidate = {
            "base_model_id": str(proposal.get("base_model_id", "")).strip() or "repair_base_model",
            "proposal": candidate_payload,
            "llm_metadata": llm_metadata,
        }
        context = {
            "generation": int(llm_metadata.get("from_generation", 0) or 0),
            "run_id": run_id,
            "code_version": os.getenv("V2_CODE_VERSION", ""),
            "reference_models": [],
            "reference_selection_trace": {},
            "latest_metrics": {},
        }
        references, selection_trace = self._collect_reference_models_for_prompt(run_id)
        context["reference_models"] = references
        context["reference_selection_trace"] = selection_trace

        try:
            self.api.add_event(
                run_id,
                "model_repair_started",
                f"Intentant reparar {proposal.get('proposal_id', '')}",
                {
                    "proposal_id": proposal.get("proposal_id"),
                    "error": error_message,
                    "reference_models_count": len(references),
                },
            )
        except Exception:
            pass
        print(f"🩹 Intentant reparar o reemplaçar {proposal.get('proposal_id', '')} després de l'error: {error_message}")

        for attempt in range(4):
            candidate_to_submit: dict[str, Any] | None = None
            mode = "repair"
            if attempt == 0:
                try:
                    candidate_to_submit = self.llm._repair_candidate_after_validation_error(original_candidate, error_message, context)
                    print(f"🔧 Resposta de repair rebuda per {proposal.get('proposal_id', '')} (intent {attempt + 1})")
                except Exception as repair_error:
                    print(f"❌ Repair LLM fallida per {proposal.get('proposal_id', '')} (intent {attempt + 1}): {repair_error}")
                    self.api.add_event(run_id, "model_repair_failed", f"Repair LLM fallida per {proposal.get('proposal_id', '')}", {"error": str(repair_error), "attempt": attempt + 1})
            else:
                mode = "replacement"
                try:
                    candidate_to_submit = self.llm.generate_candidate(context)
                    print(f"🆕 Reemplaç generat per {proposal.get('proposal_id', '')} (intent {attempt + 1})")
                except Exception as replacement_error:
                    print(f"❌ Generació reemplaçament fallida per {proposal.get('proposal_id', '')} (intent {attempt + 1}): {replacement_error}")
                    self.api.add_event(run_id, "model_repair_failed", f"Generació reemplaçament fallida per {proposal.get('proposal_id', '')}", {"error": str(replacement_error), "attempt": attempt + 1})

            if not isinstance(candidate_to_submit, dict):
                continue
            submitted_id = self._submit_repaired_candidate(run_id, proposal, candidate_to_submit, error_message, repair_depth, mode, attempt + 1)
            if submitted_id is not None:
                return True

        try:
            self.api.add_event(
                run_id,
                "model_repair_exhausted",
                f"No s'ha pogut reparar ni reemplaçar {proposal.get('proposal_id', '')}",
                {"proposal_id": proposal.get("proposal_id"), "error": error_message},
            )
        except Exception:
            pass
        return False

    def _collect_reference_models_for_prompt(self, run_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        max_refs = max(0, int(os.getenv("V2_LLM_NUM_REFERENCE_MODELS", "3")))
        if max_refs <= 0:
            return [], {"selected": [], "rejected": [], "fallback_used": False}
        references: list[dict[str, Any]] = []
        selected_trace: list[dict[str, Any]] = []
        rejected_trace: list[dict[str, Any]] = []
        try:
            proposals = self.api.list_model_proposals(limit=300)
            ranked: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
            for candidate in proposals:
                payload = candidate.get("proposal")
                if not isinstance(payload, dict):
                    continue
                model_definition = payload.get("model_definition")
                if not isinstance(model_definition, dict):
                    continue
                decision = evaluate_reference_candidate(candidate, config=self.selection_policy_config)
                if not bool(decision.get("eligible")):
                    rejected_trace.append({
                        "proposal_id": str(candidate.get("proposal_id", "")),
                        "status": str(candidate.get("status", "")),
                        "selection_reason": str(decision.get("selection_reason", "")),
                        "score": decision.get("score"),
                    })
                    continue
                score = float(decision.get("score", 0.0))
                reference = dict(model_definition)
                reference["model_id"] = str(model_definition.get("model_id", candidate.get("proposal_id", "unknown_model")))
                ranked.append((score, reference, decision))
            ranked.sort(key=lambda item: item[0], reverse=True)
            top = ranked[:max_refs]
            references = [item[1] for item in top]
            selected_trace = [{
                "proposal_id": str(item[2].get("proposal_id", "")),
                "score": item[2].get("score"),
                "selection_reason": item[2].get("selection_reason", ""),
            } for item in top]
        except Exception:
            references = []
        return references, {
            "policy_version": str(self.selection_policy_config.get("policy_version", "selection_policy_v1")),
            "selected": selected_trace,
            "rejected": rejected_trace[:10],
            "fallback_used": len(references) == 0,
        }

    def _submit_repaired_candidate(
        self,
        run_id: str,
        proposal: dict[str, Any],
        candidate: dict[str, Any],
        error_message: str,
        repair_depth: int,
        mode: str,
        attempt_number: int,
    ) -> str | None:
        repaired_proposal = candidate.get("proposal") if isinstance(candidate.get("proposal"), dict) else {}
        if not repaired_proposal:
            return None
        repaired_metadata_raw = candidate.get("llm_metadata")
        repaired_metadata = repaired_metadata_raw if isinstance(repaired_metadata_raw, dict) else {}
        repaired_metadata["repair_depth"] = repair_depth + 1
        repaired_metadata["repaired_from_proposal_id"] = str(proposal.get("proposal_id", ""))
        repaired_metadata["repair_source_error"] = error_message
        repaired_metadata["repair_mode"] = mode
        repaired_metadata["repair_attempt"] = attempt_number
        created = self.api.create_model_proposal(
            source_run_id=run_id,
            base_model_id=str(candidate.get("base_model_id", proposal.get("base_model_id", "repair_base_model"))),
            proposal=repaired_proposal,
            llm_metadata=repaired_metadata,
        )
        repaired_id = str(created.get("proposal_id", ""))
        if repaired_id == "":
            return None
        print(f"🧾 Proposal reparada/reemplaç creada: {repaired_id} (mode={mode}, intent={attempt_number})")
        self.api.enqueue_model_proposal_phase0(repaired_id)
        try:
            self.api.process_model_proposals_phase0(limit=5)
        except Exception:
            pass
        refreshed = self.api.get_model_proposal(repaired_id)
        refreshed_status = str(refreshed.get("status", ""))
        if refreshed_status == "validated_phase0":
            print(f"✅ Proposal {repaired_id} validada a phase0 i reenviada a la cua")
            try:
                self.api.update_proposal_status(
                    str(proposal.get("proposal_id", "")),
                    str(proposal.get("status", "rejected")),
                    {
                        "repair_replacement_proposal_id": repaired_id,
                        "repair_last_mode": mode,
                        "repair_last_attempt": attempt_number,
                    },
                )
            except Exception:
                pass
            self.api.add_event(
                run_id,
                "model_repair_enqueued",
                f"Proposal reparada i reenviada a phase0: {repaired_id}",
                {"original_proposal_id": proposal.get("proposal_id"), "repaired_proposal_id": repaired_id, "mode": mode, "attempt": attempt_number},
            )
            return repaired_id
        self.api.add_event(
            run_id,
            "model_repair_failed",
            f"Proposal reparada rebutjada a phase0: {repaired_id}",
            {"original_proposal_id": proposal.get("proposal_id"), "repaired_proposal_id": repaired_id, "status": refreshed_status, "mode": mode, "attempt": attempt_number},
        )
        print(f"⚠️ Proposal {repaired_id} rebutjada a phase0 després del {mode} (status={refreshed_status})")
        return None

    def _current_memory_mb(self) -> float | None:
        if resource is None:
            return None
        try:
            getrusage = getattr(resource, "getrusage", None)
            rusage_self = getattr(resource, "RUSAGE_SELF", None)
            if getrusage is None or rusage_self is None:
                return None
            usage = getrusage(rusage_self).ru_maxrss
            if usage <= 0:
                return None
            if os.name == "posix":
                return round(float(usage) / 1024.0, 2)
            return round(float(usage) / (1024.0 * 1024.0), 2)
        except Exception:
            return None

    def _training_config_hash(self, model_def: dict[str, Any]) -> str:
        training_cfg = model_def.get("training_config", {}) if isinstance(model_def.get("training_config", {}), dict) else {}
        payload = json.dumps(training_cfg, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _checkpoint_dir_for_proposal(self, proposal_id: str) -> Path:
        checkpoint_dir = Path(
            os.getenv(
                "V2_MODEL_CHECKPOINTS_DIR",
                str(self.repo_root / "colab-worker" / "checkpoints" / "model_checkpoints" / proposal_id),
            )
        )
        if not checkpoint_dir.is_absolute():
            checkpoint_dir = (self.repo_root / checkpoint_dir).resolve()
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        return checkpoint_dir

    def _resolve_resume_state(self, proposal: dict[str, Any], model_def: dict[str, Any]) -> dict[str, Any]:
        llm_metadata_raw = proposal.get("llm_metadata")
        llm_metadata: dict[str, Any] = llm_metadata_raw if isinstance(llm_metadata_raw, dict) else {}
        training_hash = self._training_config_hash(model_def)
        checkpoint_artifact_id = str(llm_metadata.get("last_checkpoint_artifact_id", "")).strip()
        checkpoint_epoch = int(llm_metadata.get("last_checkpoint_epoch", 0) or 0)
        checkpoint_path = str(llm_metadata.get("last_checkpoint_local_path", "")).strip()
        resumable = bool(llm_metadata.get("resumable", False))
        resume_attempts = int(llm_metadata.get("resume_attempts", 0) or 0)
        stored_hash = str(llm_metadata.get("training_config_hash", "")).strip()
        config_match = stored_hash == "" or stored_hash == training_hash
        checkpoint_exists = checkpoint_path != "" and Path(checkpoint_path).is_file()
        can_resume = self.resume_enabled and resumable and checkpoint_artifact_id != "" and checkpoint_epoch > 0 and checkpoint_exists and config_match and resume_attempts < self.max_resume_attempts
        return {
            "training_config_hash": training_hash,
            "checkpoint_artifact_id": checkpoint_artifact_id,
            "checkpoint_epoch": checkpoint_epoch,
            "checkpoint_local_path": checkpoint_path,
            "resume_attempts": resume_attempts,
            "config_match": config_match,
            "checkpoint_exists": checkpoint_exists,
            "resume_enabled": self.resume_enabled,
            "can_resume": can_resume,
        }

    def run_loop(self):
        print(f"🟢 [Trainer Worker: {self.trainer_id}] Mantenint cerca de models acceptats...")
        self._start_background_data_prewarm()
        while True:
            try:
                proposal = self.api.lock_accepted_proposal_for_training(self.trainer_id)
                if not proposal:
                    self._auto_promote_validated_phase0_if_needed()
                    time.sleep(10)
                    continue

                proposal_id = str(proposal.get("proposal_id", ""))
                print(f"\n==============================================")
                print(f"🎯 S'ha tancat i assignat el model {proposal_id} per a entrenament.")
                print(f"==============================================")

                self._train_proposal(proposal)

            except Exception as e:
                print(f"❌ Error en el loop d'entrenament global: {e}")
                time.sleep(15)

    def _auto_promote_validated_phase0_if_needed(self) -> None:
        try:
            proposals = self.api.list_model_proposals(limit=300)
        except Exception:
            return

        candidates = [
            p for p in proposals
            if isinstance(p, dict) and str(p.get("status", "")).strip() == "validated_phase0"
        ]
        if len(candidates) == 0:
            return

        candidates.sort(key=lambda item: str(item.get("updated_at", "")))
        selected = candidates[0]
        proposal_id = str(selected.get("proposal_id", "")).strip()
        if proposal_id == "":
            return

        try:
            self.api.update_proposal_status(
                proposal_id,
                "accepted",
                {
                    "auto_promoted_for_training": True,
                    "auto_promoted_by": self.trainer_id,
                },
            )
            run_id = str(selected.get("source_run_id", "")).strip()
            if run_id != "":
                self.api.add_event(
                    run_id,
                    "proposal_auto_promoted_for_training",
                    f"Proposta {proposal_id} promoguda automàticament a accepted",
                    {"proposal_id": proposal_id, "trainer_id": self.trainer_id},
                )
            print(f"⚙️ Auto-promoció: {proposal_id} -> accepted")
        except Exception:
            return

    def _train_proposal(self, proposal: dict[str, Any]):
        proposal_id = str(proposal.get("proposal_id", ""))
        run_id = str(proposal.get("source_run_id", ""))
        keras_model = None
        history = None
        training_succeeded = False
        model_training_metrics: dict[str, Any] = {}
        pipeline_started_at = time.time()
        X_train: list[Any] = []
        Y_train: list[Any] = []
        X_val: list[Any] = []
        Y_val: list[Any] = []
        X_test: list[Any] = []
        Y_test: list[Any] = []
        scalers: dict[str, Any] = {}
        
        try:
            # 1. Obtenir definició d'arquitectura
            model_def = proposal.get("proposal", {}).get("model_definition", {})
            if not model_def:
                raise RuntimeError("El payload no conté `model_definition`.")
            active_max_epochs, active_max_training_seconds = self._runtime_training_limits()

            training_config_raw = model_def.get("training_config")
            training_config = training_config_raw if isinstance(training_config_raw, dict) else {}
            model_def["training_config"] = training_config
            fit_config_raw = training_config.get("fit")
            fit_config = fit_config_raw if isinstance(fit_config_raw, dict) else {}
            training_config["fit"] = fit_config
            original_epochs = int(fit_config.get("epochs", 15) or 15)
            if active_max_epochs > 0:
                fit_config["epochs"] = active_max_epochs
            effective_epochs = int(fit_config.get("epochs", 15) or 15)

            model_def["model_id"] = proposal_id
            resume_state = self._resolve_resume_state(proposal, model_def)
            memory_before_data_prep_mb = self._current_memory_mb()

            (
                _load_all_raw_data_sources,
                _derive_additional_features_and_targets,
                prepare_model_specific_inputs_outputs,
                split_and_scale_data,
                build_model_from_json_definition,
            ) = self._load_legacy_training_utils()
            exp_config, all_data = self._load_training_data_context()

            # Necessari per reomplir els arrays "runtime" esperats pel V1 format
            input_cfg = exp_config.get("input_features_config", [])
            output_cfg = exp_config.get("output_targets_config", [])
            model_def["input_features_config_runtime"] = input_cfg
            model_def["output_targets_config_runtime"] = output_cfg

            print("🔨 Preparant tensors específics del model a partir de dades cachejades...")
            data_prep_started_at = time.time()
            print(f"📐 Inici prepare_model_specific_inputs_outputs per {proposal_id}")
            X_list, Y_list, in_names, out_names = prepare_model_specific_inputs_outputs(all_data, model_def)
            prepare_inputs_seconds = round(time.time() - data_prep_started_at, 3)
            print(f"✅ prepare_model_specific_inputs_outputs complet per {proposal_id} en {prepare_inputs_seconds}s")
            split_started_at = time.time()
            print(f"⚖️ Inici split_and_scale_data per {proposal_id}")
            split_indices = self._get_or_build_split_indices(X_list[0].shape[0], exp_config, model_def) if X_list else None
            input_cache_keys = self._resolve_input_cache_keys(all_data, model_def)
            (X_train, Y_train), (X_val, Y_val), (X_test, Y_test), scalers = split_and_scale_data(
                X_list,
                Y_list,
                in_names,
                exp_config,
                model_def,
                split_indices=split_indices,
                scaled_input_cache=self._scaled_input_cache,
                input_cache_keys=input_cache_keys,
            )
            split_and_scale_seconds = round(time.time() - split_started_at, 3)
            print(f"✅ split_and_scale_data complet per {proposal_id} en {split_and_scale_seconds}s")
            data_prep_seconds = round(time.time() - data_prep_started_at, 3)
            del X_list, Y_list, in_names, out_names, X_test, Y_test, scalers
            X_test = []
            Y_test = []
            scalers = {}
            memory_after_data_prep_mb = self._current_memory_mb()

            print("🏗️ Construint el graf Keras del model...")
            model_build_started_at = time.time()
            keras_model = build_model_from_json_definition(model_def)
            model_build_seconds = round(time.time() - model_build_started_at, 3)
            memory_after_model_build_mb = self._current_memory_mb()
            checkpoint_dir = self._checkpoint_dir_for_proposal(proposal_id)
            checkpoint_path = checkpoint_dir / f"{proposal_id}.weights.h5"
            
            # Parametrització temporal o definitiva?
            epochs = effective_epochs
            batch_sz = model_def.get("training_config", {}).get("fit", {}).get("batch_size", 64)
            
            # Protecció contra èpoques excessives si cal fer testing ràpid
            feedback_callback = TrainerFeedbackAndLimitCallback(
                proposal_id,
                active_max_training_seconds,
                api_client=self.api,
                run_id=run_id,
            )
            callbacks = [
                feedback_callback,
                TrainingCheckpointCallback(
                    proposal_id=proposal_id,
                    run_id=run_id,
                    checkpoint_path=checkpoint_path,
                    api_client=self.api,
                    every_epochs=self.checkpoint_every_epochs,
                    training_config_hash=resume_state["training_config_hash"],
                ),
            ]

            initial_epoch = 0
            resumed_from_checkpoint = False
            resume_checkpoint_uri = ""
            if resume_state["can_resume"]:
                try:
                    keras_model.load_weights(str(resume_state["checkpoint_local_path"]))
                    initial_epoch = int(resume_state["checkpoint_epoch"])
                    resumed_from_checkpoint = True
                    resume_checkpoint_uri = str(resume_state["checkpoint_artifact_id"])
                    self.api.update_proposal_status(
                        proposal_id,
                        "training",
                        {
                            "resume_attempts": int(resume_state["resume_attempts"]) + 1,
                            "resumed_from_checkpoint": True,
                            "resume_checkpoint_uri": resume_checkpoint_uri,
                            "training_config_hash": resume_state["training_config_hash"],
                        },
                    )
                    self.api.add_event(
                        run_id,
                        "training_resumed",
                        f"Entrenament reprès per {proposal_id}",
                        {
                            "proposal_id": proposal_id,
                            "checkpoint_artifact_id": resume_checkpoint_uri,
                            "last_epoch_completed": int(resume_state["checkpoint_epoch"]),
                            "initial_epoch": initial_epoch,
                        },
                    )
                except Exception as resume_error:
                    self.api.add_event(
                        run_id,
                        "training_resume_failed",
                        f"No s'ha pogut reprendre {proposal_id}",
                        {"proposal_id": proposal_id, "error": str(resume_error)},
                    )
                    resumed_from_checkpoint = False
                    initial_epoch = 0
            elif str(proposal.get("status", "")) == "accepted":
                llm_metadata_raw = proposal.get("llm_metadata")
                llm_metadata: dict[str, Any] = llm_metadata_raw if isinstance(llm_metadata_raw, dict) else {}
                if bool(llm_metadata.get("resumable", False)) and not bool(resume_state["config_match"]):
                    self.api.add_event(
                        run_id,
                        "training_resume_blocked_config_mismatch",
                        f"Resume bloquejat per config mismatch a {proposal_id}",
                        {
                            "proposal_id": proposal_id,
                            "stored_training_config_hash": llm_metadata.get("training_config_hash"),
                            "current_training_config_hash": resume_state["training_config_hash"],
                        },
                    )
                if bool(llm_metadata.get("resumable", False)):
                    self.api.add_event(
                        run_id,
                        "training_restarted_from_scratch",
                        f"Entrenament reiniciat des de zero per {proposal_id}",
                        {
                            "proposal_id": proposal_id,
                            "reason": "checkpoint_unavailable_or_incompatible",
                        },
                    )

            self.api.update_proposal_status(
                proposal_id,
                "training",
                {
                    "training_started_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
                    "training_interrupted_at": None,
                    "last_training_event_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
                    "resumed_from_checkpoint": resumed_from_checkpoint,
                    "resume_checkpoint_uri": resume_checkpoint_uri,
                    "training_config_hash": resume_state["training_config_hash"],
                    "resume_attempts": int(resume_state["resume_attempts"]) + (1 if resumed_from_checkpoint else 0),
                },
            )
            print(f"🔥 Training iniciat per {proposal_id} (epochs={epochs}, max_seconds={active_max_training_seconds})")
            
            print(f"🔥 Donant inici al mètode keras_model.fit() per un màxim de {epochs} èpoques.")
            start_t = time.time()
            history = keras_model.fit(
                X_train, Y_train,
                validation_data=(X_val, Y_val) if X_val else None,
                epochs=epochs,
                initial_epoch=initial_epoch,
                batch_size=batch_sz,
                verbose=0,  # Apaguem el verbose per defecte i treballem amb el de la consola 
                callbacks=cast(Any, callbacks)
            )
            elapsed = time.time() - start_t

            if bool(getattr(feedback_callback, "stopped_by_time_limit", False)):
                raise TimeoutError(
                    f"model {proposal_id} exceeded max training time "
                    f"({active_max_training_seconds}s) during fit"
                )

            total_epochs_trained = len(history.history['loss']) if 'loss' in history.history else 0
            completed_epoch = initial_epoch + total_epochs_trained
            keras_model.save_weights(str(checkpoint_path))
            checkpoint_artifact = None
            checkpoint_recorded_epoch = completed_epoch
            if checkpoint_recorded_epoch > 0:
                try:
                    checkpoint_artifact = self.api.upload_artifact_file(
                        run_id,
                        artifact_type="checkpoint",
                        file_path=str(checkpoint_path),
                        metadata={
                            "proposal_id": proposal_id,
                            "epoch": checkpoint_recorded_epoch,
                            "checkpoint_uri": str(checkpoint_path),
                            "training_config_hash": resume_state["training_config_hash"],
                        },
                    )
                except Exception as checkpoint_error:
                    print(f"⚠️ API: no s'ha pogut pujar checkpoint final ({checkpoint_error})")
            checkpoint_metadata = checkpoint_artifact.get("metadata", {}) if isinstance(checkpoint_artifact, dict) and isinstance(checkpoint_artifact.get("metadata"), dict) else {}
            
            metrics = {}
            if 'loss' in history.history:
                metrics['val_loss_total'] = float(history.history.get('val_loss', history.history['loss'])[-1])
                metrics['train_loss'] = float(history.history['loss'][-1])
                metrics['training_time_seconds'] = elapsed
            metrics['data_prep_seconds'] = data_prep_seconds
            metrics['prepare_inputs_seconds'] = prepare_inputs_seconds
            metrics['split_and_scale_seconds'] = split_and_scale_seconds
            metrics['model_build_seconds'] = model_build_seconds
            metrics['fit_seconds'] = round(float(elapsed), 3)
            metrics['configured_max_epochs'] = active_max_epochs
            metrics['effective_epochs_limit'] = int(epochs)
            metrics['original_model_epochs'] = int(original_epochs)
            metrics['configured_max_training_seconds'] = active_max_training_seconds
            metrics['memory_mb_before_data_prep'] = memory_before_data_prep_mb
            metrics['memory_mb_after_data_prep'] = memory_after_data_prep_mb
            metrics['memory_mb_after_model_build'] = memory_after_model_build_mb
            metrics['memory_mb_after_fit'] = self._current_memory_mb()

            print(f"🟢 Entrenament del model {proposal_id} complet! Reportant estatus a l'API.")

            trained_models_dir = Path(
                os.getenv(
                    "V2_TRAINED_MODELS_DIR",
                    str(self.repo_root / "colab-worker" / "checkpoints" / "trained_models"),
                )
            )
            if not trained_models_dir.is_absolute():
                trained_models_dir = (self.repo_root / trained_models_dir).resolve()
            trained_models_dir.mkdir(parents=True, exist_ok=True)
            trained_model_path = trained_models_dir / f"{proposal_id}.keras"
            keras_model.save(str(trained_model_path))
            model_storage = "drive" if "/content/drive" in str(trained_model_path).replace("\\", "/") else "local"
            artifact_record = None
            print(f"📡 API: pujant artifact trained_model per {proposal_id}...")
            artifact_upload_started_at = time.time()
            try:
                artifact_record = self.api.upload_artifact_file(
                    run_id,
                    artifact_type="trained_model",
                    file_path=str(trained_model_path),
                    metadata={
                        "proposal_id": proposal_id,
                        "trainer_id": self.trainer_id,
                        "source_storage": model_storage,
                        "source_uri": str(trained_model_path),
                    },
                )
                print("✅ API: artifact registrat")
            except Exception as artifact_error:
                print(f"⚠️ API: upload a servidor no disponible, es registra artifact local ({artifact_error})")
                try:
                    artifact_record = self.api.add_artifact(
                        run_id,
                        artifact_type="trained_model",
                        uri=str(trained_model_path),
                        storage=model_storage,
                        metadata={"proposal_id": proposal_id, "trainer_id": self.trainer_id},
                    )
                except Exception as fallback_artifact_error:
                    print(f"⚠️ API: no s'ha pogut registrar artifact local ({fallback_artifact_error})")
            metrics['artifact_upload_seconds'] = round(time.time() - artifact_upload_started_at, 3)
            metrics['memory_mb_after_artifact_upload'] = self._current_memory_mb()
            metrics['total_pipeline_seconds'] = round(time.time() - pipeline_started_at, 3)

            artifact_metadata = artifact_record.get("metadata", {}) if isinstance(artifact_record, dict) and isinstance(artifact_record.get("metadata"), dict) else {}

            # Ens assegurem de notificar a l'API V2
            print(f"📡 API: actualitzant status a trained per {proposal_id}...")
            self.api.update_proposal_status(proposal_id, "trained", {
                "training_kpis": metrics,
                "training_time": elapsed,
                "total_epochs_trained": total_epochs_trained,
                "trained_model_uri": str(trained_model_path),
                "trained_model_server_artifact_id": artifact_metadata.get("artifact_id"),
                "trained_model_download_url": artifact_metadata.get("download_url"),
                "trained_model_availability": artifact_metadata.get("availability_status"),
                "last_epoch_completed": checkpoint_recorded_epoch,
                "resumable": checkpoint_recorded_epoch < int(epochs),
                "last_checkpoint_artifact_id": checkpoint_metadata.get("artifact_id"),
                "last_checkpoint_epoch": checkpoint_recorded_epoch,
                "last_checkpoint_local_path": str(checkpoint_path),
                "resume_checkpoint_uri": checkpoint_metadata.get("artifact_id"),
                "resume_history": [{
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
                    "resumed": resumed_from_checkpoint,
                    "initial_epoch": initial_epoch,
                    "completed_epoch": checkpoint_recorded_epoch,
                }],
            })
            print("✅ API: status trained actualitzat")

            print(f"📡 API: enviant event model_training_completed per {proposal_id}...")
            self.api.add_event(run_id, "model_training_completed", f"El model acceptat {proposal_id} s'ha entrenat.", {"metrics": metrics})
            print("✅ API: event model_training_completed enviat")
            training_succeeded = True
            model_training_metrics = dict(metrics)

            self._update_champion_selection(run_id)

        except Exception as e:
            err_msg = str(e)
            print(f"⚠️ Fallada catastròfica entrenant {proposal_id}: {err_msg}")
            traceback.print_exc()
            try:
                interruption_metadata_raw = proposal.get("llm_metadata")
                interruption_metadata: dict[str, Any] = interruption_metadata_raw if isinstance(interruption_metadata_raw, dict) else {}
                self.api.update_proposal_status(proposal_id, "rejected", {
                    "training_error": err_msg,
                    "training_interrupted_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
                    "resumable": bool(interruption_metadata.get("last_checkpoint_artifact_id")),
                })
            except Exception as status_error:
                print(f"⚠️ API: no s'ha pogut marcar rejected ({status_error})")
            try:
                self.api.add_event(run_id, "model_training_failed", f"Error a l'entrenar {proposal_id}", {"error": err_msg})
            except Exception as event_error:
                print(f"⚠️ API: no s'ha pogut enviar event failed ({event_error})")
            try:
                repaired = self._attempt_repair_failed_proposal(proposal, run_id, err_msg)
                if not repaired:
                    print(f"ℹ️ No s'ha pogut reparar o reemplaçar {proposal_id} després del fallit")
            except Exception as repair_error:
                print(f"⚠️ Repair automàtic fallit per {proposal_id}: {repair_error}")
        finally:
            cleanup_started_at = time.time()
            if keras_model is not None:
                try:
                    del keras_model
                except Exception:
                    pass
            if history is not None:
                try:
                    del history
                except Exception:
                    pass
            self._release_training_memory(X_train, Y_train, X_val, Y_val, X_test, Y_test, scalers)
            cleanup_seconds = round(time.time() - cleanup_started_at, 3)
            if training_succeeded and proposal_id != "" and run_id != "":
                cleanup_payload = {
                    "training_kpis": {
                        **model_training_metrics,
                        "cleanup_seconds": cleanup_seconds,
                        "memory_mb_after_cleanup": self._current_memory_mb(),
                    }
                }
                try:
                    self.api.update_proposal_status(proposal_id, "trained", cleanup_payload)
                except Exception:
                    pass
                try:
                    self.api.add_event(
                        run_id,
                        "training_resource_summary",
                        f"Resum de recursos d'entrenament per {proposal_id}",
                        cleanup_payload,
                    )
                except Exception:
                    pass

    def _update_champion_selection(self, run_id: str) -> None:
        try:
            proposals = self.api.list_model_proposals(limit=600)
        except Exception as error:
            print(f"⚠️ Champion: no s'ha pogut carregar proposals ({error})")
            return

        scoped: list[dict[str, Any]] = []
        for proposal in proposals:
            if not isinstance(proposal, dict):
                continue
            if self.champion_scope == "run" and str(proposal.get("source_run_id", "")).strip() != run_id:
                continue
            scoped.append(proposal)

        evaluated: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for proposal in scoped:
            decision = evaluate_reference_candidate(proposal, config=self.selection_policy_config)
            if bool(decision.get("eligible")):
                evaluated.append((proposal, decision))

        if len(evaluated) == 0:
            try:
                self.api.add_event(
                    run_id,
                    "champion_selection_skipped",
                    "Cap candidat elegible per champion",
                    {
                        "scope": self.champion_scope,
                        "policy_version": self.selection_policy_config.get("policy_version", "selection_policy_v1"),
                    },
                )
            except Exception:
                pass
            return

        evaluated.sort(key=lambda item: float(item[1].get("score", 0.0)), reverse=True)
        best_proposal, best_decision = evaluated[0]
        best_score = float(best_decision.get("score", 0.0))

        champion_min_score = float(self.selection_policy_config.get("champion_min_score", 45.0))
        if best_score < champion_min_score:
            try:
                self.api.add_event(
                    run_id,
                    "champion_selection_skipped",
                    "Millor score per sota del minim de champion",
                    {
                        "scope": self.champion_scope,
                        "best_proposal_id": best_proposal.get("proposal_id"),
                        "best_score": best_score,
                        "champion_min_score": champion_min_score,
                    },
                )
            except Exception:
                pass
            return

        current_champion_proposal: dict[str, Any] | None = None
        current_champion_decision: dict[str, Any] | None = None
        for proposal, decision in evaluated:
            metadata_raw = proposal.get("llm_metadata")
            metadata = metadata_raw if isinstance(metadata_raw, dict) else {}
            if bool(metadata.get("champion_active")):
                current_champion_proposal = proposal
                current_champion_decision = decision
                break

        champion_margin_min = float(self.selection_policy_config.get("champion_margin_min", 2.0))
        if current_champion_proposal is not None and current_champion_decision is not None:
            current_id = str(current_champion_proposal.get("proposal_id", "")).strip()
            best_id = str(best_proposal.get("proposal_id", "")).strip()
            current_score = float(current_champion_decision.get("score", 0.0))
            if best_id != current_id and (best_score - current_score) < champion_margin_min:
                try:
                    self.api.add_event(
                        run_id,
                        "champion_kept",
                        "Champion actual mantingut per marge insuficient",
                        {
                            "scope": self.champion_scope,
                            "current_champion_id": current_id,
                            "current_score": current_score,
                            "best_candidate_id": best_id,
                            "best_score": best_score,
                            "margin_required": champion_margin_min,
                        },
                    )
                except Exception:
                    pass
                return

        best_id = str(best_proposal.get("proposal_id", "")).strip()
        best_status = str(best_proposal.get("status", "")).strip()
        if best_id == "" or best_status == "":
            return

        if current_champion_proposal is not None:
            current_id = str(current_champion_proposal.get("proposal_id", "")).strip()
            current_status = str(current_champion_proposal.get("status", "")).strip()
            if current_id != "" and current_id != best_id and current_status != "":
                try:
                    self.api.update_proposal_status(
                        current_id,
                        current_status,
                        {
                            "champion_active": False,
                            "champion_replaced_by": best_id,
                        },
                    )
                except Exception as error:
                    print(f"⚠️ Champion: no s'ha pogut desactivar champion anterior ({error})")

        champion_metadata = {
            "champion_active": True,
            "champion_scope": self.champion_scope,
            "champion_policy_version": str(self.selection_policy_config.get("policy_version", "selection_policy_v1")),
            "champion_policy_profile": str(self.selection_policy_config.get("profile", "default")),
            "champion_score": best_score,
            "champion_selection_reason": str(best_decision.get("selection_reason", "")),
            "champion_score_breakdown": best_decision.get("score_breakdown", {}),
            "champion_source_run_id": str(best_proposal.get("source_run_id", "")),
        }

        try:
            self.api.update_proposal_status(best_id, best_status, champion_metadata)
        except Exception as error:
            print(f"⚠️ Champion: no s'ha pogut marcar champion ({error})")
            return

        champion_uri = f"champion://{self.champion_scope}/{best_id}"
        best_metadata_raw = best_proposal.get("llm_metadata")
        best_metadata = best_metadata_raw if isinstance(best_metadata_raw, dict) else {}
        champion_storage = "local"
        if isinstance(best_metadata.get("trained_model_server_artifact_id"), str) and str(best_metadata.get("trained_model_server_artifact_id", "")).strip() != "":
            champion_storage = "server"
            champion_uri = str(best_metadata.get("trained_model_download_url") or champion_uri)
        try:
            self.api.add_artifact(
                run_id,
                artifact_type="champion_model",
                uri=champion_uri,
                storage=champion_storage,
                metadata={
                    "proposal_id": best_id,
                    "scope": self.champion_scope,
                    "score": best_score,
                    "policy_version": self.selection_policy_config.get("policy_version", "selection_policy_v1"),
                    "linked_artifact_id": best_metadata.get("trained_model_server_artifact_id"),
                    "download_url": best_metadata.get("trained_model_download_url"),
                    "availability_status": best_metadata.get("trained_model_availability"),
                },
            )
        except Exception as error:
            print(f"⚠️ Champion: no s'ha pogut registrar artifact champion ({error})")

        try:
            self.api.add_event(
                run_id,
                "champion_selected",
                f"Champion seleccionat: {best_id}",
                {
                    "scope": self.champion_scope,
                    "proposal_id": best_id,
                    "score": best_score,
                    "selection_reason": best_decision.get("selection_reason", ""),
                    "policy_version": self.selection_policy_config.get("policy_version", "selection_policy_v1"),
                    "policy_profile": self.selection_policy_config.get("profile", "default"),
                },
            )
        except Exception:
            pass
