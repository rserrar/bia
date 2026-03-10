from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main() -> int:
    repo = _repo_root()
    model_json_path = os.getenv("V2_LEGACY_MODEL_JSON_PATH", str(repo / ".." / "models" / "base" / "model_exemple_complex_v1.json"))
    experiment_config_path = os.getenv("V2_LEGACY_EXPERIMENT_CONFIG_PATH", str(repo / ".." / "config_experiment.json"))
    legacy_builder_path = os.getenv("V2_LEGACY_BUILDER_PATH", str(repo / ".." / "utils" / "model_builder.py"))
    colab_worker_src = repo / "colab-worker" / "src"
    if str(colab_worker_src) not in sys.path:
        sys.path.insert(0, str(colab_worker_src))
    from legacy_model_compat import build_legacy_model_once

    try:
        result = build_legacy_model_once(
            model_json_path=model_json_path,
            experiment_config_path=experiment_config_path,
            legacy_builder_path=legacy_builder_path,
        )
    except Exception as error:
        print(
            json.dumps(
                {
                    "ok": False,
                    "model_json_path": model_json_path,
                    "experiment_config_path": experiment_config_path,
                    "legacy_builder_path": legacy_builder_path,
                    "error": str(error),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "model_json_path": model_json_path,
                "experiment_config_path": experiment_config_path,
                "legacy_builder_path": legacy_builder_path,
                "result": result,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
