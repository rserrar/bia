import os

from .poll_client import PollClient


def main() -> None:
    api_base_url = os.getenv("V2_API_BASE_URL", "http://localhost:8080")
    run_id = os.getenv("V2_RUN_ID", "")
    interval_seconds = int(os.getenv("V2_POLL_SECONDS", "30"))
    if not run_id:
        raise RuntimeError("V2_RUN_ID is required")
    client = PollClient(api_base_url=api_base_url, run_id=run_id, interval_seconds=interval_seconds)
    client.watch()


if __name__ == "__main__":
    main()
