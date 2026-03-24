from __future__ import annotations

import json
import importlib.util
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


RESPONSES = [503, 429, 200]
EVENTS: list[dict] = []


class Handler(BaseHTTPRequestHandler):
    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw else {}

    def do_POST(self) -> None:  # noqa: N802
        global RESPONSES
        payload = self._read_json()
        if self.path == "/runs":
            if RESPONSES:
                code = RESPONSES.pop(0)
                if code != 200:
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "transient"}).encode("utf-8"))
                    return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"run_id": "run_test_retry"}).encode("utf-8"))
            return
        if self.path == "/runs/run_test_retry/events":
            EVENTS.append(payload)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "shared" / "clients" / "api_client.py"
    spec = importlib.util.spec_from_file_location("v2_api_client_for_test", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load ApiClient module for test")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ApiClient = module.ApiClient

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"

    client = ApiClient(
        base_url=base_url,
        timeout_seconds=5,
        connect_timeout_seconds=2,
        read_timeout_seconds=5,
        max_retries=4,
        circuit_breaker_threshold=5,
        circuit_breaker_cooldown_seconds=5,
    )

    try:
        created = client.create_run("retry-test", {"source": "test_api_retry_policy"})
        payload = {
            "ok": created.get("run_id") == "run_test_retry",
            "created": created,
            "events": EVENTS,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["ok"] else 1
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
