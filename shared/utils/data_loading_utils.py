from __future__ import annotations

import os
from typing import Any

import numpy as np
import pandas as pd


def load_all_raw_data_sources(
    data_paths_config: dict[str, Any],
    input_features_cfg: list[dict[str, Any]],
    output_targets_cfg: list[dict[str, Any]],
    base_data_dir: str = "data",
) -> dict[str, np.ndarray]:
    loaded_data: dict[str, np.ndarray] = {}
    keys_to_load: set[str] = set()

    for feat_conf in input_features_cfg:
        source_key = str(feat_conf.get("source_csv_key", "")).strip()
        if source_key:
            keys_to_load.add(source_key)

    for target_conf in output_targets_cfg:
        source_key = str(target_conf.get("source_csv_key", "")).strip()
        if source_key:
            keys_to_load.add(source_key)

    for csv_key in keys_to_load:
        file_name = str(data_paths_config.get(csv_key, "")).strip()
        if file_name == "":
            loaded_data[csv_key] = np.array([])
            continue
        file_path = os.path.join(base_data_dir, file_name)
        try:
            loaded_data[csv_key] = pd.read_csv(file_path, header=None).values
        except Exception:
            loaded_data[csv_key] = np.array([])

    return loaded_data


def derive_additional_features_and_targets(
    data_dict: dict[str, np.ndarray],
    input_features_cfg: list[dict[str, Any]],
    output_targets_cfg: list[dict[str, Any]],
) -> dict[str, np.ndarray]:
    for feat_conf in input_features_cfg:
        feature_name = str(feat_conf.get("feature_name", "")).strip()
        source_key = str(feat_conf.get("source_csv_key", "")).strip()
        if feature_name == "" or source_key == "":
            continue
        source = data_dict.get(source_key, np.array([]))
        if source.size == 0:
            data_dict[feature_name] = np.array([])
            continue

        derive_col = feat_conf.get("derive_last_value_from_col")
        slice_params = feat_conf.get("slice_params")
        if isinstance(derive_col, int):
            if source.ndim == 2 and source.shape[1] > derive_col:
                data_dict[feature_name] = source[:, derive_col : derive_col + 1]
            else:
                data_dict[feature_name] = np.array([])
        elif isinstance(slice_params, list) and len(slice_params) == 2:
            start = slice_params[0]
            end = slice_params[1]
            data_dict[feature_name] = source[:, slice(start, end)]
        else:
            data_dict[feature_name] = source

    for target_conf in output_targets_cfg:
        target_name = str(target_conf.get("target_name", "")).strip()
        source_key = str(target_conf.get("source_csv_key", "")).strip()
        if target_name == "" or source_key == "":
            continue
        source = data_dict.get(source_key, np.array([]))
        if source.size == 0:
            data_dict[target_name] = np.array([])
            continue
        slice_params = target_conf.get("derive_target_slice_params")
        if isinstance(slice_params, list) and len(slice_params) == 2:
            start = slice_params[0]
            end = slice_params[1]
            data_dict[target_name] = source[:, slice(start, end)]
        else:
            data_dict[target_name] = source

    return data_dict
