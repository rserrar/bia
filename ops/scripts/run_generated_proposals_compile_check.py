from __future__ import annotations

import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _normalize_prefix(prefix: str) -> str:
    value = (prefix or "").strip()
    if value == "":
        return ""
    if not value.startswith("/"):
        value = "/" + value
    return value.rstrip("/")


def _candidate_urls(api_base_url: str, path: str) -> list[str]:
    configured = _normalize_prefix(os.getenv("V2_API_PATH_PREFIX", ""))
    seen: set[str] = set()
    urls: list[str] = []
    for prefix in [configured, "", "/public/index.php", "/public"]:
        normalized = _normalize_prefix(prefix)
        if normalized in seen:
            continue
        seen.add(normalized)
        urls.append(f"{api_base_url}{normalized}{path}")
    return urls


def _request_json(method: str, api_base_url: str, path: str, token: str, payload: dict | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    last_error: Exception | None = None
    for url in _candidate_urls(api_base_url, path):
        request = urllib.request.Request(url=url, method=method, headers=headers, data=body)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                content = response.read().decode("utf-8")
                parsed = json.loads(content) if content else {}
                return parsed if isinstance(parsed, dict) else {}
        except urllib.error.HTTPError as error:
            if error.code == 404:
                last_error = error
                continue
            detail = error.read().decode("utf-8")
            raise RuntimeError(f"{method} {url} failed: {error.code} {detail}") from error
    if isinstance(last_error, urllib.error.HTTPError):
        detail = last_error.read().decode("utf-8")
        raise RuntimeError(f"{method} {path} failed with 404 on all prefixes. Last detail: {detail}") from last_error
    raise RuntimeError(f"{method} {path} failed without response")


def _compile_model_definition(model_definition: dict, proposal_id: str, experiment_config_path: str, legacy_builder_path: str) -> dict:
    repo = _repo_root()
    worker_src = repo / "colab-worker" / "src"
    if str(worker_src) not in sys.path:
        sys.path.insert(0, str(worker_src))
    from legacy_model_compat import load_legacy_model

    with tempfile.TemporaryDirectory(prefix="v2_prop_compile_") as temp_dir:
        model_path = Path(temp_dir) / f"{proposal_id}.json"
        model_path.write_text(json.dumps(model_definition, ensure_ascii=False, indent=2), encoding="utf-8")
        model = load_legacy_model(
            model_json_path=str(model_path),
            experiment_config_path=experiment_config_path,
            legacy_builder_path=legacy_builder_path,
        )
        return {
            "num_inputs": len(model.inputs),
            "num_outputs": len(model.outputs),
            "output_names": list(model.output_names),
        }


def main() -> int:
    api_base_url = os.getenv("V2_API_BASE_URL", "").rstrip("/")
    api_token = os.getenv("V2_API_TOKEN", "")
    run_id = os.getenv("V2_TARGET_RUN_ID", "").strip()
    if api_base_url == "":
        raise RuntimeError("V2_API_BASE_URL és obligatori")
    if run_id == "":
        raise RuntimeError("V2_TARGET_RUN_ID és obligatori")

    experiment_config_path = os.getenv("V2_LEGACY_EXPERIMENT_CONFIG_PATH", "configs/experiment_config.json")
    legacy_builder_path = os.getenv("V2_LEGACY_BUILDER_PATH", "shared/utils/model_builder.py")
    proposals_payload = _request_json("GET", api_base_url, "/model-proposals?limit=500", api_token)
    proposals = [
        p for p in proposals_payload.get("model_proposals", [])
        if isinstance(p, dict) and p.get("source_run_id") == run_id
    ]
    results: list[dict] = []
    compiled_ok = 0
    compiled_failed = 0
    skipped_without_model_definition = 0
    for proposal in proposals:
        proposal_id = str(proposal.get("proposal_id", ""))
        payload = proposal.get("proposal")
        model_definition = payload.get("model_definition") if isinstance(payload, dict) else None
        model_definition_keys = sorted(list(model_definition.keys())) if isinstance(model_definition, dict) else []
        used_inputs_count = 0
        output_heads_count = 0
        if isinstance(model_definition, dict):
            architecture = model_definition.get("architecture_definition", {})
            if isinstance(architecture, dict):
                used_inputs = architecture.get("used_inputs", [])
                output_heads = architecture.get("output_heads", [])
                if isinstance(used_inputs, list):
                    used_inputs_count = len(used_inputs)
                if isinstance(output_heads, list):
                    output_heads_count = len(output_heads)
        if not isinstance(model_definition, dict) or len(model_definition) == 0:
            skipped_without_model_definition += 1
            results.append(
                {
                    "proposal_id": proposal_id,
                    "status": str(proposal.get("status", "")),
                    "compile_status": "skipped_no_model_definition",
                    "model_definition_keys": model_definition_keys,
                }
            )
            continue
        try:
            compile_info = _compile_model_definition(
                model_definition=model_definition,
                proposal_id=proposal_id or "proposal",
                experiment_config_path=experiment_config_path,
                legacy_builder_path=legacy_builder_path,
            )
            compiled_ok += 1
            results.append(
                {
                    "proposal_id": proposal_id,
                    "status": str(proposal.get("status", "")),
                    "compile_status": "ok",
                    "model_definition_keys": model_definition_keys,
                    "used_inputs_count": used_inputs_count,
                    "output_heads_count": output_heads_count,
                    "compile_info": compile_info,
                }
            )
        except Exception as error:
            compiled_failed += 1
            results.append(
                {
                    "proposal_id": proposal_id,
                    "status": str(proposal.get("status", "")),
                    "compile_status": "error",
                    "model_definition_keys": model_definition_keys,
                    "used_inputs_count": used_inputs_count,
                    "output_heads_count": output_heads_count,
                    "error": str(error),
                }
            )

    output = {
        "ok": compiled_failed == 0,
        "run_id": run_id,
        "proposals_total": len(proposals),
        "compiled_ok": compiled_ok,
        "compiled_failed": compiled_failed,
        "skipped_no_model_definition": skipped_without_model_definition,
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
