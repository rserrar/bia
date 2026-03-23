# Estructura de directoris V2 (objectiu)

```text
V2/
  README.md
  STRUCTURE.md
  ARCHITECTURE.md
  COMPONENTS.md
  ROADMAP.md
  docs/
    README.md
    core.md
    runtime_flow.md
    server_api.md
    operations.md
    observability.md
    errors.md
    inventory.md

  colab-worker/
    src/
    configs/
    checkpoints/
    V2_runtime_ready_colab.ipynb
    COLAB_NOTEBOOK_PLAN.md

  server-api/
    php/
      configs/
      public/
      src/
      state/
    src/ (legacy/proves python)

  local-frontend/
    src/
    configs/

  shared/
    schemas/
    clients/
    utils/

  ops/
    scripts/
    healthchecks/

Scripts operatius clau actuals:

- `ops/scripts/run_e2e_final_smoke.py`
- `ops/scripts/run_trainer_supervisor.py`
- `ops/scripts/watch_runtime_status.py`
- `ops/scripts/p0_health_check.py`

  tests/
    integration/
    contract/
```

## Criteris

- Separació estricta per responsabilitat
- Codi compartit només a `shared/`
- Configuracions diferenciades per component
- Tests de contracte per evitar trencaments entre components
