import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from src.api_client import ApiClient
from src.checkpoint_store import CheckpointStore
from src.config import load_worker_config
from src.engine import EvolutionWorkerEngine


def main() -> None:
    print("Iniciant V2 Controller Worker...")
    config = load_worker_config()
    api_client = ApiClient(
        config.api_base_url,
        config.api_token,
        timeout_seconds=config.api_timeout_seconds,
        connect_timeout_seconds=config.api_connect_timeout_seconds,
        read_timeout_seconds=config.api_read_timeout_seconds,
        max_retries=config.api_max_retries,
        circuit_breaker_threshold=config.api_circuit_breaker_threshold,
        circuit_breaker_cooldown_seconds=config.api_circuit_breaker_cooldown_seconds,
        api_path_prefix=config.api_path_prefix,
    )
    checkpoint_store = CheckpointStore(config.checkpoint_path)
    engine = EvolutionWorkerEngine(config, api_client, checkpoint_store)
    engine.run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nController aturat manualment per l'usuari.")
    except Exception as error:
        print(f"Error critic al Controller: {error}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
