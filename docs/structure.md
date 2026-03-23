# Structure

Estructura actual orientada a runtime i operacio:

```text
V2/
  docs/                    # hub central de documentacio
  colab-worker/            # worker + trainer + notebooks
  server-api/              # API PHP + monitor
  local-frontend/          # monitor local per polling
  shared/                  # clients i utilitats comunes
  ops/                     # scripts de validacio i operacio
  configs/ config/ prompts/
  models/ data/
  tests/
```

## Documentation policy

- Canonical docs al directori `docs/`.
- Documents historics fora de `docs/` nomes si aporten valor no duplicat.
- Documents de tracking viu (`PLAN_TRACKER`, `IMPLEMENTATION_TODO`) es mantenen mentre no tinguin substitut equivalent.

## Criteris de disseny estructural

- Separacio estricta per responsabilitat.
- Codi compartit nomes a `shared/`.
- Configuracio diferenciada per component.
- Proves de contracte/integracio com a capa de seguretat evolutiva.
