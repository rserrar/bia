from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import MinMaxScaler


def _debug_log(message: str) -> None:
    print(f"[data-prep] {message}")


def prepare_model_specific_inputs_outputs(
    all_loaded_data: dict[str, np.ndarray],
    model_json_definition: dict[str, Any],
) -> tuple[list[np.ndarray], list[np.ndarray], list[str], list[str]]:
    x_list: list[np.ndarray] = []
    y_list: list[np.ndarray] = []
    input_names: list[str] = []
    output_names: list[str] = []

    arch = model_json_definition.get("architecture_definition", {})
    input_cfg_runtime = model_json_definition.get("input_features_config_runtime", [])
    output_cfg_runtime = model_json_definition.get("output_targets_config_runtime", [])

    for input_conf in arch.get("used_inputs", []):
        input_layer_name = str(input_conf.get("input_layer_name", "")).strip()
        source_feature_name = str(input_conf.get("source_feature_name", "")).strip()
        if input_layer_name == "" or source_feature_name == "":
            continue
        arr = all_loaded_data.get(source_feature_name, np.array([]))
        if arr.size == 0:
            mandatory = any(
                isinstance(item, dict)
                and item.get("feature_name") == source_feature_name
                and bool(item.get("is_mandatory_input", False))
                for item in input_cfg_runtime
            )
            if mandatory:
                raise ValueError(f"Missing mandatory input feature: {source_feature_name}")
            continue
        x_list.append(arr)
        input_names.append(input_layer_name)

    for head_conf in arch.get("output_heads", []):
        output_layer_name = str(head_conf.get("output_layer_name", "")).strip()
        maps_to = str(head_conf.get("maps_to_target_config_name", "")).strip()
        if output_layer_name == "":
            continue

        target_cfg = None
        for item in output_cfg_runtime:
            if not isinstance(item, dict):
                continue
            if maps_to and str(item.get("target_name", "")) == maps_to:
                target_cfg = item
                break
            if str(item.get("default_output_layer_name", "")) == output_layer_name:
                target_cfg = item
                break
        if not isinstance(target_cfg, dict):
            continue

        target_name = str(target_cfg.get("target_name", "")).strip()
        if target_name == "":
            continue
        arr = all_loaded_data.get(target_name, np.array([]))
        if arr.size == 0 and bool(target_cfg.get("is_mandatory_output", False)):
            raise ValueError(f"Missing mandatory output target: {target_name}")
        if arr.size == 0:
            continue
        y_list.append(arr)
        output_names.append(output_layer_name)

    return x_list, y_list, input_names, output_names


