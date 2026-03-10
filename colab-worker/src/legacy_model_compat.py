from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any


def _load_build_function(legacy_builder_path: str):
    builder_path = Path(legacy_builder_path)
    if not builder_path.exists():
        raise FileNotFoundError(f"legacy builder not found: {builder_path}")
    spec = importlib.util.spec_from_file_location("legacy_model_builder", str(builder_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load spec for: {builder_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    build_fn = getattr(module, "build_model_from_json_definition", None)
    if build_fn is None:
        raise RuntimeError("build_model_from_json_definition not found in legacy builder")
    return build_fn


def build_legacy_model_once(
    model_json_path: str,
    experiment_config_path: str,
    legacy_builder_path: str,
) -> dict[str, Any]:
    model = load_legacy_model(
        model_json_path=model_json_path,
        experiment_config_path=experiment_config_path,
        legacy_builder_path=legacy_builder_path,
    )
    return {
        "model_name": model.name,
        "num_inputs": len(model.inputs),
        "num_outputs": len(model.outputs),
        "output_names": list(model.output_names),
    }


def load_legacy_model(
    model_json_path: str,
    experiment_config_path: str,
    legacy_builder_path: str,
):
    model_path = Path(model_json_path)
    config_path = Path(experiment_config_path)
    if not model_path.exists():
        raise FileNotFoundError(f"model json not found: {model_path}")
    if not config_path.exists():
        raise FileNotFoundError(f"experiment config not found: {config_path}")
    with model_path.open("r", encoding="utf-8") as file:
        model_def = json.load(file)
    with config_path.open("r", encoding="utf-8") as file:
        experiment_config = json.load(file)
    model_def["input_features_config_runtime"] = experiment_config.get("input_features_config", [])
    model_def["output_targets_config_runtime"] = experiment_config.get("output_targets_config", [])
    build_fn = _load_build_function(legacy_builder_path)
    return build_fn(model_def)
