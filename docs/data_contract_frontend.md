# Data Contract For Frontend

Aquest document descriu quines dades s'envien des de Colab/Python, on es persisteixen al servidor i quins camps ha d'assumir un frontend professional.

## Canonical rule

El frontend no ha de dependre de logs locals de Colab.

La font canonica per UI es el servidor via read API.

## Data emitted from Colab/Python

### Runs

S'envia:

- `run_id`
- `status`
- `generation`
- `code_version`
- `heartbeat_at`
- `metadata`

### Events

S'envien events de:

- run lifecycle
- proposal generation
- phase0 processing
- training start/end per epoca
- champion selection
- API retry telemetry
- cleanup / watchdog

### Metrics

S'envien metriques resum per run/model, incloent:

- `val_loss_total`
- `models_evaluated`
- altres metriques agregades de generacio

### Artifacts

S'envien artifacts com:

- `trained_model`
- `champion_model`
- altres artifacts de suport si s'afegeixen en el futur

### Model proposals

Cada proposal inclou:

- `proposal_id`
- `status`
- `source_run_id`
- `base_model_id`
- `proposal` (payload del model)
- `llm_metadata`

## Important llm_metadata fields

Els camps rellevants per UI avui son:

- `training_kpis`
- `trained_model_uri`
- `prompt_audit`
- `champion_active`
- `champion_scope`
- `champion_score`
- `champion_policy_version`
- `champion_policy_profile`
- `champion_selection_reason`
- `champion_score_breakdown`
- `kpi_evaluation`
- `kpi_result`

## Server persistence model

El servidor persisteix aquestes col.leccions:

- `runs`
- `events`
- `metrics`
- `artifacts`
- `model_proposals`

Backends disponibles:

- JSON state store
- SQLite state store

## Frontend-ready read endpoints

- `GET /runs`
- `GET /runs/{id}`
- `GET /runs/{id}/summary`
- `GET /runs/{id}/timeline`
- `GET /runs/{id}/references`
- `GET /proposals`
- `GET /champion/run/{id}`
- `GET /champion/global`
- `GET /models/shortlist`
- `GET /models/{proposal_id}/detail-view`
- `GET /models/compare?left=...&right=...`

## What is not canonical for UI

- `logs/llm_interactions/` a Colab
- stdout/stderr del notebook
- fitxers temporals locals no persistits al servidor

## Frontend assumptions

Un frontend extern pot assumir que el servidor ja ofereix:

- estat de runs
- timeline d'events
- shortlist de models
- champion run/global
- transparència de prompt
- detall de model
- comparacio A/B de models

Sense necessitat de reproduir lògica de scoring, champion o ranking al client.
