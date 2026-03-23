# Operations

Guia operativa resumida de scripts P0.

## Quick commands

Health check:

```bash
python ops/scripts/p0_health_check.py
```

Trial curt LLM:

```bash
python ops/scripts/run_llm_generation_trial.py
```

Entrenament persistent amb auto-restart i auto-feed:

```bash
python ops/scripts/run_trainer_supervisor.py
```

Watcher runtime:

```bash
python ops/scripts/watch_runtime_status.py
```

Smoke E2E final (trial + trainer + validacio final):

```bash
python ops/scripts/run_e2e_final_smoke.py
```

## Colab background mode

Arrencar supervisor en segon pla:

```bash
nohup python -u ops/scripts/run_trainer_supervisor.py > /content/b-ia/colab-worker/checkpoints/supervisor_stdout.log 2>&1 &
```

Parar supervisor/trainer:

```bash
pkill -f "ops/scripts/run_trainer_supervisor.py" || true
pkill -f "colab-worker/run_trainer.py" || true
```

## Minimal preflight checklist

- API reachable i prefix resolt.
- `V2_API_TOKEN` valid.
- run/proposal paths responent 200.
- metadades de training persistides en `llm_metadata`.
