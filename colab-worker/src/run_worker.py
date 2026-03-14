try:
    from .api_client import ApiClient
    from .checkpoint_store import CheckpointStore
    from .config import load_worker_config
    from .engine import EvolutionWorkerEngine
except ImportError:
    from api_client import ApiClient
    from checkpoint_store import CheckpointStore
    from config import load_worker_config
    from engine import EvolutionWorkerEngine


def main() -> None:
    config = load_worker_config()
    api_client = ApiClient(config.api_base_url, config.api_token, api_path_prefix=config.api_path_prefix)
    checkpoint_store = CheckpointStore(config.checkpoint_path)
    engine = EvolutionWorkerEngine(config, api_client, checkpoint_store)
    engine.run()


if __name__ == "__main__":
    main()
