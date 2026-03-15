from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any


def _v2_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_path(path_str: str, project_root: Path) -> Path:
    raw = Path(path_str)
    if raw.is_absolute():
        return raw
    return (project_root / raw).resolve()


def _load_reference_models(project_root: Path) -> tuple[list[dict[str, Any]], str]:
    path = os.getenv("V2_PROMPT_REFERENCE_MODEL_PATH", "models/base/model_exemple_complex_v1.json").strip()
    if path == "":
        return [], ""
    ref_path = _resolve_path(path, project_root)
    if not ref_path.exists():
        return [], str(ref_path)
    try:
        data = json.loads(ref_path.read_text(encoding="utf-8"))
    except Exception:
        return [], str(ref_path)
    if isinstance(data, dict):
        return [data], str(ref_path)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)], str(ref_path)
    return [], str(ref_path)


def main() -> int:
    v2_root = _v2_root()
    project_root = _project_root()
    if not (v2_root / "colab-worker" / "src").exists() and (project_root / "V2" / "colab-worker" / "src").exists():
        v2_root = (project_root / "V2").resolve()
    if not (project_root / "prompts").exists() and (v2_root / "prompts").exists():
        project_root = v2_root
    elif not (project_root / "prompts").exists() and (v2_root.parent / "prompts").exists():
        project_root = v2_root.parent
    worker_src = v2_root / "colab-worker" / "src"
    if str(worker_src) not in sys.path:
        sys.path.insert(0, str(worker_src))
    from api_client import ApiClient
    from config import load_worker_config
    from llm_client import LlmConfig, LlmProposalClient
    from v2_prompt_builder import V2PromptBuilder

    config = load_worker_config()
    if not config.llm_enabled:
        raise RuntimeError("Activa V2_LLM_ENABLED=true abans d'executar aquesta prova.")

    context = {
        "run_id": f"manual_prompt_{int(time.time())}",
        "generation": int(os.getenv("V2_PROMPT_TEST_GENERATION", "0")),
        "latest_metrics": {
            "val_loss_total": float(os.getenv("V2_PROMPT_TEST_VAL_LOSS", "0.42")),
            "models_evaluated": int(os.getenv("V2_PROMPT_TEST_MODELS_EVALUATED", "3")),
        },
        "code_version": os.getenv("V2_CODE_VERSION", "manual-prompt-check"),
    }
    reference_models, reference_model_path = _load_reference_models(project_root)
    if reference_models:
        context["reference_models"] = reference_models

    prompt_template_resolved = _resolve_path(config.llm_prompt_template_file, project_root)
    architecture_guide_resolved = _resolve_path(config.llm_architecture_guide_file, project_root)
    experiment_resolved = _resolve_path(config.llm_experiment_config_file, project_root)
    prompt_builder = V2PromptBuilder(
        repo_root=project_root,
        prompt_template_file=config.llm_prompt_template_file,
        architecture_guide_file=config.llm_architecture_guide_file,
        experiment_config_file=config.llm_experiment_config_file,
        num_new_models=config.llm_num_new_models,
        num_reference_models=config.llm_num_reference_models,
    )
    prompt_text = prompt_builder.build_prompt(context)
    prompt_ready = (
        len(prompt_text) > 200
        and prompt_template_resolved.exists()
        and architecture_guide_resolved.exists()
        and experiment_resolved.exists()
    )

    llm = LlmProposalClient(
        LlmConfig(
            enabled=config.llm_enabled,
            use_legacy_interface=config.llm_use_legacy_interface,
            provider=config.llm_provider,
            endpoint=config.llm_endpoint,
            api_key=config.llm_api_key,
            model=config.llm_model,
            timeout_seconds=config.llm_timeout_seconds,
            temperature=config.llm_temperature,
            max_tokens=config.llm_max_tokens,
            system_prompt=config.llm_system_prompt,
            prompt_template_file=config.llm_prompt_template_file,
            fix_error_prompt_file=config.llm_fix_error_prompt_file,
            architecture_guide_file=config.llm_architecture_guide_file,
            experiment_config_file=config.llm_experiment_config_file,
            num_new_models=config.llm_num_new_models,
            num_reference_models=config.llm_num_reference_models,
            repair_on_validation_error=config.llm_repair_on_validation_error,
        )
    )

    send_to_llm = os.getenv("V2_PROMPT_SEND_TO_LLM", "false").strip().lower() in {"1", "true", "yes"}
    candidate: dict[str, Any] = {}
    if send_to_llm:
        if not prompt_ready:
            raise RuntimeError("El prompt encara no està llest. Mantén V2_PROMPT_SEND_TO_LLM=false fins tenir prompt_ready=true.")
        candidate = llm.generate_candidate(context) or {}
        if not candidate:
            raise RuntimeError("No s'ha rebut candidat LLM")

    api_result: dict[str, Any] = {}
    push_to_api = os.getenv("V2_PROMPT_PUSH_TO_API", "false").strip().lower() in {"1", "true", "yes"}
    if push_to_api and send_to_llm:
        api = ApiClient(config.api_base_url, config.api_token, api_path_prefix=config.api_path_prefix)
        run = api.create_run(code_version=f"{context['code_version']}-single", metadata={"source": "run_llm_full_prompt_check"})
        created = api.create_model_proposal(
            source_run_id=run["run_id"],
            base_model_id=str(candidate.get("base_model_id", "")).strip() or "manual_base",
            proposal=candidate.get("proposal") if isinstance(candidate.get("proposal"), dict) else {},
            llm_metadata=candidate.get("llm_metadata") if isinstance(candidate.get("llm_metadata"), dict) else {},
        )
        proposal_id = str(created.get("proposal_id", ""))
        if proposal_id:
            api.enqueue_model_proposal_phase0(proposal_id)
            api.process_model_proposals_phase0(limit=5)
            proposal_detail = api._request("GET", f"/model-proposals/{proposal_id}")
        else:
            proposal_detail = {}
        api_result = {
            "run_id": run.get("run_id"),
            "proposal_id": proposal_id,
            "proposal_status": proposal_detail.get("status"),
        }

    output = {
        "ok": prompt_ready,
        "prompt_chars": len(prompt_text),
        "prompt_preview": prompt_text[:1200],
        "prompt_ready": prompt_ready,
        "send_to_llm": send_to_llm,
        "push_to_api": push_to_api,
        "v2_root": str(v2_root),
        "project_root": str(project_root),
        "prompt_template_path": str(prompt_template_resolved),
        "prompt_template_exists": prompt_template_resolved.exists(),
        "architecture_guide_path": str(architecture_guide_resolved),
        "architecture_guide_exists": architecture_guide_resolved.exists(),
        "experiment_config_path": str(experiment_resolved),
        "experiment_config_exists": experiment_resolved.exists(),
        "reference_model_path": reference_model_path,
        "reference_models_used": len(reference_models),
        "runtime_model": config.llm_model,
        "runtime_endpoint": config.llm_endpoint,
        "candidate": candidate if send_to_llm else {},
        "api_result": api_result,
    }
    output_path = os.getenv("V2_PROMPT_OUTPUT_PATH", "/content/b-ia/llm_prompt_check_result.json").strip()
    if output_path != "":
        Path(output_path).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
