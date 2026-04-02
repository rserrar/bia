from __future__ import annotations

import os
import time
import json
import copy
import subprocess
import sys
import signal
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from shared.utils.selection_policy import evaluate_reference_candidate, load_policy_config_from_env

try:
    from .api_client import ApiClient
    from .checkpoint_store import CheckpointStore
    from .config import WorkerConfig
    from .legacy_model_compat import build_legacy_model_once
    from .llm_client import LlmConfig, LlmGenerationError, LlmProposalClient, LlmRateLimitError
except ImportError:
    from api_client import ApiClient
    from checkpoint_store import CheckpointStore
    from config import WorkerConfig
    from legacy_model_compat import build_legacy_model_once
    from llm_client import LlmConfig, LlmGenerationError, LlmProposalClient, LlmRateLimitError


@dataclass
class WorkerState:
    run_id: str | None = None
    generation: int = 0
    stage: str = "init"
    status: str = "queued"
    total_llm_tokens: int = 0


class TrainerSupervisor:
    """Gestiona el procés del Trainer en un subprocess separat."""
    def __init__(self, api_client: ApiClient, repo_root: Path):
        self.api = api_client
        self.repo_root = repo_root
        self.process: subprocess.Popen | None = None
        self.last_check_ts = time.time()
        self.trainer_id: str | None = None
        self.stuck_timeout_seconds = int(os.getenv("V2_TRAINER_STUCK_TIMEOUT", "600")) # 10 minuts per defecte

    def start(self):
        self.stop() # Assegurar que no n'hi ha cap altre
        print("🚀 Supervisor: Llançant nou procés del Trainer...")
        
        cmd = [sys.executable, str(self.repo_root / "colab-worker" / "run_trainer.py")]
        
        # Passem variables d'entorn necessàries
        env = os.environ.copy()
        # Podem forçar que el trainer hereti la configuració
        
        self.process = subprocess.Popen(
            cmd,
            cwd=str(self.repo_root),
            env=env,
            stdout=None, # El deixem que escrigui a la consola de Colab directament
            stderr=None
        )
        self.last_check_ts = time.time()
        print(f"✅ Supervisor: Trainer iniciat amb PID {self.process.pid}")

    def stop(self):
        if self.process and self.process.poll() is None:
            print(f"🛑 Supervisor: Aturant procés del Trainer (PID {self.process.pid})...")
            try:
                # Intentem tancament amable
                if os.name == 'nt': # Windows
                    self.process.terminate()
                else:
                    os.kill(self.process.pid, signal.SIGTERM)
                
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                print("⚠️ Supervisor: El procés no s'atura, forçant kill...")
                self.process.kill()
            except Exception as e:
                print(f"⚠️ Supervisor: Error al tancar el procés: {e}")
        
        self.process = None

    def ensure_alive(self):
        """Comprova si el procés està viu i si està 'encallat'."""
        if not self.process or self.process.poll() is not None:
            print("⚠️ Supervisor: El procés del Trainer ha mort o no ha començat. Reiniciant...")
            self.start()
            return

        # Comprovació de si està encallat (cada X minuts)
        now = time.time()
        if now - self.last_check_ts > 60: # Comprovem cada minut
            self.last_check_ts = now
            if self._is_trainer_stuck():
                print(f"🔥 Supervisor: Detectat Trainer encallat! Reiniciant procés...")
                self.api.add_event(
                    os.getenv("V2_RUN_ID", "unknown"), 
                    "trainer_stuck_detected", 
                    "El supervisor ha detectat que el trainer està encallat i el reiniciarà"
                )
                self.start()

    def _is_trainer_stuck(self) -> bool:
        """Determina si el trainer està encallat basant-se en l'activitat de l'API."""
        try:
            # Busquem l'últim event de la run per saber si hi ha moviment
            run_id = os.getenv("V2_RUN_ID")
            if not run_id:
                return False
                
            # Si el procés ha acabat, no està encallat (està mort)
            if self.process and self.process.poll() is not None:
                return False
                
            # Comprovem l'últim event de la run
            events = self.api._request("GET", f"runs/{run_id}/events", params={"limit": 1})
            if isinstance(events, list) and len(events) > 0:
                last_event = events[0]
                created_at = last_event.get("created_at")
                if created_at:
                    # Parseig simple de data ISO
                    import datetime
                    # Treiem la Z o el +00:00 si cal
                    clean_ts = created_at.split('.')[0].replace('Z', '').replace(' ', 'T')
                    last_dt = datetime.datetime.fromisoformat(clean_ts)
                    diff = (datetime.datetime.utcnow() - last_dt).total_seconds()
                    
                    if diff > self.stuck_timeout_seconds:
                        print(f"🕵️ Supervisor: L'últim event ({last_event.get('event_type')}) fa {diff:.1f}s. El límit és {self.stuck_timeout_seconds}s.")
                        return True
            return False
        except Exception as e:
            print(f"⚠️ Supervisor: Error comprovisionant si està encallat: {e}")
            return False


