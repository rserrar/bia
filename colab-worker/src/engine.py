from __future__ import annotations

import os
import time
import json
import copy
from dataclasses import asdict, dataclass
from pathlib import Path

try:
    from .api_client import ApiClient
    from .checkpoint_store import CheckpointStore
    from .config import WorkerConfig
    from .legacy_model_compat import build_legacy_model_once
    from .llm_client import LlmConfig, LlmProposalClient
except ImportError:
    from api_client import ApiClient
    from checkpoint_store import CheckpointStore
    from config import WorkerConfig
    from legacy_model_compat import build_legacy_model_once
    from llm_client import LlmConfig, LlmProposalClient


@dataclass
class WorkerState:
    run_id: str | None = None
    generation: int = 0
    stage: str = "init"
    status: str = "queued"
    total_llm_tokens: int = 0


class EvolutionWorkerEngine:
    def __init__(self, config: WorkerConfig, api_client: ApiClient, checkpoint_store: CheckpointStore) -> None:
        self.config = config
        self.api = api_client
        self.checkpoints = checkpoint_store
        self.state = self._load_state()
        self.last_llm_call_ts = 0.0
        self.llm = LlmProposalClient(
            LlmConfig(
                enabled=self.config.llm_enabled,
                use_legacy_interface=self.config.llm_use_legacy_interface,
                provider=self.config.llm_provider,
                endpoint=self.config.llm_endpoint,
                api_key=self.config.llm_api_key,
                model=self.config.llm_model,
                timeout_seconds=self.config.llm_timeout_seconds,
                temperature=self.config.llm_temperature,
                max_tokens=self.config.llm_max_tokens,
                system_prompt=self.config.llm_system_prompt,
                prompt_template_file=self.config.llm_prompt_template_file,
                fix_error_prompt_file=self.config.llm_fix_error_prompt_file,
                architecture_guide_file=self.config.llm_architecture_guide_file,
                experiment_config_file=self.config.llm_experiment_config_file,
                num_new_models=self.config.llm_num_new_models,
                num_reference_models=self.config.llm_num_reference_models,
                repair_on_validation_error=self.config.llm_repair_on_validation_error,
            )
        )

    def _load_state(self) -> WorkerState:
        data = self.checkpoints.load()
        if not data:
            return WorkerState()
        return WorkerState(
            run_id=data.get("run_id"),
            generation=int(data.get("generation", 0)),
            stage=data.get("stage", "init"),
            status=data.get("status", "queued"),
            total_llm_tokens=int(data.get("total_llm_tokens", 0)),
        )

    def _save_state(self) -> None:
        self.checkpoints.save(asdict(self.state))

    def _ensure_run(self) -> None:
        if self.state.run_id:
            try:
                remote_run = self.api.get_run(self.state.run_id)
            except Exception:
                self.state.run_id = None
            else:
                self.state.status = str(remote_run.get("status", self.state.status))
                remote_generation = int(remote_run.get("generation", self.state.generation))
                if remote_generation > self.state.generation:
                    self.state.generation = remote_generation
                self.state.stage = "run_recovered"
                self._save_state()
                return
        run = self.api.create_run(self.config.code_version, self.config.run_metadata)
        self.state.run_id = run["run_id"]
        self.state.status = run["status"]
        self.state.stage = "run_created"
        self._save_state()

    def _send_heartbeat(self) -> None:
        if not self.state.run_id:
            return
        run = self.api.heartbeat(self.state.run_id)
        self.state.status = run["status"]
        self._save_state()

    def _run_generation_step(self, generation: int) -> None:
        run_id = self.state.run_id
        if not run_id:
            raise RuntimeError("run_id not initialized")
        self.api.update_status(run_id, "running", generation)
        self.api.add_event(run_id, "generation_start", f"Inici generació {generation}")
        simulated_metric = {
            "val_loss_total": round(1.0 / (generation + 1), 6),
            "models_evaluated": 3,
        }
        self.api.add_metric(run_id, model_id=f"gen_{generation}_summary", generation=generation, metrics=simulated_metric)
        self._create_model_proposal_if_enabled(run_id, generation, simulated_metric)
        self.api.add_artifact(
            run_id,
            artifact_type="checkpoint",
            uri=self.config.checkpoint_path,
            storage="drive",
            metadata={"generation": generation},
        )
        self.api.add_event(run_id, "generation_end", f"Fi generació {generation}")
        self.state.generation = generation + 1
        self.state.stage = "generation_completed"
        self._save_state()

    def _create_model_proposal_if_enabled(self, run_id: str, generation: int, metrics: dict[str, float | int]) -> None:
        if not self.config.llm_enabled:
            return
        min_interval = max(0, int(self.config.llm_min_interval_seconds))
        if min_interval > 0 and self.last_llm_call_ts > 0:
            elapsed = time.time() - self.last_llm_call_ts
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
        context = {
            "run_id": run_id,
            "generation": generation,
            "latest_metrics": metrics,
            "code_version": self.config.code_version,
        }
        context["reference_models"] = self._collect_reference_models_for_prompt(run_id)
        try:
            self.last_llm_call_ts = time.time()
            print("🤖 Fent petició al LLM per generar una nova proposta. Espera si us plau...")
            candidate = self.llm.generate_candidate(context)
            if not candidate:
                return
            base_model_id = str(candidate.get("base_model_id", "")).strip() or "unknown_base_model"
            proposal = candidate.get("proposal")
            if not isinstance(proposal, dict) or len(proposal) == 0:
                raise RuntimeError("LLM candidate proposal is invalid")
            llm_metadata = candidate.get("llm_metadata")
            llm_metadata_payload = llm_metadata if isinstance(llm_metadata, dict) else {}
            llm_metadata_payload["from_generation"] = generation
            
            raw_response = llm_metadata_payload.get("raw_response", {})
            if isinstance(raw_response, dict):
                usage = raw_response.get("usage", {})
                if isinstance(usage, dict):
                    tokens = int(usage.get("total_tokens", 0) or 0)
                    if tokens > 0:
                        self.state.total_llm_tokens += tokens
                        llm_metadata_payload["accumulated_run_tokens"] = self.state.total_llm_tokens
                        max_tokens_run = int(os.getenv("V2_LLM_MAX_TOKENS_PER_RUN", "500000"))
                        if self.state.total_llm_tokens > max_tokens_run:
                            self.api.add_event(run_id, "llm_quota_reached", f"Quota exhaurida: {self.state.total_llm_tokens} > {max_tokens_run}")

            created = self.api.create_model_proposal(
                source_run_id=run_id,
                base_model_id=base_model_id,
                proposal=proposal,
                llm_metadata=llm_metadata_payload,
            )
            proposal_id = str(created.get("proposal_id", ""))
            if proposal_id != "":
                self.api.enqueue_model_proposal_phase0(proposal_id)
            self.api.add_event(
                run_id,
                "llm_proposal_created",
                f"Proposta LLM creada a generació {generation}",
                {"proposal_id": proposal_id, "base_model_id": base_model_id},
            )
        except Exception as error:
            self.api.add_event(
                run_id,
                "llm_proposal_error",
                f"Error creant proposta LLM a generació {generation}",
                {"error": str(error)},
            )

    def _collect_reference_models_for_prompt(self, run_id: str) -> list[dict[str, object]]:
        max_refs = max(0, int(self.config.llm_num_reference_models))
        if max_refs <= 0:
            return []

        references: list[dict[str, object]] = []
        try:
            proposals = self.api.list_model_proposals(limit=300)
            ranked: list[tuple[float, dict[str, object]]] = []
            for proposal in proposals:
                status = str(proposal.get("status", "")).strip()
                if status not in {"trained", "accepted", "validated_phase0"}:
                    continue
                payload = proposal.get("proposal")
                if not isinstance(payload, dict):
                    continue
                model_definition = payload.get("model_definition")
                if not isinstance(model_definition, dict):
                    continue
                llm_metadata_raw = proposal.get("llm_metadata")
                llm_metadata: dict[str, object] = llm_metadata_raw if isinstance(llm_metadata_raw, dict) else {}
                training_kpis_raw = llm_metadata.get("training_kpis")
                kpi_eval_raw = llm_metadata.get("kpi_evaluation")
                training_kpis: dict[str, object] = training_kpis_raw if isinstance(training_kpis_raw, dict) else {}
                kpi_eval: dict[str, object] = kpi_eval_raw if isinstance(kpi_eval_raw, dict) else {}
                val_loss: object = training_kpis.get("val_loss_total", kpi_eval.get("val_loss_total", 9999))
                if isinstance(val_loss, (int, float, str)):
                    try:
                        score = float(val_loss)
                    except Exception:
                        score = 9999.0
                else:
                    score = 9999.0
                reference: dict[str, object] = dict(model_definition)
                reference["model_id"] = str(model_definition.get("model_id", proposal.get("proposal_id", "unknown_model")))
                reference["reference_status"] = status
                reference["reference_source_run_id"] = str(proposal.get("source_run_id", ""))
                reference["last_evaluation_metrics_summary"] = {
                    "val_loss_total": score,
                    "training_kpis": training_kpis,
                    "kpi_evaluation": kpi_eval,
                }
                ranked.append((score, reference))
            ranked.sort(key=lambda item: item[0])
            references = [item[1] for item in ranked[:max_refs]]
        except Exception:
            references = []

        if len(references) == 0:
            fallback = self._load_reference_models_from_file(max_refs)
            if len(fallback) > 0:
                if self.state.run_id:
                    self.api.add_event(
                        run_id,
                        "llm_reference_models_fallback",
                        "S'han usat models de referència locals per al prompt",
                        {"count": len(fallback)},
                    )
                return fallback
        return references

    def _load_reference_models_from_file(self, max_refs: int) -> list[dict[str, object]]:
        path_str = os.getenv("V2_PROMPT_REFERENCE_MODEL_PATH", "models/base/model_exemple_complex_v1.json").strip()
        if path_str == "":
            return []
        raw = Path(path_str)
        repo_root = Path(__file__).resolve().parents[2]
        if raw.is_absolute():
            if not raw.exists():
                normalized = str(raw).replace("\\", "/")
                if "/V2/" in normalized:
                    candidate = Path(normalized.replace("/V2/", "/", 1))
                    if candidate.exists():
                        raw = candidate
        else:
            candidate = (repo_root / raw).resolve()
            if candidate.exists():
                raw = candidate
            else:
                normalized_rel = str(raw).replace("\\", "/")
                if normalized_rel.startswith("V2/"):
                    fallback = (repo_root / normalized_rel[3:]).resolve()
                    if fallback.exists():
                        raw = fallback
                else:
                    raw = candidate
        if not raw.exists():
            return []
        try:
            loaded = json.loads(raw.read_text(encoding="utf-8"))
        except Exception:
            return []
        models: list[dict[str, object]] = []
        if isinstance(loaded, dict):
            models = [loaded]
        elif isinstance(loaded, list):
            models = [item for item in loaded if isinstance(item, dict)]
        if len(models) == 0:
            return []
        out: list[dict[str, object]] = []
        for model in models[:max_refs]:
            entry = dict(model)
            entry["reference_status"] = "local_example"
            entry["last_evaluation_metrics_summary"] = {"source": "local_file", "val_loss_total": None}
            out.append(entry)
        return out

    def _verify_legacy_model_build_if_enabled(self) -> None:
        if not self.config.verify_legacy_model_build:
            return
        run_id = self.state.run_id
        if not run_id:
            return
        try:
            result = build_legacy_model_once(
                model_json_path=self.config.legacy_model_json_path,
                experiment_config_path=self.config.legacy_experiment_config_path,
                legacy_builder_path=self.config.legacy_builder_path,
            )
            self.api.add_event(run_id, "legacy_model_build_ok", "Compatibilitat model legacy verificada", result)
        except Exception as error:
            self.api.add_event(
                run_id,
                "legacy_model_build_error",
                "Error en verificació de compatibilitat model legacy",
                {"error": str(error)},
            )
            if self.config.legacy_build_check_strict:
                raise

    def _bootstrap_seed_model_if_needed(self, run_id: str) -> None:
        if not self.config.bootstrap_seed_model_if_empty:
            return
        try:
            existing = self.api.list_model_proposals(limit=1)
        except Exception:
            return
        if len(existing) > 0:
            return

        references = self._load_reference_models_from_file(1)
        if len(references) == 0:
            return
        seed_model = copy.deepcopy(references[0])
        if not isinstance(seed_model, dict):
            return
        seed_model.pop("reference_status", None)
        seed_model.pop("last_evaluation_metrics_summary", None)

        base_model_id = str(seed_model.get("model_id", "seed_model_base")).strip() or "seed_model_base"
        llm_metadata = {
            "seed_bootstrap": True,
            "seed_source": os.getenv("V2_PROMPT_REFERENCE_MODEL_PATH", "models/base/model_exemple_complex_v1.json"),
            "seed_created_by": "engine_bootstrap",
        }
        created = self.api.create_model_proposal(
            source_run_id=run_id,
            base_model_id=base_model_id,
            proposal={"model_definition": seed_model},
            llm_metadata=llm_metadata,
        )
        proposal_id = str(created.get("proposal_id", "")).strip()
        if proposal_id != "":
            self.api.enqueue_model_proposal_phase0(proposal_id)
        self.api.add_event(
            run_id,
            "seed_model_bootstrapped",
            "Model de prova inicial creat automàticament",
            {"proposal_id": proposal_id, "base_model_id": base_model_id},
        )

    def _process_queued_proposals_phase0_if_enabled(self) -> None:
        if not self.config.auto_process_proposals_phase0:
            return
        run_id = self.state.run_id
        if not run_id:
            return
        try:
            result = self.api.process_model_proposals_phase0(self.config.proposals_phase0_batch_size)
            processed_count = int(result.get("processed_count", 0))
            if processed_count > 0:
                self.api.add_event(
                    run_id,
                    "proposal_phase0_auto_processed",
                    f"Propostes processades automàticament: {processed_count}",
                    result,
                )
        except Exception as error:
            self.api.add_event(
                run_id,
                "proposal_phase0_auto_process_error",
                "Error en processament automàtic de proposals queued_phase0",
                {"error": str(error)},
            )

    def run(self) -> None:
        self._ensure_run()
        run_id = self.state.run_id
        if not run_id:
            raise RuntimeError("run_id not available")
        if self.state.status == "completed" or self.state.generation >= self.config.max_generations:
            self.state.status = "completed"
            self.state.stage = "finished"
            self._save_state()
            return
        self._verify_legacy_model_build_if_enabled()
        self._bootstrap_seed_model_if_needed(run_id)
        self._process_queued_proposals_phase0_if_enabled()
        self.api.update_status(run_id, "running", self.state.generation)
        last_heartbeat = 0.0
        while self.state.generation < self.config.max_generations:
            now = time.time()
            if now - last_heartbeat >= self.config.heartbeat_interval_seconds:
                self._send_heartbeat()
                self._process_queued_proposals_phase0_if_enabled()
                last_heartbeat = now
            self._run_generation_step(self.state.generation)
            self._process_queued_proposals_phase0_if_enabled()
            time.sleep(1)
        self._process_queued_proposals_phase0_if_enabled()
        self.api.update_status(run_id, "completed", self.state.generation)
        self.api.add_event(run_id, "run_completed", "Execució finalitzada")
        self.state.status = "completed"
        self.state.stage = "finished"
        self._save_state()
