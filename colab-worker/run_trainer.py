import os
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from src.config import load_worker_config
from src.api_client import ApiClient
from src.trainer import ModelTrainerEngine

def main():
    print("Iniciant V2 Trainer Worker...")
    config = load_worker_config()
    
    # Podem injectar el max_training_seconds via variable d'entorn
    tiempo_limite = int(os.environ.get("V2_TRAINER_MAX_SECONDS", 0))

    api = ApiClient(
        base_url=config.api_base_url,
        token=config.api_token,
        timeout_seconds=config.api_timeout_seconds,
        api_path_prefix=config.api_path_prefix,
    )
    
    # L'engine d'entrenament pesat necessita aquesta configuracio i limits
    engine = ModelTrainerEngine(api, {
        "max_training_seconds": tiempo_limite,
        "repo_root": str(repo_root)
    })
    
    print(f"Trainer configurat cap a l'API V2 a {config.api_base_url}{config.api_path_prefix}")
    if tiempo_limite > 0:
         print(f"Mode de prova activat: Entrenaments de max {tiempo_limite}s")
         
    engine.run_loop()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nTrainer aturat manualment per l'usuari.")
    except Exception as e:
        print(f"Error crític al Trainer: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
