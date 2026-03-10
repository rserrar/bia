from __future__ import annotations

import uuid
from typing import Any

from shared.schemas import ArtifactRecord, EventRecord, MetricRecord, RunRecord, RunStatus, utc_now_iso

from .state_store import JsonStateStore


class EvolutionApiService:
    def __init__(self, store: JsonStateStore) -> None:
        self.store = store

    def create_run(self, code_version: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        run = RunRecord(
            run_id=f"run_{uuid.uuid4().hex[:12]}",
            status=RunStatus.queued,
            code_version=code_version,
            metadata=metadata or {},
        )
        self.store.upsert_run(run.to_dict())
        return run.to_dict()

    def update_run_status(self, run_id: str, status: RunStatus, generation: int | None = None) -> dict[str, Any]:
        data = self.store.read_all()
        run_payload = data["runs"].get(run_id)
        if not run_payload:
            raise KeyError(f"run not found: {run_id}")
        run = RunRecord.from_dict(run_payload)
        run.status = status
        run.updated_at = utc_now_iso()
        if generation is not None:
            run.generation = generation
        self.store.upsert_run(run.to_dict())
        return run.to_dict()

    def heartbeat(self, run_id: str) -> dict[str, Any]:
        data = self.store.read_all()
        run_payload = data["runs"].get(run_id)
        if not run_payload:
            raise KeyError(f"run not found: {run_id}")
        run = RunRecord.from_dict(run_payload)
        run.heartbeat_at = utc_now_iso()
        run.updated_at = run.heartbeat_at
        if run.status == RunStatus.queued:
            run.status = RunStatus.running
        self.store.upsert_run(run.to_dict())
        return run.to_dict()

    def add_event(self, run_id: str, event_type: str, label: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
        event = EventRecord(run_id=run_id, event_type=event_type, label=label, details=details or {})
        self.store.append_event(event.to_dict())
        return event.to_dict()

    def add_metric(self, run_id: str, model_id: str, generation: int, metrics: dict[str, Any]) -> dict[str, Any]:
        metric = MetricRecord(run_id=run_id, model_id=model_id, generation=generation, metrics=metrics)
        self.store.append_metric(metric.to_dict())
        return metric.to_dict()

    def add_artifact(
        self,
        run_id: str,
        artifact_type: str,
        uri: str,
        checksum: str | None = None,
        storage: str = "drive",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        artifact = ArtifactRecord(
            run_id=run_id,
            artifact_type=artifact_type,
            uri=uri,
            checksum=checksum,
            storage=storage,
            metadata=metadata or {},
        )
        self.store.append_artifact(artifact.to_dict())
        return artifact.to_dict()

    def get_run(self, run_id: str) -> dict[str, Any]:
        data = self.store.read_all()
        run_payload = data["runs"].get(run_id)
        if not run_payload:
            raise KeyError(f"run not found: {run_id}")
        return run_payload

    def get_summary(self, run_id: str) -> dict[str, Any]:
        data = self.store.read_all()
        run_payload = data["runs"].get(run_id)
        if not run_payload:
            raise KeyError(f"run not found: {run_id}")
        events = [event for event in data["events"] if event["run_id"] == run_id]
        metrics = [metric for metric in data["metrics"] if metric["run_id"] == run_id]
        artifacts = [artifact for artifact in data["artifacts"] if artifact["run_id"] == run_id]
        return {
            "run": run_payload,
            "counts": {
                "events": len(events),
                "metrics": len(metrics),
                "artifacts": len(artifacts),
            },
            "latest_event": events[-1] if events else None,
            "latest_metric": metrics[-1] if metrics else None,
            "latest_artifact": artifacts[-1] if artifacts else None,
        }
