# Selection Policy v1

This document defines a deterministic and auditable policy for selecting reference models for the next LLM generation cycle.

## Goal

Convert model selection from implicit heuristics into an explicit contract that can be applied with or without the LLM.

## Policy contract

Policy id:

- `selection_policy_v1`

Input per candidate:

- `proposal.status`
- `proposal.llm_metadata.training_kpis`
- `proposal.llm_metadata.kpi_evaluation`
- `proposal.llm_metadata.kpi_result`

Output per candidate:

- `eligible` (boolean)
- `score` (0..100)
- `selection_reason`
- `constraints_failed[]`
- `score_breakdown` (weights, normalized components, penalties, metrics_used)

## Scoring function

Weights (default):

- `loss`: 0.55
- `time`: 0.15
- `stability`: 0.20
- `quality`: 0.10

Normalization:

- `normalized_loss = max(0, 1 - min(val_loss_total, loss_cap) / loss_cap)`
- `normalized_time = max(0, 1 - min(training_time_seconds, time_cap_seconds) / time_cap_seconds)`
- `normalized_stability = 1.0 (trained), 0.75 (accepted), 0.55 (validated_phase0)`
- `normalized_quality = 1.0 (kpi_result=promoted), 0.7 (missing), 0.5 (other)`

Raw score:

- `raw_score = 100 * (w_loss*loss + w_time*time + w_stability*stability + w_quality*quality)`

Penalties:

- if `training_time_seconds > hard_time_limit_seconds` then `-15` points.

Final score:

- `score = max(0, raw_score - penalties)`

## Eligibility constraints

Candidate is eligible only if all are true:

- `status in {trained, accepted, validated_phase0}`
- `val_loss_total` exists (from `training_kpis` or `kpi_evaluation`)
- `kpi_result != rejected_by_loss`

If any constraint fails:

- `eligible=false`
- `selection_reason=ineligible_due_to_constraints`

## Promotion criteria

Current system behavior with this policy:

- Top N eligible candidates by descending `score` are passed as `reference_models` to the LLM context.
- N is controlled by `V2_LLM_NUM_REFERENCE_MODELS`.
- If no eligible candidates exist, local seed fallback is used.

## Traceability requirements

For each generation, `llm_metadata.prompt_audit` stores:

- `reference_policy_version`
- `reference_models_selected[]`
- `reference_models_count`

Each selected reference includes:

- `proposal_id`
- `score`
- `selection_reason`
- `score_breakdown`

This makes selection auditable independently from model output quality.

## Relationship with LLM

- The policy computes ranking deterministically.
- The LLM does not choose references directly.
- The LLM receives preselected references and uses them for contextual generation.

This keeps selection reusable and testable even if provider/model changes.

## Robustness rules

- Hard constraints prevent using clearly invalid candidates.
- Penalties discourage slow models dominating by loss only.
- Fallback seed prevents total pipeline stall when candidate pool is empty.
- Rejected candidates are traceable through `constraints_failed` and selection trace.