class EvolutionWorkerEngine:
    def __init__(self, config: WorkerConfig, api_client: ApiClient, checkpoint_store: CheckpointStore) -> None:
        self.config = config
        self.api = api_client
        self.checkpoints = checkpoint_store
        self.state = self._load_state()
        self.last_llm_call_ts = 0.0
        self.repo_root = Path(__file__).resolve().parents[2]
        self.llm = LlmProposalClient(
            LlmConfig(
                enabled=self.config.llm_enabled,
                use_legacy_interface=self.config.llm_use_legacy_interface,
                provider=self.config.llm_provider,
                endpoint=self.config.llm_endpoint,
                api_key=self.config.llm_api_key,
                model=self.config.llm_model,
                fallback_provider=self.config.llm_fallback_provider,
                fallback_endpoint=self.config.llm_fallback_endpoint,
                fallback_api_key=self.config.llm_fallback_api_key,
                fallback_model=self.config.llm_fallback_model,
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

    def _respect_llm_min_interval(self) -> None:
        min_interval = max(0, int(self.config.llm_min_interval_seconds))
        if min_interval <= 0 or self.last_llm_call_ts <= 0:
            return
        elapsed = time.time() - self.last_llm_call_ts
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)

    def _mark_llm_call_started(self) -> None:
        self.last_llm_call_ts = time.time()

    def _llm_error_details(self, error: Exception) -> dict[str, Any]:
        if isinstance(error, LlmGenerationError):
            return error.details if isinstance(error.details, dict) else {}
        details = getattr(error, "details", None)
        return details if isinstance(details, dict) else {}

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
        # Aprofitem el heartbeat per processar rebuigs d'entrenament
        self._process_training_rejections()

    def _process_training_rejections(self) -> None:
        run_id = self.state.run_id
        if not run_id:
            return
        try:
            proposals = self.api.list_model_proposals(limit=300)
        except Exception:
            return
        for proposal in proposals:
            if str(proposal.get("source_run_id", "")) != run_id:
                continue
            if str(proposal.get("status", "")) != "rejected":
                continue
            llm_metadata = proposal.get("llm_metadata") if isinstance(proposal.get("llm_metadata"), dict) else {}
            if "training_error" not in llm_metadata:
                continue
            if llm_metadata.get("repair_exhausted") is True:
                continue
            if llm_metadata.get("repair_replacement_proposal_id") or llm_metadata.get("phase0_repair_replacement_proposal_id"):
                continue
            if int(llm_metadata.get("repair_depth", 0) or 0) >= 1:
                continue
            try:
                self._attempt_repair_rejected_training_proposal(proposal)
            except Exception as e:
                print(f"⚠️ Error intentant reparar fallada d'entrenament a {proposal.get('proposal_id')}: {e}")

    def _attempt_repair_rejected_training_proposal(self, proposal: dict[str, Any]) -> None:
        run_id = self.state.run_id
        if not run_id:
            return
        proposal_id = str(proposal.get("proposal_id", "")).strip()
        llm_metadata = proposal.get("llm_metadata") if isinstance(proposal.get("llm_metadata"), dict) else {}
        error_message = str(llm_metadata.get("training_error", "Unknown training error"))
        
        print(f"🛠️ Reparant fallada d'entrenament per {proposal.get('proposal_id')}: {error_message[:100]}...")
        
        # Lògica de context per a l'LLM
        references, selection_trace = self._collect_reference_models_for_prompt(run_id)
        recent_generated_models = self._collect_recent_generated_models(run_id)
        context = {
            "generation": int(llm_metadata.get("from_generation", 0) or 0),
            "run_id": run_id,
            "code_version": self.config.code_version,
            "reference_models": references,
            "reference_selection_trace": selection_trace,
            "recent_generated_models": recent_generated_models,
            "latest_metrics": {},
        }
        original_candidate = {
            "base_model_id": str(proposal.get("base_model_id", "")).strip() or "repair_base_model",
            "proposal": proposal.get("proposal") if isinstance(proposal.get("proposal"), dict) else {},
            "llm_metadata": llm_metadata,
        }

        # Intentem reparar o reemplaçar (mateixa lògica que phase0 però per training)
        self._respect_llm_min_interval()
        self._mark_llm_call_started()
        try:
            # Primer intent de reparació directa
            candidate_to_submit = self.llm._repair_candidate_after_validation_error(original_candidate, error_message, context)
            if candidate_to_submit:
                self._submit_training_repaired_candidate(run_id, proposal, candidate_to_submit, error_message, "repair", 1)
            else:
                # Si falla la reparació, provem un reemplaçament total
                self._respect_llm_min_interval()
                self._mark_llm_call_started()
                candidate_to_submit = self.llm.generate_candidate(context)
                if candidate_to_submit:
                    self._submit_training_repaired_candidate(run_id, proposal, candidate_to_submit, error_message, "replacement", 2)
                else:
                    self.api.update_proposal_status(proposal_id, str(proposal.get("status", "rejected")), {"repair_exhausted": True, "repair_attempts_total": 2, "repair_last_error": error_message})
                    self.api.add_event(run_id, "training_repair_exhausted", f"Repair/replacement esgotat per {proposal_id}", {"proposal_id": proposal_id, "error": error_message})
        except Exception as e:
            print(f"❌ Fallida crítica en la reparació de training per {proposal.get('proposal_id')}: {e}")
            if proposal_id != "":
                try:
                    self.api.update_proposal_status(proposal_id, str(proposal.get("status", "rejected")), {"repair_exhausted": True, "repair_last_error": str(e)})
                except Exception:
                    pass

    def _submit_training_repaired_candidate(self, run_id: str, original_proposal: dict[str, Any], candidate: dict[str, Any], error_message: str, mode: str, attempt: int) -> None:
        # Reutilitzem la lògica de submissió de phase0 adaptada
        repair_depth = int(original_proposal.get("llm_metadata", {}).get("repair_depth", 0))
        created_id = self._submit_phase0_repaired_candidate(run_id, original_proposal, candidate, error_message, repair_depth, mode, attempt)
        if created_id:
            print(f"✅ Reemplaç d'entrenament enviat: {created_id} (per {original_proposal.get('proposal_id')})")

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
        if generation == 0:
            self.api.add_event(run_id, "generation_baseline_ready", "Generació 0 reservada per models base o champions previs")
        else:
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

    def _collect_reference_models_for_prompt(self, run_id: str) -> tuple[list[dict[str, object]], dict[str, Any]]:
        max_refs = max(0, int(self.config.llm_num_reference_models))
        if max_refs <= 0:
            return [], {"policy_version": "selection_policy_v1", "selected": [], "rejected": []}

        references: list[dict[str, object]] = []
        selected_trace: list[dict[str, Any]] = []
        rejected_trace: list[dict[str, Any]] = []
        policy = load_policy_config_from_env()
        try:
            proposals = self.api.list_model_proposals(limit=300)
            ranked: list[tuple[float, dict[str, object], dict[str, Any]]] = []
            for proposal in proposals:
                payload = proposal.get("proposal")
                if not isinstance(payload, dict):
                    continue
                model_definition = payload.get("model_definition")
                if not isinstance(model_definition, dict):
                    continue
                decision = evaluate_reference_candidate(proposal, config=policy)
                if not bool(decision.get("eligible")):
                    rejected_trace.append(
                        {
                            "proposal_id": str(proposal.get("proposal_id", "")),
                            "status": str(proposal.get("status", "")),
                            "selection_reason": str(decision.get("selection_reason", "")),
                            "constraints_failed": decision.get("constraints_failed", []),
                            "score": decision.get("score"),
                        }
                    )
                    continue
                score = float(decision.get("score", 0.0))
                reference: dict[str, object] = dict(model_definition)
                reference["model_id"] = str(model_definition.get("model_id", proposal.get("proposal_id", "unknown_model")))
                reference["reference_status"] = str(proposal.get("status", ""))
                reference["reference_source_run_id"] = str(proposal.get("source_run_id", ""))
                reference["selection_score"] = score
                reference["selection_reason"] = str(decision.get("selection_reason", ""))
                reference["score_breakdown"] = decision.get("score_breakdown", {})
                ranked.append((score, reference, decision))
            ranked.sort(key=lambda item: item[0], reverse=True)
            top = ranked[:max_refs]
            references = [item[1] for item in top]
            selected_trace = [
                {
                    "proposal_id": str(item[2].get("proposal_id", "")),
                    "score": item[2].get("score"),
                    "selection_reason": item[2].get("selection_reason", ""),
                    "score_breakdown": item[2].get("score_breakdown", {}),
                }
                for item in top
            ]
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
                        {"count": len(fallback), "reason": "no_eligible_ranked_models"},
                    )
                return fallback, {
                    "policy_version": str(policy.get("policy_version", "selection_policy_v1")),
                    "selected": [
                        {
                            "proposal_id": "local_seed",
                            "score": None,
                            "selection_reason": "local_fallback",
                        }
                    ],
                    "rejected": rejected_trace[:10],
                    "fallback_used": True,
                }
        return references, {
            "policy_version": str(policy.get("policy_version", "selection_policy_v1")),
            "selected": selected_trace,
            "rejected": rejected_trace[:10],
            "fallback_used": False,
        }

    def _create_model_proposal_if_enabled(
        self,
        run_id: str,
        generation: int,
        metrics: dict[str, float | int],
        specific_candidate_index: int | None = None,
        candidates_expected: int | None = None,
    ) -> int:
        if not self.config.llm_enabled:
            return 0
        proposals_per_generation = max(1, int(self.config.llm_num_new_models))
        effective_candidates_expected = max(1, int(candidates_expected or proposals_per_generation))
        if specific_candidate_index is None:
            candidate_numbers = list(range(1, proposals_per_generation + 1))
        else:
            candidate_number = max(1, int(specific_candidate_index))
            if candidate_number > effective_candidates_expected:
                return 0
            candidate_numbers = [candidate_number]
        reference_models, reference_trace = self._collect_reference_models_for_prompt(run_id)
        recent_generated_models = self._collect_recent_generated_models(run_id)
        created_count = 0

        for candidate_number in candidate_numbers:
            self._respect_llm_min_interval()

            context = {
                "run_id": run_id,
                "generation": generation,
                "latest_metrics": metrics,
                "code_version": self.config.code_version,
                "reference_models": reference_models,
                "reference_selection_trace": reference_trace,
                "recent_generated_models": recent_generated_models,
                "candidate_index": candidate_number,
                "candidates_expected": effective_candidates_expected,
            }

            try:
                self._mark_llm_call_started()
                print(
                    f"🤖 Fent petició al LLM per generar proposta {candidate_number}/{effective_candidates_expected} "
                    f"de la generació {generation}."
                )
                candidate = self.llm.generate_candidate(context)
                print(f"📩 Resposta rebuda de l'LLM per generació {generation} candidat {candidate_number}")
                if not candidate:
                    print(f"⚠️ L'LLM no ha retornat cap proposta útil per generació {generation} candidat {candidate_number}")
                    continue
                base_model_id = str(candidate.get("base_model_id", "")).strip() or "unknown_base_model"
                proposal = candidate.get("proposal")
                if not isinstance(proposal, dict) or len(proposal) == 0:
                    raise RuntimeError("LLM candidate proposal is invalid")
                llm_metadata = candidate.get("llm_metadata")
                llm_metadata_payload = llm_metadata if isinstance(llm_metadata, dict) else {}
                llm_metadata_payload["from_generation"] = generation
                llm_metadata_payload["candidate_index"] = candidate_number
                llm_metadata_payload["candidates_expected"] = effective_candidates_expected
                proposal_fingerprint = self.llm.proposal_fingerprint(proposal)
                llm_metadata_payload["proposal_fingerprint"] = proposal_fingerprint

                if self._proposal_fingerprint_exists(run_id, proposal_fingerprint):
                    print(f"🪞 Proposta duplicada descartada per fingerprint a generació {generation} candidat {candidate_number}")
                    self.api.add_event(
                        run_id,
                        "llm_duplicate_skipped",
                        f"Proposta duplicada descartada a generació {generation}",
                        {
                            "proposal_fingerprint": proposal_fingerprint,
                            "candidate_index": candidate_number,
                            "candidates_expected": effective_candidates_expected,
                        },
                    )
                    continue

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
                    print(f"🧩 Proposal creada i enviada a phase0: {proposal_id} (gen={generation}, candidat={candidate_number})")
                    recent_generated_models.insert(0, {
                        "proposal_id": proposal_id,
                        "fingerprint": proposal_fingerprint,
                        "summary": self._summarize_model_definition(proposal),
                    })
                    recent_generated_models = recent_generated_models[:5]
                    created_count += 1
                self.api.add_event(
                    run_id,
                    "llm_proposal_created",
                    f"Proposta LLM creada a generació {generation}",
                    {
                        "proposal_id": proposal_id,
                        "base_model_id": base_model_id,
                        "candidate_index": candidate_number,
                        "candidates_expected": effective_candidates_expected,
                    },
                )
            except LlmRateLimitError as error:
                print(f"⛔ Rate limit LLM a generació {generation} candidat {candidate_number}: {error}")
                self.api.add_event(
                    run_id,
                    "llm_rate_limited",
                    f"Rate limit LLM a generació {generation}",
                    {
                        "error": str(error),
                        "candidate_index": candidate_number,
                        "candidates_expected": effective_candidates_expected,
                    },
                )
                raise
            except Exception as error:
                print(f"❌ Error generant proposta a generació {generation} candidat {candidate_number}: {error}")
                diagnostic_details = self._llm_error_details(error)
                self.api.add_event(
                    run_id,
                    "llm_proposal_error",
                    f"Error creant proposta LLM a generació {generation}",
                    {
                        "error": str(error),
                        "candidate_index": candidate_number,
                        "candidates_expected": effective_candidates_expected,
                        "llm_error_details": diagnostic_details,
                    },
                )
        return created_count

    def _collect_recent_generated_models(self, run_id: str) -> list[dict[str, str]]:
        recent: list[dict[str, str]] = []
        try:
            proposals = self.api.list_model_proposals(limit=200)
        except Exception:
            return recent
        for proposal in proposals:
            if str(proposal.get("source_run_id", "")) != run_id:
                continue
            llm_metadata = proposal.get("llm_metadata") if isinstance(proposal.get("llm_metadata"), dict) else {}
            fingerprint = str(llm_metadata.get("proposal_fingerprint", "")).strip()
            if fingerprint == "":
                continue
            recent.append({
                "proposal_id": str(proposal.get("proposal_id", "")),
                "fingerprint": fingerprint,
                "summary": self._summarize_model_definition(proposal.get("proposal") if isinstance(proposal.get("proposal"), dict) else {}),
            })
        return recent[:5]

    def _proposal_fingerprint_exists(self, run_id: str, fingerprint: str) -> bool:
        try:
            proposals = self.api.list_model_proposals(limit=300)
        except Exception:
            return False
        for proposal in proposals:
            if str(proposal.get("source_run_id", "")) != run_id:
                continue
            llm_metadata = proposal.get("llm_metadata") if isinstance(proposal.get("llm_metadata"), dict) else {}
            if str(llm_metadata.get("proposal_fingerprint", "")) == fingerprint:
                return True
        return False

    def _summarize_model_definition(self, proposal: dict[str, object]) -> str:
        model_definition = proposal.get("model_definition") if isinstance(proposal, dict) else None
        if not isinstance(model_definition, dict):
            return "unknown"
        architecture = model_definition.get("architecture_definition") if isinstance(model_definition.get("architecture_definition"), dict) else {}
        branches = architecture.get("branches") if isinstance(architecture.get("branches"), list) else []
        merges = architecture.get("merges") if isinstance(architecture.get("merges"), list) else []
        output_heads = architecture.get("output_heads") if isinstance(architecture.get("output_heads"), list) else []
        branch_types: list[str] = []
        for branch in branches[:3]:
            if not isinstance(branch, dict):
                continue
            layers = branch.get("layers") if isinstance(branch.get("layers"), list) else []
            first_type = ""
            for layer in layers:
                if isinstance(layer, dict) and isinstance(layer.get("type"), str):
                    first_type = str(layer.get("type"))
                    break
            if first_type:
                branch_types.append(first_type)
        return f"branches={len(branches)}({','.join(branch_types)}) merges={len(merges)} outputs={len(output_heads)}"

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
        # El Worker NOMÉS valida la phase0 estructural, no entrena.
        # Això evita que el Worker i el Trainer competeixin pels mateixos recursos.
        try:
            result = self.api.process_model_proposals_phase0(self.config.proposals_phase0_batch_size)
            processed_count = int(result.get("processed_count", 0))
            if processed_count > 0:
                self._handle_phase0_rejections(result)
        except Exception as error:
            print(f"⚠️ Error en processament automàtic de phase0: {error}")

    def _handle_phase0_rejections(self, result: dict[str, Any]) -> None:
        run_id = self.state.run_id
        if not run_id:
            return
        processed = result.get("processed") if isinstance(result.get("processed"), list) else []
        for item in processed:
            if not isinstance(item, dict):
                continue
            if str(item.get("status", "")) != "rejected":
                continue
            proposal_id = str(item.get("proposal_id", "")).strip()
            if proposal_id == "":
                continue
            try:
                proposal = self.api.get_model_proposal(proposal_id)
            except Exception:
                continue
            try:
                self._attempt_repair_rejected_phase0_proposal(proposal)
            except Exception as repair_error:
                print(f"⚠️ Repair phase0 fallit per {proposal_id}: {repair_error}")

    def _attempt_repair_rejected_phase0_proposal(self, proposal: dict[str, Any]) -> None:
        run_id = str(proposal.get("source_run_id", "")).strip() or self.state.run_id or ""
        if run_id == "":
            return
        llm_metadata_raw = proposal.get("llm_metadata")
        llm_metadata = llm_metadata_raw if isinstance(llm_metadata_raw, dict) else {}
        repair_depth = int(llm_metadata.get("repair_depth", 0) or 0)
        if repair_depth >= 1:
            return
        rejection_reason = str(llm_metadata.get("phase0_rejected_reason", "")).strip()
        phase0_auto = llm_metadata.get("phase0_auto") if isinstance(llm_metadata.get("phase0_auto"), dict) else {}
        if rejection_reason == "":
            errors = phase0_auto.get("errors") if isinstance(phase0_auto.get("errors"), list) else []
            rejection_reason = " | ".join(str(item) for item in errors if str(item).strip() != "")
        if rejection_reason == "":
            rejection_reason = "phase0_rejected"
        print(f"🛠️ Intentant reparar proposal rebutjada a phase0 {proposal.get('proposal_id', '')}: {rejection_reason}")
        self.api.add_event(
            run_id,
            "phase0_repair_started",
            f"Intentant reparar proposal rebutjada a phase0: {proposal.get('proposal_id', '')}",
            {"proposal_id": proposal.get("proposal_id"), "reason": rejection_reason},
        )
        references, selection_trace = self._collect_reference_models_for_prompt(run_id)
        recent_generated_models = self._collect_recent_generated_models(run_id)
        context = {
            "generation": int(llm_metadata.get("from_generation", 0) or 0),
            "run_id": run_id,
            "code_version": self.config.code_version,
            "reference_models": references,
            "reference_selection_trace": selection_trace,
            "recent_generated_models": recent_generated_models,
            "latest_metrics": {},
        }
        original_candidate = {
            "base_model_id": str(proposal.get("base_model_id", "")).strip() or "repair_base_model",
            "proposal": proposal.get("proposal") if isinstance(proposal.get("proposal"), dict) else {},
            "llm_metadata": llm_metadata,
        }
        max_attempts = max(3, int(os.getenv("V2_PHASE0_REPAIR_MAX_ATTEMPTS", "4")))
        retry_delay_seconds = max(
            1,
            int(os.getenv("V2_PHASE0_REPAIR_RETRY_DELAY_SECONDS", os.getenv("V2_LLM_MIN_INTERVAL_SECONDS", "30"))),
        )
        for attempt in range(max_attempts):
            mode = "repair" if attempt == 0 else "replacement"
            candidate_to_submit: dict[str, Any] | None = None
            try:
                self._respect_llm_min_interval()
                self._mark_llm_call_started()
                if attempt == 0:
                    candidate_to_submit = self.llm._repair_candidate_after_validation_error(original_candidate, rejection_reason, context)
                    print(f"🔧 Repair phase0 rebutjat rebut per {proposal.get('proposal_id', '')} (intent {attempt + 1})")
                else:
                    candidate_to_submit = self.llm.generate_candidate(context)
                    print(f"🆕 Reemplaç phase0 generat per {proposal.get('proposal_id', '')} (intent {attempt + 1})")
            except Exception as error:
                print(f"❌ Intent {attempt + 1} de phase0 repair/replacement fallit per {proposal.get('proposal_id', '')}: {error}")
                self.api.add_event(run_id, "phase0_repair_failed", f"Intent {attempt + 1} de repair/replacement fallit", {"proposal_id": proposal.get("proposal_id"), "attempt": attempt + 1, "mode": mode, "error": str(error), "llm_error_details": self._llm_error_details(error)})
                if attempt + 1 < max_attempts:
                    time.sleep(retry_delay_seconds)
                continue
            if not isinstance(candidate_to_submit, dict):
                if attempt + 1 < max_attempts:
                    time.sleep(retry_delay_seconds)
                continue
            created = self._submit_phase0_repaired_candidate(run_id, proposal, candidate_to_submit, rejection_reason, repair_depth, mode, attempt + 1)
            if created is not None:
                return
            if attempt + 1 < max_attempts:
                time.sleep(retry_delay_seconds)
        self.api.add_event(
            run_id,
            "phase0_repair_exhausted",
            f"No s'ha pogut reparar proposal rebutjada a phase0: {proposal.get('proposal_id', '')}",
            {"proposal_id": proposal.get("proposal_id"), "reason": rejection_reason, "attempts": max_attempts},
        )
        try:
            self.api.update_proposal_status(
                str(proposal.get("proposal_id", "")),
                str(proposal.get("status", "rejected")),
                {
                    "repair_exhausted": True,
                    "repair_attempts_total": max_attempts,
                    "repair_last_error": rejection_reason,
                },
            )
        except Exception:
            pass

    def _submit_phase0_repaired_candidate(
        self,
        run_id: str,
        original_proposal: dict[str, Any],
        candidate: dict[str, Any],
        rejection_reason: str,
        repair_depth: int,
        mode: str,
        attempt_number: int,
    ) -> str | None:
        base_model_id = str(candidate.get("base_model_id", original_proposal.get("base_model_id", "repair_base_model"))).strip() or "repair_base_model"
        proposal_payload = candidate.get("proposal") if isinstance(candidate.get("proposal"), dict) else {}
        if not proposal_payload:
            return None
        llm_metadata_raw = candidate.get("llm_metadata")
        llm_metadata = llm_metadata_raw if isinstance(llm_metadata_raw, dict) else {}
        original_metadata_raw = original_proposal.get("llm_metadata")
        original_metadata = original_metadata_raw if isinstance(original_metadata_raw, dict) else {}
        original_generation = int(original_metadata.get("from_generation", -1) or -1)
        if original_generation >= 0:
            llm_metadata["from_generation"] = original_generation
        llm_metadata["repair_depth"] = repair_depth + 1
        llm_metadata["repaired_from_proposal_id"] = str(original_proposal.get("proposal_id", ""))
        llm_metadata["repair_source_error"] = rejection_reason
        llm_metadata["repair_mode"] = mode
        llm_metadata["repair_attempt"] = attempt_number
        fingerprint = self.llm.proposal_fingerprint(proposal_payload)
        llm_metadata["proposal_fingerprint"] = fingerprint
        if self._proposal_fingerprint_exists(run_id, fingerprint):
            self.api.add_event(
                run_id,
                "phase0_repair_duplicate_skipped",
                "Proposal reparada duplicada descartada",
                {"proposal_id": original_proposal.get("proposal_id"), "repair_mode": mode, "attempt": attempt_number},
            )
            return None
        created = self.api.create_model_proposal(
            source_run_id=run_id,
            base_model_id=base_model_id,
            proposal=proposal_payload,
            llm_metadata=llm_metadata,
        )
        proposal_id = str(created.get("proposal_id", "")).strip()
        if proposal_id == "":
            return None
        self.api.enqueue_model_proposal_phase0(proposal_id)
        try:
            self.api.process_model_proposals_phase0(limit=1)
        except Exception:
            pass
        refreshed = self.api.get_model_proposal(proposal_id)
        refreshed_status = str(refreshed.get("status", ""))
        if refreshed_status == "validated_phase0":
            print(f"✅ Proposal reparada a phase0 validada: {proposal_id}")
            try:
                self.api.update_proposal_status(
                    str(original_proposal.get("proposal_id", "")),
                    str(original_proposal.get("status", "rejected")),
                    {
                        "repair_replacement_proposal_id": proposal_id,
                        "repair_attempts_total": attempt_number,
                        "repair_last_mode": mode,
                        "repair_last_attempt": attempt_number,
                        "repair_exhausted": False,
                        "phase0_repair_replacement_proposal_id": proposal_id,
                        "phase0_repair_last_mode": mode,
                        "phase0_repair_last_attempt": attempt_number,
                    },
                )
            except Exception:
                pass
            self.api.add_event(
                run_id,
                "model_repair_enqueued",
                f"Proposal reparada i reenviada a phase0: {proposal_id}",
                {"original_proposal_id": original_proposal.get("proposal_id"), "repaired_proposal_id": proposal_id, "mode": mode, "attempt": attempt_number},
            )
            return proposal_id
        self.api.add_event(
            run_id,
            "phase0_repair_failed",
            f"Proposal reparada rebutjada a phase0: {proposal_id}",
            {"original_proposal_id": original_proposal.get("proposal_id"), "repaired_proposal_id": proposal_id, "status": refreshed_status, "mode": mode, "attempt": attempt_number},
        )
        return None

    def _target_models_total(self) -> int:
        configured = int(getattr(self.config, "target_models_total", 0) or 0)
        if configured > 0:
            return configured
        models_per_generation = max(1, int(self.config.llm_num_new_models))
        return max(1, int(self.config.max_generations) * models_per_generation)

    def _active_buffer_target(self, target_models_total: int) -> int:
        configured = int(getattr(self.config, "active_buffer_target", 0) or 0)
        if configured > 0:
            return max(1, min(configured, max(1, target_models_total)))
        models_per_generation = max(1, int(self.config.llm_num_new_models))
        return max(1, min(max(2, models_per_generation * 2), max(1, target_models_total)))

    def _next_generation_labels(self, proposal_sequence: int) -> tuple[int, int, int]:
        candidates_expected = max(1, int(self.config.llm_num_new_models))
        normalized_sequence = max(1, proposal_sequence)
        generation_label = ((normalized_sequence - 1) // candidates_expected) + 1
        candidate_index = ((normalized_sequence - 1) % candidates_expected) + 1
        return generation_label, candidate_index, candidates_expected

    def _emit_progress_snapshot(self, run_id: str, counts: dict[str, int], stage: str, stage_label: str) -> None:
        target_models_total = self._target_models_total()
        buffer_target = self._active_buffer_target(target_models_total)
        payload = {
            "progress_event": True,
            "run_id": run_id,
            "current_run_id": run_id,
            "run_ids": [run_id],
            "stage": stage,
            "stage_label": stage_label,
            "generations_completed": int(self.state.generation),
            "generations_total": max(1, int(self.config.max_generations)),
            "models_generated": int(counts.get("scheduled", counts.get("total", 0))),
            "models_trained": int(counts.get("trained", 0)),
            "models_rejected": int(counts.get("rejected", 0)),
            "active_models_count": int(counts.get("active", 0)),
            "target_models_total": target_models_total,
            "active_buffer_target": buffer_target,
        }
        print(json.dumps(payload, ensure_ascii=True), flush=True)

    def _replenish_active_buffer(self, run_id: str, counts: dict[str, int], target_models_total: int, buffer_target: int) -> int:
        trained_count = int(counts.get("trained", 0))
        active_count = int(counts.get("active", 0))
        training_count = int(counts.get("training", 0))
        scheduled_count = int(counts.get("scheduled", counts.get("total", 0)))
        remaining_needed = max(0, target_models_total - trained_count)
        if remaining_needed <= 0:
            return 0
        pending_capacity_needed = max(0, target_models_total - trained_count - active_count)
        if pending_capacity_needed <= 0:
            return 0
        effective_buffer_target = buffer_target
        if trained_count <= 0 and training_count <= 0:
            effective_buffer_target = min(buffer_target, 2)
        buffer_gap = max(0, effective_buffer_target - active_count)
        if buffer_gap <= 0:
            return 0
        creation_budget = min(buffer_gap, pending_capacity_needed, 2)
        created_total = 0
        for _ in range(creation_budget):
            proposal_sequence = scheduled_count + created_total + 1
            generation_label, candidate_index, candidates_expected = self._next_generation_labels(proposal_sequence)
            simulated_metric = {
                "val_loss_total": round(1.0 / (generation_label + 1), 6),
                "models_evaluated": max(1, counts.get("trained", 0)),
            }
            print(
                f"🔁 Reomplint buffer: proposta {proposal_sequence}/{target_models_total} "
                f"(Gen {generation_label}, Cand {candidate_index}, active={active_count + created_total}/{effective_buffer_target})..."
            )
            created_now = self._create_model_proposal_if_enabled(
                run_id,
                generation_label,
                simulated_metric,
                specific_candidate_index=candidate_index,
                candidates_expected=candidates_expected,
            )
            if created_now <= 0:
                continue
            created_total += created_now
            self.state.generation = max(self.state.generation, generation_label)
            self.state.stage = "buffer_replenished"
            self._save_state()
        return created_total

    def _get_run_global_counts(self, run_id: str) -> dict[str, int]:
        """Compta l'estat global de tots els models de la run."""
        active_statuses = {"draft", "queued_phase0", "validated_phase0", "accepted", "training"}
        counts = {
            "total": 0,
            "scheduled": 0,
            "active": 0,
            "trained": 0,
            "rejected": 0,
            "draft": 0,
            "queued_phase0": 0,
            "validated_phase0": 0,
            "accepted": 0,
            "training": 0,
        }
        try:
            proposals = self.api.list_model_proposals(limit=1000)
        except Exception:
            return counts
        for proposal in proposals:
            if str(proposal.get("source_run_id", "")) != run_id:
                continue
            counts["total"] += 1
            llm_metadata = proposal.get("llm_metadata") if isinstance(proposal.get("llm_metadata"), dict) else {}
            if llm_metadata.get("seed_bootstrap") is not True:
                counts["scheduled"] += 1
            status = str(proposal.get("status", ""))
            if status in active_statuses:
                counts["active"] += 1
                if status in counts:
                    counts[status] += 1
            elif status == "trained":
                counts["trained"] += 1
            elif status == "rejected":
                counts["rejected"] += 1
        return counts

    def run(self) -> None:
        self._ensure_run()
        run_id = self.state.run_id
        if not run_id:
            raise RuntimeError("run_id not available")

        final_status = "completed"
        final_label = "Execució finalitzada"

        # 1. Inici de la sessió
        if self.state.status == "completed":
            print("🏁 Run ja completada.")
            return

        self._verify_legacy_model_build_if_enabled()
        self._bootstrap_seed_model_if_needed(run_id)
        # El Worker NOMÉS valida la phase0 estructural, no entrena
        self._process_queued_proposals_phase0_if_enabled()
        self.api.update_status(run_id, "running", self.state.generation)

        # 2. Scheduler continu basat en target i buffer
        target_models_total = self._target_models_total()
        active_buffer_target = self._active_buffer_target(target_models_total)

        last_maintenance = 0.0
        print(
            f"🌊 Iniciant scheduler continu supervisat. "
            f"Target={target_models_total} models entrenats, buffer={active_buffer_target}."
        )

        try:
            while True:
                now = time.time()

                # Manteniment periòdic (Heartbeat, Repairs)
                if now - last_maintenance >= self.config.heartbeat_interval_seconds:
                    self._send_heartbeat()
                    # El Worker valida la phase0 de les propostes que ell mateix crea
                    self._process_queued_proposals_phase0_if_enabled()
                    self._process_training_rejections()
                    last_maintenance = now

                # Estat global i progress operatiu
                counts = self._get_run_global_counts(run_id)
                trained_count = counts["trained"]
                active_count = counts["active"]
                self._emit_progress_snapshot(
                    run_id,
                    counts,
                    stage="running",
                    stage_label=f"trained={trained_count}/{target_models_total} · active={active_count}/{active_buffer_target}",
                )

                if trained_count >= target_models_total and active_count == 0:
                    print(f"✅ Target assolit i cua drenada: {trained_count}/{target_models_total} models entrenats.")
                    break

                self._replenish_active_buffer(run_id, counts, target_models_total, active_buffer_target)
                time.sleep(10)
        except LlmRateLimitError as error:
            final_status = "failed"
            final_label = "Execució aturada per rate limit LLM"
            self.api.add_event(run_id, "run_failed", final_label, {"error": str(error), "fatal_error": "llm_rate_limited"})
            print(
                json.dumps(
                    {
                        "progress_event": True,
                        "run_id": run_id,
                        "fatal_error": "llm_rate_limited",
                        "stop_worker_loop": True,
                        "stage": "failed",
                        "stage_label": final_label,
                    },
                    ensure_ascii=True,
                ),
                flush=True,
            )
            raise
        except KeyboardInterrupt:
            print("\n👋 Worker interromput per l'usuari.")
            final_status = "cancelled"
            final_label = "Execució interrompuda per l'usuari"
        except Exception as error:
            final_status = "failed"
            final_label = "Execució fallida"
            try:
                self.api.add_event(run_id, "run_failed", final_label, {"error": str(error)})
            except Exception:
                pass
            raise
        finally:
            self.api.update_status(run_id, final_status, self.state.generation)
            if final_status == "completed":
                self.api.add_event(run_id, "run_completed", final_label)
            counts = self._get_run_global_counts(run_id)
            self._emit_progress_snapshot(run_id, counts, stage=final_status, stage_label=final_label)
            self.state.status = final_status
            self.state.stage = "finished"
            self._save_state()
