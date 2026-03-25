# Documentation Inventory

Aquesta carpeta `docs/` es el punt d'entrada unificat.

## Canonical docs (new hub)

- `docs/core.md`
- `docs/runtime_flow.md`
- `docs/architecture.md`
- `docs/components.md`
- `docs/roadmap.md`
- `docs/structure.md`
- `docs/selection_policy_v1.md`
- `docs/selection_policy_v1_1.md`
- `docs/clean_state_policy.md`
- `docs/legacy_inventory.md`
- `docs/runbook_operations.md`
- `docs/data_contract_frontend.md`
- `docs/execution_control_plane.md`
- `docs/server_api.md`
- `docs/operations.md`
- `docs/observability.md`
- `docs/errors.md`
- `docs/decisions_and_outcomes.md`
- `docs/coverage_audit.md`
- `docs/inventory.md`

## Existing project docs preserved

Root:

- `README.md`

Root legacy duplicated docs removed after migration:

- `STRUCTURE.md` (migrat a `docs/structure.md`)
- `ARCHITECTURE.md` (migrat a `docs/architecture.md`)
- `COMPONENTS.md` (migrat a `docs/components.md`)
- `ROADMAP.md` (migrat a `docs/roadmap.md`)

Colab worker:

- `colab-worker/README.md`
- `colab-worker/COLAB_NOTEBOOK_PLAN.md`

Server API:

- `server-api/README.md`

Ops:

- `ops/README.md`
- `ops/PLAN_TRACKER.md`
- `ops/IMPLEMENTATION_TODO.md`
- `ops/REAL_ENV_ROLLOUT.md`
- `ops/REPO_SETUP.md`

Other components:

- `local-frontend/README.md`
- `shared/README.md`
- `tests/README.md`
- `prompts/instruccions.md`

## Migration note

No s'ha eliminat ni mogut cap document antic.

La regla nova es:

- consulta rapida: `docs/core.md`
- detall per component: docs originals preservats
- troubleshooting: `docs/errors.md`
