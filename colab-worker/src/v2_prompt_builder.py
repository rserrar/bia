from __future__ import annotations

import glob
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
        prompt = prompt.replace("{{architecture_guide_content}}", self._combined_architecture_guide(architecture_guide))
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
            default_layer = str(item.get("default_input_layer_name", ""))
            source_csv = str(item.get("source_csv_key", ""))
            slice_params = item.get("slice_params")
            derive_col = item.get("derive_last_value_from_col")
            extras: list[str] = []
            if default_layer != "":
                extras.append(f"default_input_layer_name={default_layer}")
            if source_csv != "":
                extras.append(f"csv={source_csv}")
            if isinstance(slice_params, list) and len(slice_params) == 2:
                extras.append(f"slice={slice_params[0]}:{slice_params[1]}")
            if derive_col is not None:
                extras.append(f"derive_last_value_from_col={derive_col}")
            entries.append(f"- feature_name={feature} · cols={cols} · mandatory={mandatory} · {' · '.join(extras)} · {desc}")
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
            loss = str(item.get("loss_function", ""))
            activation = str(item.get("activation_output_layer", ""))
            source_csv = str(item.get("source_csv_key", ""))
            entries.append(f"- target_name={target} · cols={cols} · mandatory={mandatory} · default_output_layer_name={layer} · loss={loss} · activation={activation} · csv={source_csv}")
        return "\n".join(entries) if entries else "No output targets config available."

    def _combined_architecture_guide(self, static_guide: str) -> str:
        parts = []
        if static_guide.strip() != "":
            parts.append(static_guide.strip())
        examples = self._build_architecture_guide_from_examples(limit_examples=4)
        if examples.strip() != "":
            parts.append(examples.strip())
        return "\n\n".join(parts)

    def _build_architecture_guide_from_examples(self, limit_examples: int = 4) -> str:
        parts = [
            "### EXEMPLES D'ARQUITECTURES JSON FUNCIONALS",
            "Utilitza aquests exemples com a referència per a l'estructura correcta del JSON, les connexions entre capes i la definició de `used_inputs`, `branches`, `merges` i `output_heads`.",
            "#### Estructura correcta per a `used_inputs`",
            "`used_inputs` ha de ser una LLISTA DE DICCIONARIS. Cada element ha de definir `input_layer_name`, `source_feature_name` i `shape`.",
            "```json\n{\n  \"architecture_definition\": {\n    \"used_inputs\": [\n      {\n        \"input_layer_name\": \"input_prices_last_100\",\n        \"source_feature_name\": \"prices_hist_last_100\",\n        \"shape\": [100]\n      }\n    ]\n  }\n}\n```",
        ]
        example_patterns = [
            self.repo_root / "models" / "test" / "*.json",
            self.repo_root / "models" / "base" / "*.json",
        ]
        seen: set[str] = set()
        collected: list[Path] = []
        for pattern in example_patterns:
            for raw_path in sorted(glob.glob(str(pattern))):
                if raw_path in seen:
                    continue
                seen.add(raw_path)
                collected.append(Path(raw_path))
                if len(collected) >= limit_examples:
                    break
            if len(collected) >= limit_examples:
                break
        if not collected:
            return "\n\n".join(parts)
        for index, example_path in enumerate(collected, start=1):
            try:
                example_text = example_path.read_text(encoding="utf-8").strip()
            except Exception:
                continue
            parts.append(f"#### Exemple guia {index}: `{example_path.name}`\n```json\n{example_text}\n```")
        return "\n\n".join(parts)

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
        references = self._reference_models_for_prompt(context)
        lines = [
            f"CAS D'ESTUDI GENERACIÓ {generation}",
            f"- run_id: {context.get('run_id', 'n/a')}",
            f"- code_version: {context.get('code_version', 'n/a')}",
            f"- latest_metrics: {metrics_text}",
            "- Objectiu: proposar una arquitectura nova millorant val_loss_total sense perdre estabilitat en stop_loss i take_profit.",
        ]
        if references:
            lines.append("- Models de referència i mètriques resumides:")
            for idx, reference in enumerate(references[: self.num_reference_models], start=1):
                ref_id = str(reference.get("model_id", reference.get("proposal_id", f"reference_{idx}")))
                ref_metrics = reference.get("last_evaluation_metrics") if isinstance(reference.get("last_evaluation_metrics"), dict) else {}
                lines.append(f"  * {ref_id}: {json.dumps(ref_metrics, ensure_ascii=False)}")
        return "\n".join(lines)
