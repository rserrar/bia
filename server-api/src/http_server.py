from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from shared.schemas.contracts import RunStatus

from .service import EvolutionApiService
from .state_store import JsonStateStore


class ApiHandler(BaseHTTPRequestHandler):
    service: EvolutionApiService

    def _respond(self, status: int, payload: dict) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _read_json(self) -> dict:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
        return json.loads(raw.decode("utf-8"))

    def do_POST(self) -> None:
        path = urlparse(self.path).path.strip("/")
        parts = path.split("/") if path else []
        try:
            if parts == ["runs"]:
                payload = self._read_json()
                run = self.service.create_run(
                    code_version=payload.get("code_version", "dev"),
                    metadata=payload.get("metadata", {}),
                )
                self._respond(201, run)
                return
            if len(parts) == 3 and parts[0] == "runs" and parts[2] == "heartbeat":
                run = self.service.heartbeat(parts[1])
                self._respond(200, run)
                return
            if len(parts) == 3 and parts[0] == "runs" and parts[2] == "status":
                payload = self._read_json()
                status = RunStatus(payload["status"])
                run = self.service.update_run_status(parts[1], status=status, generation=payload.get("generation"))
                self._respond(200, run)
                return
            if len(parts) == 3 and parts[0] == "runs" and parts[2] == "events":
                payload = self._read_json()
                event = self.service.add_event(parts[1], payload["event_type"], payload["label"], payload.get("details"))
                self._respond(201, event)
                return
            if len(parts) == 3 and parts[0] == "runs" and parts[2] == "metrics":
                payload = self._read_json()
                metric = self.service.add_metric(parts[1], payload["model_id"], int(payload["generation"]), payload["metrics"])
                self._respond(201, metric)
                return
            if len(parts) == 3 and parts[0] == "runs" and parts[2] == "artifacts":
                payload = self._read_json()
                artifact = self.service.add_artifact(
                    parts[1],
                    payload["artifact_type"],
                    payload["uri"],
                    checksum=payload.get("checksum"),
                    storage=payload.get("storage", "drive"),
                    metadata=payload.get("metadata"),
                )
                self._respond(201, artifact)
                return
            self._respond(404, {"error": "not_found"})
        except KeyError as error:
            self._respond(404, {"error": str(error)})
        except Exception as error:
            self._respond(400, {"error": str(error)})

    def do_GET(self) -> None:
        path = urlparse(self.path).path.strip("/")
        parts = path.split("/") if path else []
        try:
            if len(parts) == 2 and parts[0] == "runs":
                run = self.service.get_run(parts[1])
                self._respond(200, run)
                return
            if len(parts) == 3 and parts[0] == "runs" and parts[2] == "summary":
                summary = self.service.get_summary(parts[1])
                self._respond(200, summary)
                return
            self._respond(404, {"error": "not_found"})
        except KeyError as error:
            self._respond(404, {"error": str(error)})
        except Exception as error:
            self._respond(400, {"error": str(error)})


def serve(host: str = "0.0.0.0", port: int = 8080, state_file: str | None = None) -> None:
    selected_state_file = state_file or str(Path(__file__).resolve().parents[1] / "state" / "state.json")
    store = JsonStateStore(selected_state_file)
    ApiHandler.service = EvolutionApiService(store)
    server = ThreadingHTTPServer((host, port), ApiHandler)
    server.serve_forever()


if __name__ == "__main__":
    serve()
