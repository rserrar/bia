# Execution Control Plane

Aquest document defineix la v1 del control plane server-driven.

## Goal

Fer que Colab deixi de ser un conjunt de scripts manuals i passi a ser un worker executor que consumeix plans d'execucio definits al servidor.

## Entity: execution_request

Camps principals:

- `request_id`
- `type`
- `status`
- `config`
- `created_at`
- `updated_at`
- `claimed_by_worker`
- `claimed_at`
- `heartbeat_at`
- `attempts`
- `result_summary`
- `result_artifacts`
- `error_summary`

## Config v1

`execution_request.config` actual:

- `profile`
- `generations`
- `models_per_generation`
- `champion_scope`
- `auto_feed`
- `resume_enabled`
- `bootstrap_seed_model_if_empty`
- `auto_process_proposals_phase0`
- `llm_min_interval_seconds`
- `execution_mode`
- `dataset_mode`
- `type_description`

Status valids:

- `pending`
- `claimed`
- `running`
- `completed`
- `failed`
- `cancelled`

## Execution types v1

- `smoke_run`
- `micro_training`
- `integration_matrix`
- `resume_training`
- `cleanup`

Perfil d'execucio visible al monitor:

- `small_test`: validacio rapida del pipeline amb dataset petit.
- `default`: configuracio equilibrada.
- `real_large`: pensat per dataset gran i cost/temps alts.

## Canonical loop

`run_worker_loop.py` fa:

1. consulta pendents al servidor
2. reclama una request (`claim`)
3. la marca `running`
4. executa el tipus corresponent
5. reporta `complete` o `fail`
6. torna a fer polling

## Flux real actual de generacions

Flux actual esperat del worker V2:

1. `generation 0` = baseline
2. no crea models nous en aquesta generació inicial
3. `generation 1..N` creen models nous amb l'LLM
4. cada generació espera que la seva cua es vagi resolent abans de donar-la per tancada
5. quan queda només un model entrenant-se d'una generació, es pot fer prefetch de la següent
6. el run no es marca `completed` fins que la cua total d'entrenament s'ha buidat

Events operatius nous i importants:

- `generation_baseline_ready`
- `generation_drain_wait_started`
- `generation_drain_wait_completed`
- `generation_prefetch_started`
- `training_drain_wait_started`
- `training_drain_wait_completed`

## Runtime contract (server-driven)

El servidor es la font canonica de configuracio de l'execucio.

El worker Colab no ha d'inventar defaults diferents per a una request concreta. Quan reclama una `execution_request`, trasllada al runtime almenys:

- `generations`
- `models_per_generation`
- `resume_enabled`
- `bootstrap_seed_model_if_empty`
- `auto_process_proposals_phase0`
- `llm_min_interval_seconds`
- `champion_scope`

Conseqüencia practica:

- un `1 x 1` amb `bootstrap_seed_model_if_empty=false` ha de generar exactament 1 model nou
- un `2 x 2` ha de generar exactament 4 models nous
- si hi ha un champion previ al servidor, aquest es pot reutilitzar com a referencia de prompt sense tocar configuracio manual de Colab

## Progress i resultat

Durant l'execucio, `result_summary` i la vista normalitzada exposen:

- `generations_total`
- `generations_completed`
- `models_generated`
- `models_trained`
- `current_stage`
- `current_stage_label`
- `run_ids`
- `current_run_id`
- `latest_event_type`
- `latest_artifact_type`

Per execucions acabades, el monitor i l'autopsia poden distingir entre:

- `champion_selected`
- `champion_kept`
- `champion_selection_skipped`

## Execution autopsy

Endpoint operatiu:

- `GET /execution-requests/{request_id}/autopsy?timeline_limit=40`

Retorna una vista compacta per operacio amb:

- estat general i timings
- lifecycle resumit
- outcome final
- `reference_context`
- extracte curt de logs rellevants
- runs associats amb `summary`, `timeline`, `references`, `proposals` i `artifacts`

## Repair loop

Quan una proposal falla per un error reparable, la V2 intenta mantenir viu el cicle:

- primer prova una reparacio LLM del model fallit
- si la reparacio falla, prova un reempla\u00e7 nou
- el resultat es reenvia a `phase0`

Metadades utiles per a genealogia i observabilitat:

- `repaired_from_proposal_id`
- `repair_mode`
- `repair_attempt`
- `repair_source_error`

Objectiu operatiu:

- evitar que una proposal dolenta consumeixi un slot sense reempla\u00e7
- mantenir sempre feina potencial a la cua mentre hi hagi marge per corregir o regenerar

Política actual:

- si una proposal falla per un error reparable, primer s'intenta `repair`
- si no funciona, es prova `replacement`
- es poden fer diversos intents abans de donar el cas per esgotat

Events útils per seguir-ho:

- `model_repair_started`
- `model_repair_failed`
- `model_repair_enqueued`
- `model_repair_exhausted`

## Guia curta per llegir execucions

Ordre típic de lectura:

1. `execution_request`
2. `run summary`
3. `events`
4. `autopsy`

Interpretació ràpida:

- `starting_trial` = encara no hi ha prou context al `result_summary`; potser el run ja està avançant però la request va endarrerida
- `run_id` buit durant massa estona = cal mirar el log directe de Colab
- `validated_phase0` = model generat i estructuralment acceptable, pendent d'entrenar
- `training` = model actualment en execució al trainer
- `trained` = model completat correctament
- `rejected` = model descartat a `phase0` o per fallada de trainer
- `partial_generation=true` = la generació LLM no ha produït tots els models previstos, però el sistema continua amb els disponibles

## Reclaim policy

Una request `claimed` o `running` amb `heartbeat_at` stale pot tornar a ser elegible.

Objectiu:

- tolerar caigudes de sessio Colab
- evitar requests bloquejades indefinidament

## Why this matters

- simplifica Colab
- centralitza configuracio i historial
- prepara una base molt millor per frontend extern
