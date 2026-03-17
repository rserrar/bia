from __future__ import annotations

import time
from typing import Any

import requests


class ApiClient:
    def __init__(
        self,
        base_url: str,
        token: str = "",
        timeout_seconds: int = 20,
        api_path_prefix: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.headers = {"Content-Type": "application/json"}
        self.api_path_prefix = self._normalize_prefix(api_path_prefix)
        self._resolved_prefix: str | None = self.api_path_prefix if self.api_path_prefix else None
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        max_retries: int = 3,
    ) -> dict[str, Any]:
        attempt = 0
        while True:
            try:
                last_error: Exception | None = None
                for prefix in self._candidate_prefixes():
                    url = f"{self.base_url}{prefix}{path}"
                    response = requests.request(
                        method=method,
                        url=url,
                        json=payload,
                        headers=self.headers,
                        timeout=self.timeout_seconds,
                    )
                    if response.status_code == 404:
                        last_error = requests.HTTPError(f"404 for {url}", response=response)
                        continue
                    response.raise_for_status()
                    self._resolved_prefix = prefix
                    if not response.text:
                        return {}
                    return response.json()
                if last_error is not None:
                    raise last_error
                raise RuntimeError("request failed without response")
            except Exception:
                attempt += 1
                if attempt >= max_retries:
                    raise
                time.sleep(min(2**attempt, 10))

    def _candidate_prefixes(self) -> list[str]:
        if self._resolved_prefix is not None:
            return [self._resolved_prefix]
        seen: set[str] = set()
        prefixes: list[str] = []
        for candidate in ["", "/public/index.php", "/public", self.api_path_prefix]:
            normalized = self._normalize_prefix(candidate)
            if normalized in seen:
                continue
            seen.add(normalized)
            prefixes.append(normalized)
        return prefixes

    def _normalize_prefix(self, prefix: str) -> str:
        cleaned = (prefix or "").strip()
        if cleaned == "":
            return ""
        if not cleaned.startswith("/"):
            cleaned = "/" + cleaned
        return cleaned.rstrip("/")

    def create_run(self, code_version: str, metadata: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/runs", {"code_version": code_version, "metadata": metadata})

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/runs/{run_id}")

    def heartbeat(self, run_id: str) -> dict[str, Any]:
        return self._request("POST", f"/runs/{run_id}/heartbeat")

    def update_status(self, run_id: str, status: str, generation: int | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": status}
        if generation is not None:
            payload["generation"] = generation
        return self._request("POST", f"/runs/{run_id}/status", payload)

    def add_event(
        self,
        run_id: str,
        event_type: str,
        label: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/runs/{run_id}/events",
            {"event_type": event_type, "label": label, "details": details or {}},
        )

    def add_metric(
        self,
        run_id: str,
        model_id: str,
        generation: int,
        metrics: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/runs/{run_id}/metrics",
            {"model_id": model_id, "generation": generation, "metrics": metrics},
        )

    def add_artifact(
        self,
        run_id: str,
        artifact_type: str,
        uri: str,
        storage: str = "drive",
        checksum: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "artifact_type": artifact_type,
            "uri": uri,
            "storage": storage,
            "metadata": metadata or {},
        }
        if checksum:
            payload["checksum"] = checksum
        return self._request("POST", f"/runs/{run_id}/artifacts", payload)

    def maintenance_watchdog(self, stale_after_seconds: int) -> dict[str, Any]:
        return self._request("POST", "/maintenance/watchdog", {"stale_after_seconds": stale_after_seconds})

    def process_model_proposals_phase0(self, limit: int = 20) -> dict[str, Any]:
        return self._request("POST", "/maintenance/process-model-proposals-phase0", {"limit": limit})

    def create_model_proposal(
        self,
        source_run_id: str,
        base_model_id: str,
        proposal: dict[str, Any],
        llm_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/model-proposals",
            {
                "source_run_id": source_run_id,
                "base_model_id": base_model_id,
                "proposal": proposal,
                "llm_metadata": llm_metadata or {},
            },
        )

    def enqueue_model_proposal_phase0(self, proposal_id: str) -> dict[str, Any]:
        return self._request("POST", f"/model-proposals/{proposal_id}/enqueue-phase0")

    def list_model_proposals(self, limit: int = 100) -> list[dict[str, Any]]:
        payload = self._request("GET", f"/model-proposals?limit={max(1, int(limit))}")
        proposals = payload.get("model_proposals", []) if isinstance(payload, dict) else []
        return [item for item in proposals if isinstance(item, dict)]

    def get_model_proposal(self, proposal_id: str) -> dict[str, Any]:
        return self._request("GET", f"/model-proposals/{proposal_id}")

    def lock_accepted_proposal_for_training(self, trainer_id: str) -> dict[str, Any] | None:
        try:
            return self._request("POST", "/model-proposals/lock-for-training", {"trainer_id": trainer_id})
        except Exception:
            return None

    def update_proposal_status(
        self,
        proposal_id: str,
        status: str,
        metadata_updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/model-proposals/{proposal_id}/status",
            {"status": status, "metadata_updates": metadata_updates or {}},
        )

