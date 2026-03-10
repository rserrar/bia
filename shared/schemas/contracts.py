from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunStatus(str, Enum):
    queued = "queued"
    running = "running"
    retrying = "retrying"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class EventLevel(str, Enum):
    info = "info"
    warning = "warning"
    error = "error"


@dataclass
class RunRecord:
    run_id: str
    status: RunStatus
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    code_version: str = "unknown"
    generation: int = 0
    heartbeat_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunRecord":
        return cls(
            run_id=data["run_id"],
            status=RunStatus(data["status"]),
            created_at=data.get("created_at", utc_now_iso()),
            updated_at=data.get("updated_at", utc_now_iso()),
            code_version=data.get("code_version", "unknown"),
            generation=int(data.get("generation", 0)),
            heartbeat_at=data.get("heartbeat_at"),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class EventRecord:
    run_id: str
    event_type: str
    label: str
    level: EventLevel = EventLevel.info
    timestamp: str = field(default_factory=utc_now_iso)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["level"] = self.level.value
        return payload


@dataclass
class MetricRecord:
    run_id: str
    model_id: str
    generation: int
    metrics: dict[str, Any]
    timestamp: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ArtifactRecord:
    run_id: str
    artifact_type: str
    uri: str
    checksum: str | None = None
    storage: str = "drive"
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
