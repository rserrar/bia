# Components

## Colab worker

Responsabilitat:

- executar generacions,
- crear propostes LLM,
- i gestionar bootstrap seed quan no hi ha propostes.

Moduls clau:

- `colab-worker/src/engine.py`
- `colab-worker/src/llm_client.py`
- `colab-worker/src/config.py`
- `colab-worker/src/run_worker.py`

## Trainer worker

Responsabilitat:

- capturar propostes,
- entrenar-les,
- i publicar resultat final (status + artifact + metadata).

Moduls clau:

- `colab-worker/src/trainer.py`
- `colab-worker/run_trainer.py`

## Server API (PHP)

Responsabilitat:

- persistencia de `runs`, `events`, `metrics`, `artifacts`, `model_proposals`,
- coordinacio de cua i estats.

Punts clau:

- `server-api/php/public/index.php`
- `server-api/php/src/ApiService.php`
- `server-api/php/public/monitor.php`

Endpoints base de coordinacio:

- `POST /runs`
- `POST /runs/{run_id}/heartbeat`
- `POST /runs/{run_id}/events`
- `POST /runs/{run_id}/metrics`
- `POST /runs/{run_id}/artifacts`
- `GET /runs/{run_id}`
- `GET /runs/{run_id}/summary`

Endpoints de proposals:

- `GET /model-proposals?limit=...`
- `GET /model-proposals/{proposal_id}`
- `POST /model-proposals/{proposal_id}/status`
- `POST /model-proposals/{proposal_id}/enqueue-phase0`
- `POST /model-proposals/lock-for-training`

## Ops layer

Responsabilitat:

- salut del sistema,
- automatitzacio de cicles curts,
- operacio continua en mode prova.

Scripts clau:

- `ops/scripts/run_e2e_final_smoke.py`
- `ops/scripts/run_trainer_supervisor.py`
- `ops/scripts/p0_health_check.py`
- `ops/scripts/watch_runtime_status.py`

## Frontend local / shared / tests

- `local-frontend`: monitor de lectura per polling (interval tipic 15-60s i mode tolerant a desconnexio).
- `shared`: clients i utilitats compartides entre components.
- `tests`: capa prevista per contracte/integracio (encara en maduracio).

## Security split (operational)

- API token per escriptura/lectura d'operacio.
- Auditoria via events i timestamps d'actualitzacio.
