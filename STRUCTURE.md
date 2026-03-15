# Estructura de directoris V2 (objectiu)

```text
V2/
  README.md
  STRUCTURE.md
  ARCHITECTURE.md
  COMPONENTS.md
  ROADMAP.md

  colab-worker/
    src/
    configs/
    checkpoints/
    V2_real_run_notebook.ipynb
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

  tests/
    integration/
    contract/
```

## Criteris

- Separació estricta per responsabilitat
- Codi compartit només a `shared/`
- Configuracions diferenciades per component
- Tests de contracte per evitar trencaments entre components

