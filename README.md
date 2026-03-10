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

## Estat actual

- API PHP base implementada i funcional sota `server-api/php/`
- Worker Colab base implementat sota `colab-worker/src/`
- Monitor local per polling implementat sota `local-frontend/src/`
- Contracte d'API alineat a `shared/schemas/api_contract.json`

## Reutilització de codi

- Colab worker: 80-90% de reutilització prevista
- Server API: 95% de reutilització prevista
- Frontend local: 85-90% de reutilització prevista
- Pla d'entorn real: `ops/REAL_ENV_ROLLOUT.md`
- Guia de notebook Colab: `colab-worker/COLAB_NOTEBOOK_PLAN.md`
- Notebook executable: `colab-worker/V2_real_run_notebook.ipynb`
- Tauler de seguiment: `ops/PLAN_TRACKER.md`
- Checklist previ real: `ops/scripts/go_no_go_check.py`
- Runner Fase 0 de compilació/execució: `ops/scripts/run_phase0_model_validation.py`
- Config Fase 0: `ops/configs/phase0_model_validation.json`

## Posada en marxa local (stack mínima)

1. Iniciar API PHP:

```bash
cd V2/server-api/php/public
php -S 127.0.0.1:8080
```

2. Executar smoke test API (nova terminal):

```bash
cd V2
python ops/scripts/smoke_test_api.py
```

3. Executar watchdog de heartbeat (opcional):

```bash
cd V2
python ops/scripts/watchdog_retry.py
```

## Principis de robustesa

- Checkpoints i resum automàtic de sessions
- Reintents amb backoff exponencial
- Idempotència en operacions crítiques
- Observabilitat (events, mètriques, errors, heartbeat)
- Fallback d'emmagatzematge (Drive principal, servidor secundari)

