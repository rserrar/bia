from __future__ import annotations

import os
import time
import json
import copy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from shared.utils.selection_policy import evaluate_reference_candidate, load_policy_config_from_env

try:
    from .api_client import ApiClient
    from .checkpoint_store import CheckpointStore
    from .config import WorkerConfig
    from .legacy_model_compat import build_legacy_model_once
    from .llm_client import LlmConfig, LlmProposalClient, LlmRateLimitError
except ImportError:
    from api_client import ApiClient
    from checkpoint_store import CheckpointStore
    from config import WorkerConfig
    from legacy_model_compat import build_legacy_model_once
    from llm_client import LlmConfig, LlmProposalClient, LlmRateLimitError


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

    def _generation_proposal_counts(self, run_id: str, generation: int) -> dict[str, int]:
        active_statuses = {"draft", "queued_phase0", "validated_phase0", "accepted", "training"}
        counts = {"total": 0, "active": 0, "training": 0, "trained": 0, "rejected": 0}
        try:
            proposals = self.api.list_model_proposals(limit=500)
        except Exception:
            return counts
        for proposal in proposals:
            if str(proposal.get("source_run_id", "")) != run_id:
                continue
            llm_metadata = proposal.get("llm_metadata") if isinstance(proposal.get("llm_metadata"), dict) else {}
            proposal_generation = int(llm_metadata.get("from_generation", -1) or -1)
            if proposal_generation != generation:
                continue
            counts["total"] += 1
            status = str(proposal.get("status", ""))
            if status in active_statuses:
                counts["active"] += 1
            if status == "training":
                counts["training"] += 1
            elif status == "trained":
                counts["trained"] += 1
            elif status == "rejected":
                counts["rejected"] += 1
        return counts

    def _wait_for_generation_to_drain(self, run_id: str, generation: int, prefetch_generation: int | None = None) -> int | None:
        timeout_seconds = max(60, int(os.getenv("V2_WAIT_FOR_GENERATION_DRAIN_SECONDS", "86400")))
        poll_seconds = max(5, int(os.getenv("V2_WAIT_FOR_GENERATION_DRAIN_POLL_SECONDS", "10")))
        started = time.time()
        prefetched_generation: int | None = None
        print(f"⏳ Esperant que la generació {generation} es buidi abans de continuar...")
        self.api.add_event(run_id, "generation_drain_wait_started", f"Esperant que la generació {generation} es buidi", {"generation": generation, "prefetch_generation": prefetch_generation})
        while True:
            self._send_heartbeat()
            self._process_queued_proposals_phase0_if_enabled()
            counts = self._generation_proposal_counts(run_id, generation)
            if counts["total"] == 0 or counts["active"] == 0:
                print(f"✅ Generació {generation} resolta: total={counts['total']} trained={counts['trained']} rejected={counts['rejected']}")
                self.api.add_event(run_id, "generation_drain_wait_completed", f"Generació {generation} buidada", {"generation": generation, **counts})
                return prefetched_generation
            if prefetch_generation is not None and prefetched_generation is None and counts["training"] == 1 and counts["active"] == 1:
                print(f"⚡ Prefetch de la generació {prefetch_generation} mentre es tanca la {generation}")
                self.api.add_event(run_id, "generation_prefetch_started", f"Prefetch generació {prefetch_generation} mentre es tanca la {generation}", {"current_generation": generation, "prefetch_generation": prefetch_generation, **counts})
                self._run_generation_step(prefetch_generation)
                prefetched_generation = prefetch_generation
            if time.time() - started > timeout_seconds:
                self.api.add_event(run_id, "generation_drain_wait_timeout", f"Timeout esperant generació {generation}", {"generation": generation, **counts})
                raise TimeoutError(f"generation {generation} did not drain for run {run_id}: {counts}")
            time.sleep(poll_seconds)

    def _create_model_proposal_if_enabled(self, run_id: str, generation: int, metrics: dict[str, float | int]) -> None:
        if not self.config.llm_enabled:
            return
        proposals_per_generation = max(1, int(self.config.llm_num_new_models))
        reference_models, reference_trace = self._collect_reference_models_for_prompt(run_id)
        recent_generated_models = self._collect_recent_generated_models(run_id)

        for candidate_index in range(proposals_per_generation):
            self._respect_llm_min_interval()

            context = {
                "run_id": run_id,
                "generation": generation,
                "latest_metrics": metrics,
                "code_version": self.config.code_version,
                "reference_models": reference_models,
                "reference_selection_trace": reference_trace,
                "recent_generated_models": recent_generated_models,
                "candidate_index": candidate_index + 1,
                "candidates_expected": proposals_per_generation,
            }

            try:
                self._mark_llm_call_started()
                print(
                    f"🤖 Fent petició al LLM per generar proposta {candidate_index + 1}/{proposals_per_generation} "
                    f"de la generació {generation}."
                )
                candidate = self.llm.generate_candidate(context)
                print(f"📩 Resposta rebuda de l'LLM per generació {generation} candidat {candidate_index + 1}")
                if not candidate:
                    print(f"⚠️ L'LLM no ha retornat cap proposta útil per generació {generation} candidat {candidate_index + 1}")
                    continue
                base_model_id = str(candidate.get("base_model_id", "")).strip() or "unknown_base_model"
                proposal = candidate.get("proposal")
                if not isinstance(proposal, dict) or len(proposal) == 0:
                    raise RuntimeError("LLM candidate proposal is invalid")
                llm_metadata = candidate.get("llm_metadata")
                llm_metadata_payload = llm_metadata if isinstance(llm_metadata, dict) else {}
                llm_metadata_payload["from_generation"] = generation
                llm_metadata_payload["candidate_index"] = candidate_index + 1
                llm_metadata_payload["candidates_expected"] = proposals_per_generation
                proposal_fingerprint = self.llm.proposal_fingerprint(proposal)
                llm_metadata_payload["proposal_fingerprint"] = proposal_fingerprint

                if self._proposal_fingerprint_exists(run_id, proposal_fingerprint):
                    print(f"🪞 Proposta duplicada descartada per fingerprint a generació {generation} candidat {candidate_index + 1}")
                    self.api.add_event(
                        run_id,
                        "llm_duplicate_skipped",
                        f"Proposta duplicada descartada a generació {generation}",
                        {
                            "proposal_fingerprint": proposal_fingerprint,
                            "candidate_index": candidate_index + 1,
                            "candidates_expected": proposals_per_generation,
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
                    print(f"🧩 Proposal creada i enviada a phase0: {proposal_id} (gen={generation}, candidat={candidate_index + 1})")
                    recent_generated_models.insert(0, {
                        "proposal_id": proposal_id,
                        "fingerprint": proposal_fingerprint,
                        "summary": self._summarize_model_definition(proposal),
                    })
                    recent_generated_models = recent_generated_models[:5]
                self.api.add_event(
                    run_id,
                    "llm_proposal_created",
                    f"Proposta LLM creada a generació {generation}",
                    {
                        "proposal_id": proposal_id,
                        "base_model_id": base_model_id,
                        "candidate_index": candidate_index + 1,
                        "candidates_expected": proposals_per_generation,
                    },
                )
            except LlmRateLimitError as error:
                print(f"⛔ Rate limit LLM a generació {generation} candidat {candidate_index + 1}: {error}")
                self.api.add_event(
                    run_id,
                    "llm_rate_limited",
                    f"Rate limit LLM a generació {generation}",
                    {
                        "error": str(error),
                        "candidate_index": candidate_index + 1,
                        "candidates_expected": proposals_per_generation,
                    },
                )
                raise
            except Exception as error:
                print(f"❌ Error generant proposta a generació {generation} candidat {candidate_index + 1}: {error}")
                self.api.add_event(
                    run_id,
                    "llm_proposal_error",
                    f"Error creant proposta LLM a generació {generation}",
                    {
                        "error": str(error),
                        "candidate_index": candidate_index + 1,
                        "candidates_expected": proposals_per_generation,
                    },
                )

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
        try:
            result = self.api.process_model_proposals_phase0(self.config.proposals_phase0_batch_size)
            processed_count = int(result.get("processed_count", 0))
            if processed_count > 0:
                self._handle_phase0_rejections(result)
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
        retry_delay_seconds = max(1, int(os.getenv("V2_PHASE0_REPAIR_RETRY_DELAY_SECONDS", "5")))
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
                self.api.add_event(run_id, "phase0_repair_failed", f"Intent {attempt + 1} de repair/replacement fallit", {"proposal_id": proposal.get("proposal_id"), "attempt": attempt + 1, "mode": mode, "error": str(error)})
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

    def _pending_training_counts(self, run_id: str) -> dict[str, int]:
        active_statuses = {"draft", "queued_phase0", "validated_phase0", "accepted", "training"}
        counts = {"total": 0, "active": 0, "trained": 0, "rejected": 0}
        try:
            proposals = self.api.list_model_proposals(limit=500)
        except Exception:
            return counts
        for proposal in proposals:
            if str(proposal.get("source_run_id", "")) != run_id:
                continue
            counts["total"] += 1
            status = str(proposal.get("status", ""))
            if status in active_statuses:
                counts["active"] += 1
            elif status == "trained":
                counts["trained"] += 1
            elif status == "rejected":
                counts["rejected"] += 1
        return counts

    def _wait_for_training_queue_to_drain(self, run_id: str) -> None:
        timeout_seconds = max(60, int(os.getenv("V2_WAIT_FOR_TRAINING_DRAIN_SECONDS", "86400")))
        poll_seconds = max(5, int(os.getenv("V2_WAIT_FOR_TRAINING_DRAIN_POLL_SECONDS", "10")))
        started = time.time()
        self.api.add_event(run_id, "training_drain_wait_started", "Esperant que s'acabi la cua d'entrenament", {"timeout_seconds": timeout_seconds})
        while True:
            self._send_heartbeat()
            self._process_queued_proposals_phase0_if_enabled()
            counts = self._pending_training_counts(run_id)
            if counts["total"] > 0 and counts["active"] == 0:
                self.api.add_event(run_id, "training_drain_wait_completed", "Cua d'entrenament buidada", counts)
                return
            if time.time() - started > timeout_seconds:
                self.api.add_event(run_id, "training_drain_wait_timeout", "Timeout esperant la cua d'entrenament", counts)
                raise TimeoutError(f"training queue did not drain for run {run_id}: {counts}")
            time.sleep(poll_seconds)

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
        if self.state.generation == 0:
            self._run_generation_step(0)
            print("🪜 Generació 0 completada com a baseline; les propostes noves comencen a la generació 1")
        next_generation = max(1, self.state.generation)
        prefetched_generation: int | None = None
        while next_generation <= self.config.max_generations:
            now = time.time()
            if now - last_heartbeat >= self.config.heartbeat_interval_seconds:
                self._send_heartbeat()
                self._process_queued_proposals_phase0_if_enabled()
                last_heartbeat = now
            current_generation = next_generation
            if prefetched_generation == current_generation:
                prefetched_generation = None
            else:
                self._run_generation_step(current_generation)
            self._process_queued_proposals_phase0_if_enabled()
            prefetch_target = current_generation + 1 if current_generation < self.config.max_generations else None
            prefetched_generation = self._wait_for_generation_to_drain(run_id, current_generation, prefetch_target)
            next_generation = current_generation + 1
            time.sleep(1)
        self._process_queued_proposals_phase0_if_enabled()
        self._wait_for_training_queue_to_drain(run_id)
        self.api.update_status(run_id, "completed", self.state.generation)
        self.api.add_event(run_id, "run_completed", "Execució finalitzada")
        self.state.status = "completed"
        self.state.stage = "finished"
        self._save_state()
