from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class V2PromptBuilder:
    def __init__(
        self,
        repo_root: Path,
        prompt_template_file: str,
        architecture_guide_file: str,
        experiment_config_file: str,
        num_new_models: int,
        num_reference_models: int,
    ) -> None:
        self.repo_root = repo_root
        self.prompt_template_file = prompt_template_file
        self.architecture_guide_file = architecture_guide_file
        self.experiment_config_file = experiment_config_file
        self.num_new_models = max(1, num_new_models)
        self.num_reference_models = max(0, num_reference_models)

    def build_prompt(self, context: dict[str, Any]) -> str:
        template = self._read_text(self.prompt_template_file)
        architecture_guide = self._read_text(self.architecture_guide_file)
        experiment = self._read_json(self.experiment_config_file)
        inputs_desc = self._inputs_description(experiment)
        outputs_desc = self._outputs_description(experiment)
        reference_models = self._reference_models_for_prompt(context)
        genealogy = self._genealogy_for_prompt(context)

        prompt = template
        prompt = prompt.replace("{{num_new_models}}", str(self.num_new_models))
        prompt = prompt.replace("{{available_inputs_description}}", inputs_desc)
        prompt = prompt.replace("{{available_outputs_description}}", outputs_desc)
        prompt = prompt.replace("{{num_best_models_considered}}", str(len(reference_models)))
        prompt = prompt.replace("{{best_performing_models_json}}", json.dumps(reference_models, ensure_ascii=False, indent=2))
        prompt = prompt.replace("{{architecture_guide_content}}", architecture_guide)
        prompt = prompt.replace("{{genealogy_case_studies}}", genealogy)
        return prompt

    def _resolve_path(self, file_path: str) -> Path:
        raw = Path(file_path)
        if raw.is_absolute():
            return raw
        return (self.repo_root / raw).resolve()

    def _read_text(self, file_path: str) -> str:
        resolved = self._resolve_path(file_path)
        if not resolved.exists():
            return ""
        return resolved.read_text(encoding="utf-8")

    def _read_json(self, file_path: str) -> dict[str, Any]:
        resolved = self._resolve_path(file_path)
        if not resolved.exists():
            return {}
        try:
            loaded = json.loads(resolved.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _inputs_description(self, experiment: dict[str, Any]) -> str:
        entries = []
        for item in experiment.get("input_features_config", [])[:20]:
            if not isinstance(item, dict):
                continue
            feature = str(item.get("feature_name", "unknown"))
            cols = int(item.get("total_columns", 0))
            mandatory = bool(item.get("is_mandatory_input", False))
            desc = str(item.get("description", ""))
            entries.append(f"- {feature} · cols={cols} · mandatory={mandatory} · {desc}")
        return "\n".join(entries) if entries else "No input features config available."

    def _outputs_description(self, experiment: dict[str, Any]) -> str:
        entries = []
        for item in experiment.get("output_targets_config", [])[:30]:
            if not isinstance(item, dict):
                continue
            target = str(item.get("target_name", "unknown"))
            cols = int(item.get("total_columns", 0))
            mandatory = bool(item.get("is_mandatory_output", False))
            layer = str(item.get("default_output_layer_name", ""))
            entries.append(f"- {target} · cols={cols} · mandatory={mandatory} · default_layer={layer}")
        return "\n".join(entries) if entries else "No output targets config available."

    def _reference_models_for_prompt(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        references = context.get("reference_models")
        if isinstance(references, list):
            clean = [item for item in references if isinstance(item, dict)]
            return clean[: self.num_reference_models]
        metrics = context.get("latest_metrics")
        if isinstance(metrics, dict):
            return [{"model_id": "current_generation_summary", "last_evaluation_metrics": metrics}]
        return []

    def _genealogy_for_prompt(self, context: dict[str, Any]) -> str:
        generation = int(context.get("generation", 0))
        metrics = context.get("latest_metrics", {})
        metrics_text = json.dumps(metrics, ensure_ascii=False) if isinstance(metrics, dict) else "{}"
        return (
            f"CAS D'ESTUDI GENERACIÓ {generation}\n"
            f"- run_id: {context.get('run_id', 'n/a')}\n"
            f"- code_version: {context.get('code_version', 'n/a')}\n"
            f"- latest_metrics: {metrics_text}\n"
            "- Objectiu: proposar una arquitectura nova millorant val_loss_total "
            "sense perdre estabilitat en stop_loss i take_profit."
        )
