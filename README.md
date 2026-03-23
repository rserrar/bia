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

Punt d'entrada recomanat (unificat):

- `docs/core.md`
- `docs/inventory.md`

- `ARCHITECTURE.md`: arquitectura tècnica global i decisions de disseny
- `COMPONENTS.md`: responsabilitats i interfícies de cada component
- `ROADMAP.md`: pla d'implementació per fases

## Estat actual

- API PHP base implementada i funcional sota `server-api/php/`
- Worker Colab base implementat sota `colab-worker/src/`
- Monitor local per polling implementat sota `local-frontend/src/`
- Contracte d'API alineat a `shared/schemas/api_contract.json`
- Trial LLM validat amb OpenAI (`gpt-5.4`) i creació de propostes per generació
- Reparació automàtica de candidats LLM activable amb `V2_LLM_REPAIR_ON_VALIDATION_ERROR=true`
- Verificació de compilació de propostes per run amb `ops/scripts/run_generated_proposals_compile_check.py`
- Entrenament automàtic operatiu: `validated_phase0 -> accepted -> training -> trained`
- Artifact del model entrenat guardat (`trained_model`) i metadades de training persistides a `llm_metadata`
- Supervisor operatiu amb auto-restart + auto-feed de feina (`ops/scripts/run_trainer_supervisor.py`)
- Visor runtime en temps real per CLI (`ops/scripts/watch_runtime_status.py`)

## Reutilització de codi

- Colab worker: 80-90% de reutilització prevista
- Server API: 95% de reutilització prevista
- Frontend local: 85-90% de reutilització prevista
- Pla d'entorn real: `ops/REAL_ENV_ROLLOUT.md`
- Guia de notebook Colab: `colab-worker/COLAB_NOTEBOOK_PLAN.md`
- Notebook runtime-ready: `colab-worker/V2_runtime_ready_colab.ipynb`
- Tauler de seguiment: `ops/PLAN_TRACKER.md`
- Checklist previ real: `ops/scripts/go_no_go_check.py`
- Runner Fase 0 de compilació/execució: `ops/scripts/run_phase0_model_validation.py`
- Config Fase 0: `ops/configs/phase0_model_validation.json`
- Trial curt LLM: `ops/scripts/run_llm_generation_trial.py`
- Probe de models/limits OpenAI: `ops/scripts/probe_openai_models.py`
- Prova de prompt complet: `ops/scripts/run_llm_full_prompt_check.py`
- Compile-check de propostes generades: `ops/scripts/run_generated_proposals_compile_check.py`
- Health check P0: `ops/scripts/p0_health_check.py`
- Smoke E2E final: `ops/scripts/run_e2e_final_smoke.py`
- Supervisor trainer: `ops/scripts/run_trainer_supervisor.py`
- Runtime watcher: `ops/scripts/watch_runtime_status.py`

## Layout de dades

Per executar el pipeline complet (validacions de models i entrenament de propostes) cal disposar d'uns fitxers CSV de dades.

- **Fitxers esperats** (vegeu `configs/experiment_config.json`):
  - Entrades:
    - `entrada_valors.csv`
    - `entrada_extra.csv`
    - `min.csv`
    - `max.csv`
  - Sortides:
    - `sortida_min.csv`
    - `sortida_max.csv`
    - `sortida_tb.csv`
    - `sortida_sl.csv`
    - `sortida_sn.csv`
    - `sortida_valors.csv`

Per defecte, l'arrel de dades es llegeix de `data_dir` a `configs/experiment_config.json`. El valor actual és:

```json
  "data_dir": "data/min"
```

- **Dataset mínim recomanat**:
  - Col·loca els CSV de prova a `data/min/`.
  - Els noms esperats actuals per sortides són `sortida_min.csv`, `sortida_max.csv`, `sortida_tb.csv`, `sortida_sl.csv`, `sortida_sn.csv`, `sortida_valors.csv`.

Cap d'aquests fitxers de dades es versiona en aquest directori; els has de crear/ubicar tu segons el teu cas d'ús.

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

4. Cicle curt automàtic (recomanat en fase de proves):

```bash
cd V2
python ops/scripts/run_e2e_final_smoke.py
```

5. Operació contínua en proves (trainer + auto-feed + health checks):

```bash
cd V2
python ops/scripts/run_trainer_supervisor.py
```

## Principis de robustesa

- Checkpoints i resum automàtic de sessions
- Reintents amb backoff exponencial
- Idempotència en operacions crítiques
- Observabilitat (events, mètriques, errors, heartbeat)
- Fallback d'emmagatzematge (Drive principal, servidor secundari)

## Estat LLM V2 (fet i pendent)

### Fet

- Integració E2E de generació de propostes LLM a cada generació del worker.
- Compatibilitat d'endpoint/model OpenAI amb fallback de paràmetres i validació de clau.
- Trial operatiu a Colab amb `ops/scripts/run_llm_generation_trial.py`.
- Probe de models/límits amb `ops/scripts/probe_openai_models.py`.
- Validació de prompt complet (mode sec i mode real) amb `ops/scripts/run_llm_full_prompt_check.py`.
- Compile-check de propostes per `run_id` amb `ops/scripts/run_generated_proposals_compile_check.py`.
- Reparació automàtica de candidats invàlids activable amb `V2_LLM_REPAIR_ON_VALIDATION_ERROR=true`.
- Normalització de schema de `model_definition` abans de validar/compilar.

### Pendent

- Incrementar qualitat arquitectònica de les propostes (ara compilen, però sovint són simplificades).
- Afegir mètriques de qualitat post-compilació més enllà de "compila/no compila".
- Definir criteris de promoció automàtica de propostes a fases posteriors.
- Consolidar benchmark de 10+ generacions amb KPIs estables per model i configuració.
- Refinar el flux de reparació perquè preservi millor la intenció original del model.

### Proper pas recomanat

1. Executar trial de 10 generacions amb reparació activa.
2. Executar compile-check del `run_id` resultant.
3. Revisar distribució de `used_inputs` i `output_heads` per detectar simplificacions excessives.
4. Ajustar prompt/validacions amb objectiu de millorar qualitat mantenint taxa de compilació alta.

