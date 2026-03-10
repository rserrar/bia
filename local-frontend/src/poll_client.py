from __future__ import annotations

import json
import time
from datetime import datetime

import requests


class PollClient:
    def __init__(self, api_base_url: str, run_id: str, interval_seconds: int = 30) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.run_id = run_id
        self.interval_seconds = interval_seconds

    def fetch_summary(self) -> dict:
        url = f"{self.api_base_url}/runs/{self.run_id}/summary"
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        return response.json()

    def watch(self) -> None:
        while True:
            try:
                summary = self.fetch_summary()
                timestamp = datetime.now().isoformat()
                print(json.dumps({"timestamp": timestamp, "summary": summary}, ensure_ascii=False))
            except Exception as error:
                print(json.dumps({"error": str(error), "timestamp": datetime.now().isoformat()}, ensure_ascii=False))
            time.sleep(self.interval_seconds)
