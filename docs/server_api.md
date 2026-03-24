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
- `GET /runs/{run_id}/references`
- `GET /model-proposals?limit=...`
- `GET /proposals?limit=...`
- `GET /model-proposals/{proposal_id}`
- `GET /champion/run/{run_id}`
- `GET /champion/global`
- `GET /models/shortlist`
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

## UI-first read contracts

Els endpoints nous de lectura estan pensats per monitor i futur frontend extern.

- `GET /proposals`
  - proposals enriquides per UI (`training_kpis`, `trained_model_uri`, `prompt_audit`, info champion)
- `GET /champion/run/{id}`
  - champion de run + top candidates + policy metadata
- `GET /champion/global`
  - champion global + ranking global
- `GET /runs/{id}/references`
  - transparència de prompt: quins models s'han passat al LLM
  - inclou `role` (`top`, `reference`, `fallback`, `exploration`)
- `GET /models/shortlist`
  - shortlist consumible directament per UI (score, rationale, artifact)
  - inclou `primary_kpi`

Increment 2 de productització:

- `GET /runs/{id}/summary` inclou `summary_text`
- `GET /champion/run/{id}` i `GET /champion/global` inclouen `delta_from_previous` i `primary_factors` a `top_candidates`