def split_and_scale_data(
    x_model_list: list[np.ndarray],
    y_model_list: list[np.ndarray],
    _model_input_keras_names: list[str],
    experiment_config: dict[str, Any],
    model_json_definition: dict[str, Any],
    split_indices: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None,
    scaled_input_cache: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] | None = None,
    input_cache_keys: list[str] | None = None,
) -> tuple[
    tuple[list[np.ndarray], list[np.ndarray]],
    tuple[list[np.ndarray], list[np.ndarray]],
    tuple[list[np.ndarray], list[np.ndarray]],
    dict[str, MinMaxScaler],
]:
    if not x_model_list or not y_model_list:
        empty_x = [np.array([]) for _ in x_model_list]
        empty_y = [np.array([]) for _ in y_model_list]
        return (empty_x, empty_y), (empty_x, empty_y), (empty_x, empty_y), {}

    n_samples = x_model_list[0].shape[0]
    if n_samples == 0:
        empty_x = [x.copy() for x in x_model_list]
        empty_y = [y.copy() for y in y_model_list]
        return (empty_x, empty_y), (empty_x, empty_y), (empty_x, empty_y), {}

    eval_params = experiment_config.get("evaluator_params", {})
    val_split = float(eval_params.get("validation_split", 0.15))
    test_split = float(eval_params.get("test_split", 0.10))
    seed = int(model_json_definition.get("training_config", {}).get("seed", experiment_config.get("global_seed", 42)))

    _debug_log(
        f"split_and_scale_data start: samples={n_samples}, inputs={len(x_model_list)}, outputs={len(y_model_list)}, "
        f"val_split={val_split}, test_split={test_split}, seed={seed}"
    )

    if split_indices is not None:
        train_idx, val_idx, test_idx = split_indices
    else:
        indices = np.arange(n_samples)
        train_val_idx, test_idx = train_test_split(indices, test_size=test_split, random_state=seed, shuffle=True)
        if val_split > 0 and len(train_val_idx) >= 2:
            effective_val = val_split / max(1e-6, (1.0 - test_split))
            effective_val = min(max(effective_val, 0.0), 0.9)
            train_idx, val_idx = train_test_split(train_val_idx, test_size=effective_val, random_state=seed, shuffle=True)
        else:
            train_idx = train_val_idx
            val_idx = np.array([], dtype=int)

    _debug_log(
        f"index split done: train={len(train_idx)}, val={len(val_idx)}, test={len(test_idx)}"
    )

    def select(parts: list[np.ndarray], idx: np.ndarray) -> list[np.ndarray]:
        return [arr[idx] if arr.size > 0 else arr for arr in parts]

    x_train = select(x_model_list, train_idx)
    y_train = select(y_model_list, train_idx)
    x_val = select(x_model_list, val_idx)
    y_val = select(y_model_list, val_idx)
    x_test = select(x_model_list, test_idx)
    y_test = select(y_model_list, test_idx)

    _debug_log("array slicing done; starting scaling per input tensor")

    scalers: dict[str, MinMaxScaler] = {}
    x_train_scaled: list[np.ndarray] = []
    x_val_scaled: list[np.ndarray] = []
    x_test_scaled: list[np.ndarray] = []

    for idx, arr_train in enumerate(x_train):
        if arr_train.size == 0:
            _debug_log(f"input_{idx}: empty tensor, skipping scaling")
            x_train_scaled.append(arr_train)
            x_val_scaled.append(x_val[idx])
            x_test_scaled.append(x_test[idx])
            continue
        cache_key = input_cache_keys[idx] if isinstance(input_cache_keys, list) and idx < len(input_cache_keys) else f"input_{idx}"
        if scaled_input_cache is not None and cache_key in scaled_input_cache:
            cached_train, cached_val, cached_test = scaled_input_cache[cache_key]
            _debug_log(f"input_{idx}: reusing cached scaled tensors for key={cache_key}")
            x_train_scaled.append(cached_train)
            x_val_scaled.append(cached_val)
            x_test_scaled.append(cached_test)
            continue
        scaler = MinMaxScaler()
        train_shape = arr_train.shape
        train_flat = arr_train.reshape(-1, train_shape[-1]) if arr_train.ndim > 2 else arr_train.reshape(train_shape[0], -1)
        _debug_log(f"input_{idx}: fit_transform start shape={train_shape} flat={train_flat.shape}")
        train_scaled = scaler.fit_transform(train_flat).reshape(train_shape)
        x_train_scaled.append(train_scaled)
        _debug_log(f"input_{idx}: fit_transform done")

        val_arr = x_val[idx]
        if val_arr.size > 0:
            val_shape = val_arr.shape
            val_flat = val_arr.reshape(-1, val_shape[-1]) if val_arr.ndim > 2 else val_arr.reshape(val_shape[0], -1)
            _debug_log(f"input_{idx}: validation transform start shape={val_shape} flat={val_flat.shape}")
            x_val_scaled.append(scaler.transform(val_flat).reshape(val_shape))
            _debug_log(f"input_{idx}: validation transform done")
        else:
            x_val_scaled.append(val_arr)

        test_arr = x_test[idx]
        if test_arr.size > 0:
            test_shape = test_arr.shape
            test_flat = test_arr.reshape(-1, test_shape[-1]) if test_arr.ndim > 2 else test_arr.reshape(test_shape[0], -1)
            _debug_log(f"input_{idx}: test transform start shape={test_shape} flat={test_flat.shape}")
            x_test_scaled.append(scaler.transform(test_flat).reshape(test_shape))
            _debug_log(f"input_{idx}: test transform done")
        else:
            x_test_scaled.append(test_arr)
        scalers[f"input_{idx}"] = scaler
        if scaled_input_cache is not None:
            scaled_input_cache[cache_key] = (x_train_scaled[-1], x_val_scaled[-1], x_test_scaled[-1])

    _debug_log("split_and_scale_data completed")

    return (x_train_scaled, y_train), (x_val_scaled, y_val), (x_test_scaled, y_test), scalers
