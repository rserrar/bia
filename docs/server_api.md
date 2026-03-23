# Server API

API de coordinacio i persistencia del sistema.

## Prefix and routing

La plataforma suporta rutes desplegades com:

- ``
- `/public/index.php`
- `/public`

Els clients del repo ja fan autodeteccio de prefix quan reben `404`.

## Endpoints clau

- `POST /runs`
- `POST /runs/{run_id}/heartbeat`
- `POST /runs/{run_id}/events`
- `POST /runs/{run_id}/metrics`
- `POST /runs/{run_id}/artifacts`
- `GET /runs/{run_id}`
- `GET /runs/{run_id}/summary`
- `GET /model-proposals?limit=...`
- `GET /model-proposals/{proposal_id}`
- `POST /model-proposals/{proposal_id}/status`
- `POST /model-proposals/{proposal_id}/enqueue-phase0`
- `POST /model-proposals/lock-for-training`
- `POST /maintenance/process-model-proposals-phase0`

## Metadata behavior (critical)

`POST /model-proposals/{proposal_id}/status` admet `metadata_updates`.

Aquest camp s'ha de persistir dins `llm_metadata` per guardar:

- `training_kpis`
- `trained_model_uri`
- qualsevol marca operativa extra (`probe_meta`, etc.)

Si aquests camps no es guarden, revisar desplegament real de:

- `server-api/php/public/index.php`
- `server-api/php/src/ApiService.php`

## Monitor auth

`monitor.php` suporta:

- login usuari/contrasenya (actualment incrustat al codi)
- token compatible (query/header)

En entorn real, recomanat passar credencials a `.env` i evitar hardcode.
