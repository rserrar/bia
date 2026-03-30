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
            loaded_data[csv_key] = np.array([], dtype=np.float32)
            continue
        file_path = os.path.join(base_data_dir, file_name)
        npy_path = file_path + ".npy"
        
        try:
            # Check if binary cache exists and is valid (not older than CSV)
            if os.path.exists(npy_path) and os.path.getmtime(npy_path) >= os.path.getmtime(file_path):
                # Use mmap_mode='r' to save memory if the user wants, but here we want it in RAM 
                # for the speed benefit mentioned by the user.
                arr = np.load(npy_path)
                if arr.dtype != np.float32:
                    arr = arr.astype(np.float32)
                loaded_data[csv_key] = arr
                print(f"✅ Cache binària carregada: {file_name}.npy ({len(arr)} files)")
                continue
            
            # If not in cache or cache stale, load CSV
            print(f"📄 Carregant CSV: {file_name}...")
            arr = pd.read_csv(file_path, header=None, dtype=np.float32).values
            loaded_data[csv_key] = arr
            print(f"✅ CSV carregat: {file_name} ({len(arr)} files)")
            
            # Save to binary cache for next time
            try:
                np.save(npy_path, arr)
                print(f"💾 Cache binària guardada: {file_name}.npy")
            except Exception as e:
                print(f"⚠️ No s'ha pogut guardar la cache binària per {file_name}: {e}")
                
        except Exception:
            try:
                # Fallback in case of mixed types or other issues, though expected to be numeric
                arr = pd.read_csv(file_path, header=None).values.astype(np.float32)
                loaded_data[csv_key] = arr
                try:
                    np.save(npy_path, arr)
                except Exception:
                    pass
            except Exception:
                loaded_data[csv_key] = np.array([], dtype=np.float32)

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
        source = data_dict.get(source_key, np.array([], dtype=np.float32))
        if source.size == 0:
            data_dict[feature_name] = np.array([], dtype=np.float32)
            continue

        derive_col = feat_conf.get("derive_last_value_from_col")
        slice_params = feat_conf.get("slice_params")
        if isinstance(derive_col, int):
            if source.ndim == 2 and source.shape[1] > derive_col:
                data_dict[feature_name] = source[:, derive_col : derive_col + 1].astype(np.float32)
            else:
                data_dict[feature_name] = np.array([], dtype=np.float32)
        elif isinstance(slice_params, list) and len(slice_params) == 2:
            start = slice_params[0]
            end = slice_params[1]
            data_dict[feature_name] = source[:, slice(start, end)].astype(np.float32)
        else:
            data_dict[feature_name] = source.astype(np.float32)

    for target_conf in output_targets_cfg:
        target_name = str(target_conf.get("target_name", "")).strip()
        source_key = str(target_conf.get("source_csv_key", "")).strip()
        if target_name == "" or source_key == "":
            continue
        source = data_dict.get(source_key, np.array([], dtype=np.float32))
        if source.size == 0:
            data_dict[target_name] = np.array([], dtype=np.float32)
            continue
        slice_params = target_conf.get("derive_target_slice_params")
        if isinstance(slice_params, list) and len(slice_params) == 2:
            start = slice_params[0]
            end = slice_params[1]
            data_dict[target_name] = source[:, slice(start, end)].astype(np.float32)
        else:
            data_dict[target_name] = source.astype(np.float32)

    return data_dict
