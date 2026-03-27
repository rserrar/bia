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

## Reclaim policy

Una request `claimed` o `running` amb `heartbeat_at` stale pot tornar a ser elegible.

Objectiu:

- tolerar caigudes de sessio Colab
- evitar requests bloquejades indefinidament

## Why this matters

- simplifica Colab
- centralitza configuracio i historial
- prepara una base molt millor per frontend extern
