import os
import json

try:
    from .poll_client import PollClient
except ImportError:
    from poll_client import PollClient


def main() -> None:
    api_base_url = os.getenv("V2_API_BASE_URL", "http://localhost:8080")
    run_id = os.getenv("V2_RUN_ID", "")
    interval_seconds = int(os.getenv("V2_POLL_SECONDS", "30"))
    monitor_once = os.getenv("V2_MONITOR_ONCE", "").lower() in {"1", "true", "yes"}
    if not run_id:
        raise RuntimeError("V2_RUN_ID is required")
    client = PollClient(api_base_url=api_base_url, run_id=run_id, interval_seconds=interval_seconds)
    if monitor_once:
        print(json.dumps(client.fetch_summary(), ensure_ascii=False))
        return
    client.watch()


if __name__ == "__main__":
    main()
