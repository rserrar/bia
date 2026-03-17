import time
import os
import json
import logging
import traceback
from pathlib import Path
from typing import Any, Optional

try:
    import tensorflow as tf
    from tensorflow.keras.callbacks import Callback
except ImportError:
    tf = None

from src.api_client import ApiClient

# A callback that prints out epoch progression visibly and gracefully stops 
# the training if it exceeds a specified max time limit.
class TrainerFeedbackAndLimitCallback(Callback):
    def __init__(self, proposal_id: str, max_training_seconds: int = 0):
        super().__init__()
        self.proposal_id = proposal_id
        self.max_training_seconds = max_training_seconds
        self.start_time = 0.0

    def on_train_begin(self, logs=None):
        self.start_time = time.time()
        print(f"\n🚀 Inciant entrenament pesat pel model {self.proposal_id}")
        if self.max_training_seconds > 0:
            print(f"⏱️ Límit establert a: {self.max_training_seconds} segons.")

    def on_epoch_begin(self, epoch, logs=None):
        print(f"🔄 Model {self.proposal_id} - Començant època {epoch + 1}...")

    def on_epoch_end(self, epoch, logs=None):
        elapsed = time.time() - self.start_time
        metrics_str = " | ".join([f"{k}: {v:.4f}" for k, v in (logs or {}).items()])
        print(f"✅ Època {epoch + 1} completada - {metrics_str} - Temps transcòrregut: {elapsed:.1f}s")
        
        if self.max_training_seconds > 0 and elapsed > self.max_training_seconds:
            print(f"🛑 ATENCIÓ: Temps límit d'entrenament superat ({elapsed:.1f}s > {self.max_training_seconds}s). S'interromp l'entrenament.")
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

    def run_loop(self):
        print(f"🟢 [Trainer Worker: {self.trainer_id}] Mantenint cerca de models acceptats...")
        while True:
            try:
                proposal = self.api.lock_accepted_proposal_for_training(self.trainer_id)
                if not proposal:
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

    def _train_proposal(self, proposal: dict[str, Any]):
        proposal_id = str(proposal.get("proposal_id", ""))
        run_id = str(proposal.get("source_run_id", ""))
        
        try:
            # 1. Obtenir definició d'arquitectura
            model_def = proposal.get("proposal", {}).get("model_definition", {})
            if not model_def:
                raise RuntimeError("El payload no conté `model_definition`.")
                
            model_def["model_id"] = proposal_id

            # 2. Reutilitzar els scripts de dades del V1 per fer la neteja
            from utils.data_loading_utils import load_all_raw_data_sources, derive_additional_features_and_targets
            from utils.data_preparation_utils import prepare_model_specific_inputs_outputs, split_and_scale_data
            from utils.model_builder import build_model_from_json_definition

            print("📊 Carregant el fitxer de configuració de l'experiment (V1 compatibility)...")
            experiment_path = self.repo_root / "config_experiment.json"
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
            callbacks = [TrainerFeedbackAndLimitCallback(proposal_id, self.max_training_seconds)]
            
            print(f"🔥 Donant inici al mètode keras_model.fit() per un màxim de {epochs} èpoques.")
            start_t = time.time()
            history = keras_model.fit(
                X_train, Y_train,
                validation_data=(X_val, Y_val) if X_val else None,
                epochs=epochs,
                batch_size=batch_sz,
                verbose=0,  # Apaguem el verbose per defecte i treballem amb el de la consola 
                callbacks=callbacks
            )
            elapsed = time.time() - start_t
            
            metrics = {}
            if 'loss' in history.history:
                metrics['val_loss_total'] = float(history.history.get('val_loss', history.history['loss'])[-1])
                metrics['train_loss'] = float(history.history['loss'][-1])
                metrics['training_time_seconds'] = elapsed

            print(f"🟢 Entrenament del model {proposal_id} complet! Reportant estatus a l'API.")

            # Ens assegurem de notificar a l'API V2
            self.api.update_proposal_status(proposal_id, "trained", {
                "training_kpis": metrics,
                "training_time": elapsed,
                "total_epochs_trained": len(history.history['loss'])
            })
            
            self.api.add_event(run_id, "model_training_completed", f"El model acceptat {proposal_id} s'ha entrenat.", {"metrics": metrics})

        except Exception as e:
            err_msg = str(e)
            print(f"⚠️ Fallada catastròfica entrenant {proposal_id}: {err_msg}")
            traceback.print_exc()
            self.api.update_proposal_status(proposal_id, "rejected", {
                "training_error": err_msg
            })
            self.api.add_event(run_id, "model_training_failed", f"Error a l'entrenar {proposal_id}", {"error": err_msg})
