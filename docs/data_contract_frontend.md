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
- `last_epoch_completed`
- `last_checkpoint_artifact_id`
- `last_checkpoint_epoch`
- `resumable`
- `resume_attempts`
- `resumed_from_checkpoint`
- `resume_checkpoint_uri`
- `training_interrupted_at`
- `resume_history`

També pot aparèixer dins `result_summary` d'una execution:

- `reference_context`

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

## Artifact policy

Backend canonic actual:

- servidor (`storage/artifacts/...`) quan l'upload a servidor funciona

Drive/local:

- es pot continuar usant com a origen temporal o copia local d'entrenament,
- pero no ha de ser la font principal per al frontend.

Metadata d'artifact exposada a frontend:

- `artifact_id`
- `artifact_type`
- `storage_backend`
- `artifact_uri`
- `download_url`
- `availability_status`
- `checksum`
- `timestamp`
- `metadata`

## Frontend-ready read endpoints

- `GET /runs`
- `GET /runs/{id}`
- `GET /runs/{id}/summary`
- `GET /runs/{id}/timeline`
- `GET /runs/{id}/references`
- `GET /execution-requests`
- `GET /execution-requests/{id}`
- `GET /execution-requests/{id}/autopsy`
- `GET /proposals`
- `GET /champion/run/{id}`
- `GET /champion/global`
- `GET /models/shortlist`
- `GET /models/{proposal_id}/detail-view`
- `GET /models/compare?left=...&right=...`
- `GET /models/{proposal_id}/artifacts`
- `GET /artifacts/{artifact_id}/download`

Upload intern actual:

- `POST /runs/{run_id}/artifacts/upload`

Aquest endpoint permet persistir una copia del model entrenat al servidor i evitar dependencia del path local de Colab.

## Execution UI contract

Per control operatiu, les execucions exposen camps pensats per monitor/UI:

- `progress.generations_total`
- `progress.generations_completed`
- `progress.models_generated`
- `progress.models_trained`
- `current_stage`
- `current_stage_label`
- `run_ids`
- `current_run_id`
- `elapsed_seconds`

Per autopsia/resum final:

- `outcome.final_status`
- `outcome.latest_event_type`
- `outcome.latest_artifact_type`
- `outcome.champion_decision`
- `outcome.proposal_id`
- `outcome.proposal_status`
- `outcome.trained_model_uri`
- `outcome.training_kpis_keys`
- `reference_context.reference_models_count`
- `reference_context.primary_reference_proposal_id`
- `reference_context.primary_reference_reason`

Quan una execucio reutilitza un champion previ com a context de prompt, la UI no ha d'inferir-ho de logs: ho ha de poder llegir de `reference_context` o de `GET /runs/{id}/references`.

Checkpoints:

- artifacts amb `artifact_type=checkpoint`
- cada checkpoint pot portar:
  - `epoch`
  - `checkpoint_uri`
  - `training_config_hash`

## Resume limitation (current v1)

El resume actual restaura pesos del model i epoca, pero no garanteix restauracio completa de l'estat intern de l'optimizer.

Conseqüencia practica:

- el training repren pesos i progrés funcionalment,
- pero no equival encara a una restauracio bit-a-bit del training state complet.

Per al frontend/auditoria, aquest comportament s'ha d'entendre com:

- `resume funcional per pesos`
- no `full optimizer state restore`

Nota d'accés des d'UI:

- el monitor web no ha d'enllaçar directament a `GET /artifacts/{artifact_id}/download` si l'API requereix token.
- el patró actual és usar `monitor.php?download_artifact_id=...` com a proxy autenticat.

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
