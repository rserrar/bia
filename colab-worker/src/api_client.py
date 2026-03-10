from __future__ import annotations

import time
from typing import Any

import requests


class ApiClient:
    def __init__(self, base_url: str, token: str = "", timeout_seconds: int = 20) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.headers = {"Content-Type": "application/json"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None, max_retries: int = 3) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        attempt = 0
        while True:
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    json=payload,
                    headers=self.headers,
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
                return response.json()
            except Exception:
                attempt += 1
                if attempt >= max_retries:
                    raise
                time.sleep(min(2 ** attempt, 10))

    def create_run(self, code_version: str, metadata: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/runs", {"code_version": code_version, "metadata": metadata})

    def heartbeat(self, run_id: str) -> dict[str, Any]:
        return self._request("POST", f"/runs/{run_id}/heartbeat")

    def update_status(self, run_id: str, status: str, generation: int | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": status}
        if generation is not None:
            payload["generation"] = generation
        return self._request("POST", f"/runs/{run_id}/status", payload)

    def add_event(self, run_id: str, event_type: str, label: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/runs/{run_id}/events",
            {"event_type": event_type, "label": label, "details": details or {}},
        )

    def add_metric(self, run_id: str, model_id: str, generation: int, metrics: dict[str, Any]) -> dict[str, Any]:
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
