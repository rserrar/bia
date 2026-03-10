from __future__ import annotations

import time
from dataclasses import asdict, dataclass

from .api_client import ApiClient
from .checkpoint_store import CheckpointStore
from .config import WorkerConfig


@dataclass
class WorkerState:
    run_id: str | None = None
    generation: int = 0
    stage: str = "init"
    status: str = "queued"


class EvolutionWorkerEngine:
    def __init__(self, config: WorkerConfig, api_client: ApiClient, checkpoint_store: CheckpointStore) -> None:
        self.config = config
        self.api = api_client
        self.checkpoints = checkpoint_store
        self.state = self._load_state()

    def _load_state(self) -> WorkerState:
        data = self.checkpoints.load()
        if not data:
            return WorkerState()
        return WorkerState(
            run_id=data.get("run_id"),
            generation=int(data.get("generation", 0)),
            stage=data.get("stage", "init"),
            status=data.get("status", "queued"),
        )

    def _save_state(self) -> None:
        self.checkpoints.save(asdict(self.state))

    def _ensure_run(self) -> None:
        if self.state.run_id:
            return
        run = self.api.create_run(self.config.code_version, self.config.run_metadata)
        self.state.run_id = run["run_id"]
        self.state.status = run["status"]
        self.state.stage = "run_created"
        self._save_state()

    def _send_heartbeat(self) -> None:
        if not self.state.run_id:
            return
        run = self.api.heartbeat(self.state.run_id)
        self.state.status = run["status"]
        self._save_state()

    def _run_generation_step(self, generation: int) -> None:
        run_id = self.state.run_id
        if not run_id:
            raise RuntimeError("run_id not initialized")
        self.api.update_status(run_id, "running", generation)
        self.api.add_event(run_id, "generation_start", f"Inici generació {generation}")
        simulated_metric = {
            "val_loss_total": round(1.0 / (generation + 1), 6),
            "models_evaluated": 3,
        }
        self.api.add_metric(run_id, model_id=f"gen_{generation}_summary", generation=generation, metrics=simulated_metric)
        self.api.add_artifact(
            run_id,
            artifact_type="checkpoint",
            uri=self.config.checkpoint_path,
            storage="drive",
            metadata={"generation": generation},
        )
        self.api.add_event(run_id, "generation_end", f"Fi generació {generation}")
        self.state.generation = generation + 1
        self.state.stage = "generation_completed"
        self._save_state()

    def run(self) -> None:
        self._ensure_run()
        run_id = self.state.run_id
        if not run_id:
            raise RuntimeError("run_id not available")
        self.api.update_status(run_id, "running", self.state.generation)
        last_heartbeat = 0.0
        while self.state.generation < self.config.max_generations:
            now = time.time()
            if now - last_heartbeat >= self.config.heartbeat_interval_seconds:
                self._send_heartbeat()
                last_heartbeat = now
            self._run_generation_step(self.state.generation)
            time.sleep(1)
        self.api.update_status(run_id, "completed", self.state.generation)
        self.api.add_event(run_id, "run_completed", "Execució finalitzada")
        self.state.status = "completed"
        self.state.stage = "finished"
        self._save_state()
