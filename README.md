# V2 - Plataforma d'Evolució de Models (Colab + API + Frontend Local)

## Objectiu

Aquest directori conté la nova versió del projecte.

La V2 es construeix amb 3 components separats:

- Colab Worker: execució automàtica del cicle d'evolució de models
- Server API: control d'estat, persistència, seguretat i coordinació
- Frontend Local (Windows): monitoratge i visualització de resultats

## Regles de treball

- A partir d'ara, tot el codi nou es crea dins `V2/`
- El codi antic fora de `V2/` es manté només com a referència
- Les interfícies entre components s'han de definir amb contractes clars (JSON/API)
- Cada execució ha de ser reproduïble (versions de codi i configuració)

## Estructura base prevista

```text
V2/
  colab-worker/
  server-api/
  local-frontend/
  shared/
  ops/
  docs/
  tests/
```

## Documentació inclosa

- `ARCHITECTURE.md`: arquitectura tècnica global i decisions de disseny
- `COMPONENTS.md`: responsabilitats i interfícies de cada component
- `ROADMAP.md`: pla d'implementació per fases

## Principis de robustesa

- Checkpoints i resum automàtic de sessions
- Reintents amb backoff exponencial
- Idempotència en operacions crítiques
- Observabilitat (events, mètriques, errors, heartbeat)
- Fallback d'emmagatzematge (Drive principal, servidor secundari)

