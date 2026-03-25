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
- `GET /runs/{run_id}/timeline`
- `GET /runs/{run_id}/references`
- `GET /model-proposals?limit=...`
- `GET /proposals?limit=...`
- `GET /model-proposals/{proposal_id}`
- `GET /champion/run/{run_id}`
- `GET /champion/global`
- `GET /models/shortlist`
- `GET /models/{proposal_id}/detail-view`
- `GET /models/compare?left=...&right=...`
- `GET /models/{proposal_id}/artifacts`
- `GET /artifacts/{artifact_id}/download`
- `POST /execution-requests`
- `GET /execution-requests`
- `GET /execution-requests/pending`
- `GET /execution-requests/{request_id}`
- `POST /execution-requests/{request_id}/claim`
- `POST /execution-requests/{request_id}/heartbeat`
- `POST /execution-requests/{request_id}/start`
- `POST /execution-requests/{request_id}/complete`
- `POST /execution-requests/{request_id}/fail`
- `POST /execution-requests/{request_id}/cancel`
- `POST /model-proposals/{proposal_id}/status`
- `POST /model-proposals/{proposal_id}/enqueue-phase0`
- `POST /model-proposals/lock-for-training`
- `POST /runs/{run_id}/artifacts/upload`
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

Increment 3 de productització:

- `GET /runs/{id}/timeline`
  - timeline ordenada d'events per a monitor i frontend extern
- `GET /models/{proposal_id}/detail-view`
  - vista rica de model (`training_kpis`, `prompt_audit`, champion metadata, `selection_view`, payload base)
- `GET /models/compare`
  - comparacio A/B de dos models ja resolta al backend

Increment d'artifacts canònics:

- `POST /runs/{run_id}/artifacts/upload`
  - permet pujar el fitxer real del model al servidor
- `GET /models/{proposal_id}/artifacts`
  - retorna metadata frontend-ready dels artifacts del model
- `GET /artifacts/{artifact_id}/download`
  - descarrega l'artifact quan el backend canònic es `server`

Increment de resumabilitat:

- `GET /models/{proposal_id}/detail-view`
  - inclou `resume_state`
- `GET /models/{proposal_id}/artifacts`
  - inclou artifacts `checkpoint`
- `GET /runs/{run_id}/timeline`
  - mostra `training_checkpoint_saved`, `training_interrupted`, `training_resumed`, `training_resume_failed`, `training_restarted_from_scratch`

Nota de consistencia de score:

- si una proposal ja esta marcada com a champion actiu, la vista de champion usa el score persistit a `llm_metadata.champion_score` com a font principal.
- aixi s'evita desalineacio entre score de seleccio i score visualitzat al monitor.

Nota de monitor:

- `monitor.php` fa de proxy de descàrrega autenticat (`download_artifact_id`) per evitar exposar el token API al navegador.

Persistència actual al servidor (font per frontend):

- `runs`
- `events`
- `metrics`
- `artifacts`
- `model_proposals`

Els frontends han de consumir aquesta capa, no dependre de logs locals de Colab.

Control plane v1:

- `execution_request` es la nova entitat de control d'execucio
- el servidor actua com a control plane
- Colab actua com a executor via `run_worker_loop.py`
