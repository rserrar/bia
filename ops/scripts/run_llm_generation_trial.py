from __future__ import annotations

import json
import os
import sys
import time
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


def _request_json(method: str, api_base_url: str, path: str, token: str, payload: dict | None = None) -> tuple[dict, str]:
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
                if isinstance(parsed, dict):
                    parsed["_resolved_url"] = url
                return parsed, url
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


def _resolve_llm_api_key() -> str:
    explicit = os.getenv("V2_LLM_API_KEY", "").strip()
    if explicit:
        return explicit
    env_key = os.getenv("OPENAI_API_KEY", "").strip()
    if env_key:
        return env_key
    config_path = os.getenv("V2_LLM_CONFIG_FILE", "").strip()
    if config_path == "":
        return ""
    path = Path(config_path)
    if not path.is_absolute():
        path = (_repo_root().parent / path).resolve()
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    from_file = str(data.get("openai_api_key", "")).strip()
    if from_file:
        return from_file
    env_var_name = str(data.get("openai_api_key_env_var", "")).strip()
    if env_var_name:
        return os.getenv(env_var_name, "").strip()
    return ""


def main() -> int:
    repo = _repo_root()
    worker_src = repo / "colab-worker" / "src"
    if str(worker_src) not in sys.path:
        sys.path.insert(0, str(worker_src))
    from run_worker import main as run_worker_main
    from config import load_worker_config

    api_base_url = os.getenv("V2_API_BASE_URL", "").rstrip("/")
    api_token = os.getenv("V2_API_TOKEN", "")
    if api_base_url == "":
        raise RuntimeError("V2_API_BASE_URL is required")

    generations = int(os.getenv("V2_LLM_TRIAL_GENERATIONS", "4"))
    print(f"[trial] iniciant prova LLM · generations={generations}")
    os.environ["V2_MAX_GENERATIONS"] = str(generations)
    os.environ["V2_HEARTBEAT_INTERVAL_SECONDS"] = os.getenv("V2_LLM_TRIAL_HEARTBEAT_SECONDS", "5")
    os.environ["V2_CODE_VERSION"] = os.getenv("V2_LLM_TRIAL_CODE_VERSION", "trial-llm-generation")
    os.environ["V2_LLM_ENABLED"] = "true"
    os.environ["V2_LLM_PROVIDER"] = os.getenv("V2_LLM_PROVIDER", "openai")
    os.environ["V2_LLM_USE_LEGACY_INTERFACE"] = os.getenv("V2_LLM_USE_LEGACY_INTERFACE", "true")
    os.environ["V2_AUTO_PROCESS_PROPOSALS_PHASE0"] = "true"
    provider = os.getenv("V2_LLM_PROVIDER", "openai").strip().lower()
    if provider != "mock":
        key = _resolve_llm_api_key()
        if key == "":
            raise RuntimeError(
                "LLM provider requires API key. Defineix OPENAI_API_KEY o V2_LLM_API_KEY "
                "o configura-la a V2_LLM_CONFIG_FILE."
            )
    print(f"[trial] provider seleccionat: {provider}")
    engine_source = (worker_src / "engine.py").read_text(encoding="utf-8")
    engine_has_llm_hook = "_create_model_proposal_if_enabled" in engine_source and "llm_proposal_created" in engine_source
    if not engine_has_llm_hook:
        raise RuntimeError(
            "El codi del worker no inclou el hook LLM esperat. "
            "Fes git pull a /content/b-ia i torna a provar."
        )
    runtime_config = load_worker_config()
    print(
        "[trial] config efectiva: "
        f"llm_enabled={runtime_config.llm_enabled}, "
        f"provider={runtime_config.llm_provider}, "
        f"use_legacy={runtime_config.llm_use_legacy_interface}, "
        f"model={runtime_config.llm_model}, "
        f"api_key_present={'yes' if runtime_config.llm_api_key.strip() else 'no'}"
    )

    checkpoint_dir = os.getenv("V2_TRIAL_CHECKPOINT_DIR", str(repo / "colab-worker" / "checkpoints"))
    checkpoint_path = Path(checkpoint_dir) / f"trial_llm_state_{int(time.time())}.json"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    os.environ["V2_CHECKPOINT_PATH"] = str(checkpoint_path)
    print(f"[trial] checkpoint: {checkpoint_path}")

    run_worker_main()
    print("[trial] worker finalitzat, comprovant resultats...")

    state = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    run_id = str(state.get("run_id", ""))
    if run_id == "":
        raise RuntimeError("run_id not found in checkpoint")

    flush_limit = max(20, generations * 3)
    for _ in range(3):
        _request_json(
            "POST",
            api_base_url,
            "/maintenance/process-model-proposals-phase0",
            api_token,
            {"limit": flush_limit},
        )
        proposals_payload, _ = _request_json("GET", api_base_url, "/model-proposals?limit=200", api_token)
        run_proposals = [
            p for p in proposals_payload.get("model_proposals", [])
            if isinstance(p, dict) and p.get("source_run_id") == run_id
        ]
        queued_count = len([p for p in run_proposals if p.get("status") == "queued_phase0"])
        if queued_count == 0:
            break
        time.sleep(1)

    summary, _ = _request_json("GET", api_base_url, f"/runs/{run_id}/summary", api_token)
    events: list[dict] = []
    events_endpoint_available = True
    try:
        events_payload, _ = _request_json("GET", api_base_url, f"/runs/{run_id}/events?limit=500", api_token)
        events = [e for e in events_payload.get("events", []) if isinstance(e, dict)]
    except Exception:
        events_endpoint_available = False
    llm_error_events = [e for e in events if e.get("event_type") == "llm_proposal_error"]
    llm_created_events = [e for e in events if e.get("event_type") == "llm_proposal_created"]
    proposals_payload, _ = _request_json("GET", api_base_url, "/model-proposals?limit=200", api_token)
    proposals = [p for p in proposals_payload.get("model_proposals", []) if isinstance(p, dict) and p.get("source_run_id") == run_id]
    validated = [p for p in proposals if p.get("status") == "validated_phase0"]

    output = {
        "ok": len(proposals) >= generations and len(validated) >= generations,
        "run_id": run_id,
        "generations": generations,
        "proposals_created": len(proposals),
        "proposals_validated_phase0": len(validated),
        "llm_created_events": len(llm_created_events),
        "llm_error_events": len(llm_error_events),
        "llm_error_samples": [e.get("details", {}) for e in llm_error_events[-3:]],
        "events_endpoint_available": events_endpoint_available,
        "run_status": summary.get("run", {}).get("status"),
        "latest_event_type": summary.get("latest_event", {}).get("event_type"),
        "latest_event_label": summary.get("latest_event", {}).get("label"),
        "provider": provider,
        "runtime_llm_enabled": runtime_config.llm_enabled,
        "runtime_llm_provider": runtime_config.llm_provider,
        "runtime_llm_use_legacy": runtime_config.llm_use_legacy_interface,
        "runtime_llm_model": runtime_config.llm_model,
        "runtime_llm_api_key_present": runtime_config.llm_api_key.strip() != "",
        "engine_has_llm_hook": engine_has_llm_hook,
        "checkpoint_path": str(checkpoint_path),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
