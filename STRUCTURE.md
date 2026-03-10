# Estructura de directoris V2 (objectiu)

```text
V2/
  README.md
  STRUCTURE.md
  ARCHITECTURE.md
  COMPONENTS.md
  ROADMAP.md

  colab-worker/
    notebook/
    src/
    configs/
    checkpoints/

  server-api/
    src/
    migrations/
    configs/

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

