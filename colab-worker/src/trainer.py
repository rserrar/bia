import time
import os
import json
import logging
import traceback
from pathlib import Path
from typing import Any, Optional, cast

from shared.utils.selection_policy import evaluate_reference_candidate, load_policy_config_from_env

try:
    import tensorflow as tf
    from tensorflow.keras.callbacks import Callback as KerasCallback
except ImportError:
    tf = None

    class KerasCallback:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            pass

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
class TrainerFeedbackAndLimitCallback(KerasCallback):
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
            self.model.stop_training = True

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
                )
            ]
            
            print(f"🔥 Donant inici al mètode keras_model.fit() per un màxim de {epochs} èpoques.")
            start_t = time.time()
            history = keras_model.fit(
                X_train, Y_train,
                validation_data=(X_val, Y_val) if X_val else None,
                epochs=epochs,
                batch_size=batch_sz,
                verbose=0,  # Apaguem el verbose per defecte i treballem amb el de la consola 
                callbacks=cast(Any, callbacks)
            )
            elapsed = time.time() - start_t
            
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
            print(f"📡 API: pujant artifact trained_model per {proposal_id}...")
            try:
                self.api.add_artifact(
                    run_id,
                    artifact_type="trained_model",
                    uri=str(trained_model_path),
                    storage=model_storage,
                    metadata={"proposal_id": proposal_id, "trainer_id": self.trainer_id},
                )
                print("✅ API: artifact registrat")
            except Exception as artifact_error:
                print(f"⚠️ API: no s'ha pogut registrar artifact ({artifact_error})")

            # Ens assegurem de notificar a l'API V2
            print(f"📡 API: actualitzant status a trained per {proposal_id}...")
            self.api.update_proposal_status(proposal_id, "trained", {
                "training_kpis": metrics,
                "training_time": elapsed,
                "total_epochs_trained": len(history.history['loss']),
                "trained_model_uri": str(trained_model_path),
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
                self.api.update_proposal_status(proposal_id, "rejected", {
                    "training_error": err_msg
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
        try:
            self.api.add_artifact(
                run_id,
                artifact_type="champion_model",
                uri=champion_uri,
                storage="local",
                metadata={
                    "proposal_id": best_id,
                    "scope": self.champion_scope,
                    "score": best_score,
                    "policy_version": self.selection_policy_config.get("policy_version", "selection_policy_v1"),
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
                },
            )
        except Exception:
            pass
