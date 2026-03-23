# Selection Policy v1.1

Selection Policy v1.1 extends v1 with two production-critical capabilities:

1. explicit champion selection,
2. context-dependent thresholds and weights.

## Scope

This policy is deterministic and auditable. It is used to rank reference candidates before the LLM prompt is built, and to derive champion status after training.

## Context profiles

Configured via `V2_SELECTION_POLICY_PROFILE`:

- `small_test` (or `small`, `test`): optimized for short validation cycles on reduced datasets.
- `real_large` (or `real`, `large`, `prod`): optimized for full dataset runs.
- `default`: balanced fallback.

Profile controls:

- weights (`loss`, `time`, `stability`, `quality`),
- caps (`loss_cap`, `time_cap_seconds`, `hard_time_limit_seconds`),
- champion gates (`champion_min_score`, `champion_margin_min`).

## Scoring contract

Same deterministic structure as v1:

- normalized component scores,
- weighted sum to `raw_score`,
- penalties,
- final bounded score in `0..100`.

Eligibility constraints are still mandatory:

- allowed status,
- available `val_loss_total`,
- not rejected by KPI gate.

## Champion selection contract

Configured via:

- `V2_CHAMPION_SCOPE=run|global` (default `run`)
- `V2_CHAMPION_MIN_SCORE` (optional override)
- `V2_CHAMPION_MARGIN_MIN` (optional override)

Flow:

1. evaluate eligible proposals in scope,
2. pick highest score,
3. apply `champion_min_score` gate,
4. if an existing champion exists, require margin `best_score - current_score >= champion_margin_min` to replace,
5. persist champion metadata and emit champion artifact/event.

Champion metadata fields:

- `champion_active`
- `champion_scope`
- `champion_policy_version`
- `champion_score`
- `champion_selection_reason`
- `champion_score_breakdown`
- `champion_source_run_id`

## LLM relationship

- policy performs ranking and selection,
- LLM receives selected references and context,
- LLM does not own deterministic selection logic.

This separation keeps behavior auditable and portable across LLM providers/models.

## Traceability

`prompt_audit` includes:

- `reference_policy_version`
- `reference_models_selected`
- `reference_models_count`

Runtime includes champion events/artifacts:

- `champion_selected`
- `champion_kept`
- `champion_selection_skipped`
- artifact type `champion_model`
