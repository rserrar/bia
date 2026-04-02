from __future__ import annotations

import os
from typing import Any

import numpy as np
import pandas as pd

from shared.utils.runtime_log_utils import should_log


def _mb(arr: np.ndarray) -> float:
    return round(float(arr.nbytes) / (1024.0 * 1024.0), 2)


def _log_loading(message: str, level: str = "summary") -> None:
    if should_log("V2_LOG_DATA_LOADING", level=level, default="summary"):
        print(message)


def load_all_raw_data_sources(
    data_paths_config: dict[str, Any],
    input_features_cfg: list[dict[str, Any]],
    output_targets_cfg: list[dict[str, Any]],
    base_data_dir: str = "data",
) -> dict[str, np.ndarray]:
    loaded_data: dict[str, np.ndarray] = {}
    keys_to_load: set[str] = set()
    total_loaded_mb = 0.0

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
                # Use mmap_mode='r' to save real RAM. The OS will handle the memory mapping.
                arr = np.load(npy_path, mmap_mode='r')
                if arr.dtype != np.float32:
                    # If it's not float32, we do need to load it and convert it
                    arr = np.load(npy_path).astype(np.float32)
                loaded_data[csv_key] = arr
                current_mb = _mb(arr)
                total_loaded_mb += current_mb
                _log_loading(f"✅ Cache binària (mmap) carregada: {file_name}.npy ({len(arr)} files, dtype={arr.dtype}, ~{current_mb} MB)", level="verbose")
                continue
            
            # If not in cache or cache stale, load CSV
            _log_loading(f"📄 Carregant CSV: {file_name}...", level="verbose")
            arr = pd.read_csv(file_path, header=None, dtype=np.float32).values
            loaded_data[csv_key] = arr
            current_mb = _mb(arr)
            total_loaded_mb += current_mb
            _log_loading(f"✅ CSV carregat: {file_name} ({len(arr)} files, dtype={arr.dtype}, ~{current_mb} MB)", level="verbose")
            
            # Save to binary cache for next time
            try:
                np.save(npy_path, arr)
                _log_loading(f"💾 Cache binària guardada: {file_name}.npy", level="verbose")
            except Exception as e:
                _log_loading(f"⚠️ No s'ha pogut guardar la cache binària per {file_name}: {e}", level="summary")
                
        except Exception:
            try:
                # Fallback in case of mixed types or other issues, though expected to be numeric
                arr = pd.read_csv(file_path, header=None).values.astype(np.float32)
                loaded_data[csv_key] = arr
                total_loaded_mb += _mb(arr)
                try:
                    np.save(npy_path, arr)
                except Exception:
                    pass
            except Exception:
                loaded_data[csv_key] = np.array([], dtype=np.float32)

    _log_loading(f"📦 Dades font carregades: {len(loaded_data)} arrays, ús aproximat ~{round(total_loaded_mb, 2)} MB", level="summary")
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
                data_dict[feature_name] = source[:, derive_col : derive_col + 1]
            else:
                data_dict[feature_name] = np.array([], dtype=np.float32)
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
        source = data_dict.get(source_key, np.array([], dtype=np.float32))
        if source.size == 0:
            data_dict[target_name] = np.array([], dtype=np.float32)
            continue
        slice_params = target_conf.get("derive_target_slice_params")
        if isinstance(slice_params, list) and len(slice_params) == 2:
            start = slice_params[0]
            end = slice_params[1]
            data_dict[target_name] = source[:, slice(start, end)]
        else:
            data_dict[target_name] = source

    summary = []
    for key, value in data_dict.items():
        if isinstance(value, np.ndarray) and value.size > 0:
            summary.append(f"{key}: shape={value.shape}, dtype={value.dtype}, ~{_mb(value)} MB")
    if summary:
        _log_loading("🧾 Resum de tensores derivats:", level="summary")
        for line in summary[:20]:
            _log_loading(f"   - {line}", level="verbose")

    return data_dict
