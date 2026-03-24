from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _request_json(method: str, api_base_url: str, path: str, token: str, payload: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    last_error: Exception | None = None
    for url in _candidate_urls(api_base_url, path):
        req = urllib.request.Request(url=url, method=method, headers=headers, data=body)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                parsed = json.loads(raw) if raw else {}
                if isinstance(parsed, dict):
                    return parsed, url
                return {}, url
        except urllib.error.HTTPError as err:
            if err.code == 404:
                last_error = err
                continue
            detail = err.read().decode("utf-8")
            raise RuntimeError(f"{method} {url} failed: {err.code} {detail}") from err
    if isinstance(last_error, urllib.error.HTTPError):
        detail = last_error.read().decode("utf-8")
        raise RuntimeError(f"{method} {path} failed with 404 on all prefixes. Last detail: {detail}") from last_error
    raise RuntimeError(f"{method} {path} failed without response")


def _extract_json_blocks(text: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for match in re.findall(r"\{[\s\S]*?\}", text):
        try:
            parsed = json.loads(match)
            if isinstance(parsed, dict):
                blocks.append(parsed)
        except Exception:
            continue
    return blocks


def _parse_iso_to_ts(value: str) -> float:
    if value.strip() == "":
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


@dataclass
class MatrixCase:
    idx: int
    profile: str
    generations: int


def _build_cases(total_runs: int, profiles: list[str], generations: int) -> list[MatrixCase]:
    if total_runs <= 0:
        return []
    if len(profiles) == 0:
        profiles = ["small_test", "default"]
    result: list[MatrixCase] = []
    for i in range(total_runs):
        profile = profiles[i % len(profiles)]
        result.append(MatrixCase(idx=i + 1, profile=profile, generations=generations))
    return result


def _validate_run_consistency(api_base_url: str, token: str, run_id: str, stale_minutes: int) -> dict[str, Any]:
    run_payload, _ = _request_json("GET", api_base_url, f"/runs/{run_id}", token)
    summary_payload, _ = _request_json("GET", api_base_url, f"/runs/{run_id}/summary", token)
    events_payload, _ = _request_json("GET", api_base_url, f"/runs/{run_id}/events?limit=300", token)
    proposals_payload, _ = _request_json("GET", api_base_url, "/model-proposals?limit=800", token)

    proposals = [
        p for p in proposals_payload.get("model_proposals", [])
        if isinstance(p, dict) and str(p.get("source_run_id", "")).strip() == run_id
    ]
    events = [e for e in events_payload.get("events", []) if isinstance(e, dict)]

    trained = [p for p in proposals if str(p.get("status", "")).strip() == "trained"]
    stale_pending: list[dict[str, Any]] = []
    now_ts = time.time()
    for p in proposals:
        status = str(p.get("status", "")).strip()
        if status not in {"accepted", "validated_phase0", "training", "queued_phase0"}:
            continue
        updated_at = str(p.get("updated_at", ""))
        age_minutes = (now_ts - _parse_iso_to_ts(updated_at)) / 60.0
        if age_minutes > stale_minutes:
            stale_pending.append({"proposal_id": p.get("proposal_id"), "status": status, "age_minutes": round(age_minutes, 2)})

    trained_metadata_missing = []
    for p in trained:
        metadata = p.get("llm_metadata") if isinstance(p.get("llm_metadata"), dict) else {}
        if not isinstance(metadata.get("training_kpis"), dict) or len(metadata.get("training_kpis", {})) == 0:
            trained_metadata_missing.append({"proposal_id": p.get("proposal_id"), "missing": "training_kpis"})
        if not isinstance(metadata.get("trained_model_uri"), str) or str(metadata.get("trained_model_uri", "")).strip() == "":
            trained_metadata_missing.append({"proposal_id": p.get("proposal_id"), "missing": "trained_model_uri"})

    event_types = {str(e.get("event_type", "")) for e in events}
    has_champion_event = any(t in event_types for t in {"champion_selected", "champion_kept", "champion_selection_skipped"})
    has_champion_flag = any(
        isinstance(p.get("llm_metadata"), dict) and bool((p.get("llm_metadata") or {}).get("champion_active"))
        for p in proposals
    )
    champion_trace_present = has_champion_event or has_champion_flag
    latest_artifact = summary_payload.get("latest_artifact") if isinstance(summary_payload.get("latest_artifact"), dict) else {}

    checks = {
        "run_completed": str(run_payload.get("status", "")) == "completed",
        "trained_exists": len(trained) > 0,
        "no_stale_pending": len(stale_pending) == 0,
        "trained_metadata_persisted": len(trained_metadata_missing) == 0,
        "champion_trace_present": champion_trace_present,
        "trained_artifact_present": str(latest_artifact.get("artifact_type", "")) in {"trained_model", "champion_model"},
    }

    return {
        "checks": checks,
        "ok": all(bool(v) for k, v in checks.items() if k != "champion_trace_present"),
        "warnings": [] if champion_trace_present else ["champion_trace_missing"],
        "proposals_total": len(proposals),
        "trained_total": len(trained),
        "stale_pending": stale_pending,
        "trained_metadata_missing": trained_metadata_missing,
        "latest_artifact_type": latest_artifact.get("artifact_type"),
        "latest_event_type": (summary_payload.get("latest_event") or {}).get("event_type") if isinstance(summary_payload.get("latest_event"), dict) else None,
    }


def _run_case(repo: Path, case: MatrixCase, api_base_url: str, token: str, stale_minutes: int) -> dict[str, Any]:
    env = os.environ.copy()
    env["V2_SELECTION_POLICY_PROFILE"] = case.profile
    env["V2_E2E_GENERATIONS"] = str(case.generations)
    env.setdefault("V2_E2E_TRAIN_TIMEOUT_SECONDS", "1200")
    env.setdefault("V2_LLM_MAX_TOKENS", "6000")
    env.setdefault("V2_LLM_NUM_REFERENCE_MODELS", "2")

    started = time.time()
    proc = subprocess.run(
        [sys.executable, str(repo / "ops" / "scripts" / "run_e2e_final_smoke.py")],
        cwd=str(repo),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    retried_for_empty_llm = False
    if proc.returncode != 0 and "OpenAI response content is empty" in proc.stdout:
        retried_for_empty_llm = True
        time.sleep(4)
        proc = subprocess.run(
            [sys.executable, str(repo / "ops" / "scripts" / "run_e2e_final_smoke.py")],
            cwd=str(repo),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    duration = round(time.time() - started, 2)

    blocks = _extract_json_blocks(proc.stdout)
    last_json = blocks[-1] if len(blocks) > 0 else {}
    run_id = str(last_json.get("run_id", "")).strip()

    consistency = None
    if proc.returncode == 0 and run_id != "":
        try:
            consistency = _validate_run_consistency(api_base_url, token, run_id, stale_minutes)
        except Exception as error:
            consistency = {
                "ok": False,
                "checks": {},
                "error": f"consistency_check_failed: {error}",
            }

    ok = proc.returncode == 0 and bool(last_json.get("ok")) and isinstance(consistency, dict) and bool(consistency.get("ok"))
    return {
        "case_index": case.idx,
        "profile": case.profile,
        "generations": case.generations,
        "ok": ok,
        "returncode": proc.returncode,
        "duration_seconds": duration,
        "run_id": run_id,
        "e2e_result": last_json,
        "consistency": consistency,
        "output_tail": proc.stdout[-3000:],
        "retried_for_empty_llm": retried_for_empty_llm,
    }


def _write_report(repo: Path, report: dict[str, Any]) -> tuple[Path, Path]:
    reports_dir = repo / "ops" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = reports_dir / f"integration_matrix_{ts}.json"
    md_path = reports_dir / f"integration_matrix_{ts}.md"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Integration Matrix Report",
        "",
        f"- started_at: {report.get('started_at')}",
        f"- finished_at: {report.get('finished_at')}",
        f"- ok: {report.get('ok')}",
        f"- total_cases: {report.get('total_cases')}",
        f"- passed_cases: {report.get('passed_cases')}",
        "",
        "## Cases",
        "",
        "| # | profile | run_id | ok | duration_s | trained | notes |",
        "|---|---|---|---|---:|---:|---|",
    ]
    for case in report.get("cases", []):
        consistency = case.get("consistency") if isinstance(case.get("consistency"), dict) else {}
        trained = consistency.get("trained_total", 0)
        notes = ""
        if not case.get("ok"):
            if isinstance(consistency, dict) and isinstance(consistency.get("checks"), dict):
                failed = [k for k, v in consistency.get("checks", {}).items() if not bool(v)]
                notes = ",".join(failed) if len(failed) > 0 else "e2e_failed"
            else:
                notes = "e2e_failed"
        lines.append(
            f"| {case.get('case_index')} | {case.get('profile')} | {case.get('run_id', '')} | {case.get('ok')} | {case.get('duration_seconds')} | {trained} | {notes} |"
        )

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> int:
    repo = _repo_root()
    mode = os.getenv("V2_MATRIX_MODE", "plan").strip().lower()
    total_runs = int(os.getenv("V2_MATRIX_RUNS", "5"))
    generations = int(os.getenv("V2_MATRIX_GENERATIONS", "1"))
    stale_minutes = int(os.getenv("V2_MATRIX_STALE_MINUTES", "20"))
    profiles_raw = os.getenv("V2_MATRIX_PROFILES", "small_test")
    profiles = [item.strip() for item in profiles_raw.split(",") if item.strip()]

    cases = _build_cases(total_runs, profiles, generations)
    if mode == "plan":
        payload = {
            "mode": "plan",
            "cases": [case.__dict__ for case in cases],
            "total_cases": len(cases),
            "notes": "Set V2_MATRIX_MODE=run with API env vars to execute.",
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    api_base_url = os.getenv("V2_API_BASE_URL", "").rstrip("/")
    token = os.getenv("V2_API_TOKEN", "")
    if api_base_url == "":
        raise RuntimeError("V2_API_BASE_URL is required for run mode")

    started_at = _now_utc()
    case_results = []
    for case in cases:
        result = _run_case(repo, case, api_base_url, token, stale_minutes)
        case_results.append(result)
        print(json.dumps({
            "case_index": result.get("case_index"),
            "profile": result.get("profile"),
            "run_id": result.get("run_id"),
            "ok": result.get("ok"),
            "duration_seconds": result.get("duration_seconds"),
        }, ensure_ascii=False))

    passed_cases = len([c for c in case_results if bool(c.get("ok"))])
    report = {
        "ok": passed_cases == len(case_results) and len(case_results) > 0,
        "started_at": started_at,
        "finished_at": _now_utc(),
        "total_cases": len(case_results),
        "passed_cases": passed_cases,
        "profiles": profiles,
        "generations_per_case": generations,
        "stale_minutes": stale_minutes,
        "cases": case_results,
    }

    json_path, md_path = _write_report(repo, report)
    report["report_json"] = str(json_path)
    report["report_md"] = str(md_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
