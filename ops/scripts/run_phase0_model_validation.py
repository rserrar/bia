from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _shape_without_batch(tensor_shape) -> tuple[int, ...]:
    dims: list[int] = []
    for dim in tensor_shape[1:]:
        dims.append(int(dim) if dim is not None else 1)
    return tuple(dims)


def _fake_inputs(model, dataset_samples: int) -> list[np.ndarray]:
    tensors = model.inputs if isinstance(model.inputs, list) else [model.inputs]
    arrays: list[np.ndarray] = []
    for tensor in tensors:
        shape = _shape_without_batch(tensor.shape)
        arrays.append(np.random.random((dataset_samples, *shape)).astype("float32"))
    return arrays


def _fake_outputs(model, dataset_samples: int) -> list[np.ndarray]:
    tensors = model.outputs if isinstance(model.outputs, list) else [model.outputs]
    arrays: list[np.ndarray] = []
    for tensor in tensors:
        shape = _shape_without_batch(tensor.shape)
        arrays.append(np.random.random((dataset_samples, *shape)).astype("float32"))
    return arrays


def _load_phase0_config(config_path: Path) -> dict:
    with config_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def main() -> int:
    repo = _repo_root()
    colab_worker_src = repo / "colab-worker" / "src"
    if str(colab_worker_src) not in sys.path:
        sys.path.insert(0, str(colab_worker_src))
    try:
        from legacy_model_compat import load_legacy_model
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False, indent=2))
        return 1

    default_config_path = repo / "ops" / "configs" / "phase0_model_validation.json"
    config_path = Path(os.getenv("V2_PHASE0_CONFIG_PATH", str(default_config_path)))
    if not config_path.exists():
        print(json.dumps({"ok": False, "error": f"phase0 config not found: {config_path}"}, ensure_ascii=False, indent=2))
        return 1
    config = _load_phase0_config(config_path)
    profiles = config.get("profiles", {})
    experiment_config_path = str(config.get("experiment_config_path", ""))
    legacy_builder_path = str(config.get("legacy_builder_path", ""))

    results: list[dict] = []
    for model_item in config.get("models", []):
        if not bool(model_item.get("enabled", True)):
            continue
        model_json_path = str(model_item.get("model_json_path", ""))
        profile_name = str(model_item.get("profile", "smoke"))
        profile = profiles.get(profile_name, {})
        dataset_samples = int(profile.get("dataset_samples", 64))
        batch_size = int(profile.get("batch_size", 8))
        epochs = int(profile.get("epochs", 1))
        max_train_seconds = int(profile.get("max_train_seconds", 20))
        start = time.time()
        item_result = {
            "model_json_path": model_json_path,
            "profile": profile_name,
            "dataset_samples": dataset_samples,
            "batch_size": batch_size,
            "epochs": epochs,
            "max_train_seconds": max_train_seconds,
            "ok": False,
        }
        try:
            model = load_legacy_model(
                model_json_path=model_json_path,
                experiment_config_path=experiment_config_path,
                legacy_builder_path=legacy_builder_path,
            )
            x_data = _fake_inputs(model, dataset_samples)
            y_data = _fake_outputs(model, dataset_samples)
            model.fit(x_data, y_data, epochs=epochs, batch_size=batch_size, verbose=0)
            duration = time.time() - start
            item_result["train_seconds"] = round(duration, 3)
            item_result["ok"] = duration <= max_train_seconds
            if not item_result["ok"]:
                item_result["error"] = f"training exceeded max_train_seconds ({duration:.3f}s > {max_train_seconds}s)"
        except Exception as error:
            item_result["error"] = str(error)
        results.append(item_result)

    ok = len(results) > 0 and all(bool(item.get("ok")) for item in results)
    print(json.dumps({"ok": ok, "config_path": str(config_path), "results": results}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
