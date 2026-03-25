import time
import os
import json
import hashlib
import logging
import traceback
from pathlib import Path
from typing import Any, Optional, cast

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

    def _emit_event(self, event_type: str, label: str, details: dict[str, Any] | None = None) -> None:
        if self.api is None or self.run_id.strip() == "":
            return
        try:
            self.api.add_event(self.run_id, event_type, label, details or {})
        except Exception:
            return

    def on_train_begin(self, logs=None):
        self.start_time = time.time()
        print(f"\n🚀 Inciant entrenament pesat pel model {self.proposal_id}")
        if self.max_training_seconds > 0:
            print(f"⏱️ Límit establert a: {self.max_training_seconds} segons.")
        self._emit_event(
            "model_training_started",
            f"Entrenament iniciat per {self.proposal_id}",
            {"proposal_id": self.proposal_id, "max_training_seconds": self.max_training_seconds},
        )

    def on_epoch_begin(self, epoch, logs=None):
        print(f"🔄 Model {self.proposal_id} - Començant època {epoch + 1}...")
        self._emit_event(
            "model_training_epoch_start",
            f"Model {self.proposal_id} · inici època {epoch + 1}",
            {"proposal_id": self.proposal_id, "epoch": int(epoch + 1)},
        )

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
            print(f"🛑 ATENCIÓ: Temps límit d'entrenament superat ({elapsed:.1f}s > {self.max_training_seconds}s). S'interromp l'entrenament.")
            self._emit_event(
                "model_training_stopped_by_time_limit",
                f"Model {self.proposal_id} aturat per límit de temps",
                {
                    "proposal_id": self.proposal_id,
                    "elapsed_seconds": round(float(elapsed), 2),
                    "max_training_seconds": self.max_training_seconds,
                },
            )
            model = getattr(self, "model", None)
            if model is not None:
                model.stop_training = True


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
        self.selection_policy_config = load_policy_config_from_env()
        self.champion_scope = os.getenv("V2_CHAMPION_SCOPE", "run").strip().lower()
        if self.champion_scope not in {"run", "global"}:
            self.champion_scope = "run"
        self.checkpoint_every_epochs = max(1, int(os.getenv("V2_CHECKPOINT_EVERY_EPOCHS", "1")))
        self.max_resume_attempts = max(1, int(os.getenv("V2_MAX_RESUME_ATTEMPTS", "2")))

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
        can_resume = resumable and checkpoint_artifact_id != "" and checkpoint_epoch > 0 and checkpoint_exists and config_match and resume_attempts < self.max_resume_attempts
        return {
            "training_config_hash": training_hash,
            "checkpoint_artifact_id": checkpoint_artifact_id,
            "checkpoint_epoch": checkpoint_epoch,
            "checkpoint_local_path": checkpoint_path,
            "resume_attempts": resume_attempts,
            "config_match": config_match,
            "checkpoint_exists": checkpoint_exists,
            "can_resume": can_resume,
        }

    def run_loop(self):
        print(f"🟢 [Trainer Worker: {self.trainer_id}] Mantenint cerca de models acceptats...")
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
        
        try:
            # 1. Obtenir definició d'arquitectura
            model_def = proposal.get("proposal", {}).get("model_definition", {})
            if not model_def:
                raise RuntimeError("El payload no conté `model_definition`.")

            model_def["model_id"] = proposal_id
            resume_state = self._resolve_resume_state(proposal, model_def)

            # 2. Reutilitzar utilitats de dades/model (shared first, legacy fallback)
            try:
                from shared.utils.data_loading_utils import load_all_raw_data_sources, derive_additional_features_and_targets
                from shared.utils.data_preparation_utils import prepare_model_specific_inputs_outputs, split_and_scale_data
                from shared.utils.model_builder import build_model_from_json_definition
            except ModuleNotFoundError:
                from utils.data_loading_utils import load_all_raw_data_sources, derive_additional_features_and_targets
                from utils.data_preparation_utils import prepare_model_specific_inputs_outputs, split_and_scale_data
                from utils.model_builder import build_model_from_json_definition

            print("📊 Carregant el fitxer de configuració de l'experiment (V1 compatibility)...")
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
            
            # Necessari per reomplir els arrays "runtime" esperats pel V1 format
            input_cfg = exp_config.get("input_features_config", [])
            output_cfg = exp_config.get("output_targets_config", [])
            model_def["input_features_config_runtime"] = input_cfg
            model_def["output_targets_config_runtime"] = output_cfg

            print("🔨 Instanciant les dades locals i processant-les...")
            raw_sources = load_all_raw_data_sources(
                exp_config.get("data_paths", {}), 
                input_cfg, 
                output_cfg, 
                base_data_dir=str(base_data_dir)
            )
            all_data = derive_additional_features_and_targets(raw_sources, input_cfg, output_cfg)
            
            X_list, Y_list, in_names, out_names = prepare_model_specific_inputs_outputs(all_data, model_def)
            (X_train, Y_train), (X_val, Y_val), (X_test, Y_test), scalers = split_and_scale_data(X_list, Y_list, in_names, exp_config, model_def)

            print("🏗️ Construint el graf Keras del model...")
            keras_model = build_model_from_json_definition(model_def)
            checkpoint_dir = self._checkpoint_dir_for_proposal(proposal_id)
            checkpoint_path = checkpoint_dir / f"{proposal_id}.weights.h5"
            
            # Parametrització temporal o definitiva?
            epochs = model_def.get("training_config", {}).get("fit", {}).get("epochs", 15)
            batch_sz = model_def.get("training_config", {}).get("fit", {}).get("batch_size", 64)
            
            # Protecció contra èpoques excessives si cal fer testing ràpid
            callbacks = [
                TrainerFeedbackAndLimitCallback(
                    proposal_id,
                    self.max_seconds_per_model,
                    api_client=self.api,
                    run_id=run_id,
                ),
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
