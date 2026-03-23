# Runtime Flow

Aquest es el flux curt recomanat en fase de proves.

## Preconditions

- `V2_API_BASE_URL` i `V2_API_TOKEN` configurats.
- Repo actualitzat tant a Colab com al servidor (`git pull`).
- API activa i prefix validat (`probe_api_prefix.py`).

## Flux curt (recomanat)

1. Smoke E2E automatic:

```bash
python ops/scripts/run_e2e_final_smoke.py
```

2. Operacio continua amb auto-feed:

```bash
python ops/scripts/run_trainer_supervisor.py
```

3. Observacio live:

```bash
python ops/scripts/watch_runtime_status.py
```

## Expected result

- `run_status=completed`
- almenys una proposta `trained`
- `latest_artifact_type=trained_model`
- `llm_metadata.training_kpis` i `llm_metadata.trained_model_uri` presents a la proposta entrenada.

## Important env vars

- `V2_LLM_ENABLED`
- `V2_BOOTSTRAP_SEED_MODEL_IF_EMPTY`
- `V2_API_TIMEOUT_SECONDS`
- `V2_SUPERVISOR_AUTO_FEED`
- `V2_SUPERVISOR_FEED_GENERATIONS`
- `V2_SUPERVISOR_AUTO_FEED_MIN_INTERVAL_SECONDS`
