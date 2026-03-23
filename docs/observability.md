# Observability

Objectiu: saber que esta passant en runtime sense esperar al final.

## Fonts de veritat

- API summary: `/runs/{run_id}/summary`
- events per run: `/runs/{run_id}/events`
- proposals: `/model-proposals`
- monitor web: `server-api/php/public/monitor.php`

## Events clau a vigilar

- `llm_proposal_created`
- `proposal_auto_promoted_for_training`
- `model_training_started`
- `model_training_epoch_start`
- `model_training_epoch_end`
- `model_training_completed`
- `model_training_failed`

## Artifacts clau

- `checkpoint`
- `trained_model`

## Scripts per visibilitat

- `ops/scripts/watch_runtime_status.py` (resum continu)
- `ops/scripts/p0_health_check.py` (PASS/FAIL curt)

## Interpretacio rapida

- `proposals_by_status.training` puja: trainer actiu.
- `latest_artifact=trained_model`: model guardat correctament.
- `latest_event=model_training_completed`: cicle de training finalitzat.
- `trained_model_uri` + `training_kpis` a `llm_metadata`: traçabilitat completa.
