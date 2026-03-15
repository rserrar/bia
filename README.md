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
- Trial LLM validat amb OpenAI (`gpt-5.4`) i creació de propostes per generació
- Reparació automàtica de candidats LLM activable amb `V2_LLM_REPAIR_ON_VALIDATION_ERROR=true`
- Verificació de compilació de propostes per run amb `ops/scripts/run_generated_proposals_compile_check.py`

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
- Trial curt LLM: `ops/scripts/run_llm_generation_trial.py`
- Probe de models/limits OpenAI: `ops/scripts/probe_openai_models.py`
- Prova de prompt complet: `ops/scripts/run_llm_full_prompt_check.py`
- Compile-check de propostes generades: `ops/scripts/run_generated_proposals_compile_check.py`

## Layout de dades

Per executar el pipeline complet (validacions de models i entrenament de propostes) cal disposar d'uns fitxers CSV de dades.

- **Fitxers esperats** (vegeu `configs/experiment_config.json`):
  - Entrades:
    - `entrada_valors.csv`
    - `entrada_extra.csv`
    - `min.csv`
    - `max.csv`
  - Sortides:
    - `sortida_min_7d.csv`
    - `sortida_max_7d.csv`
    - `sortida_tb.csv`
    - `sortida_sl.csv`
    - `sortida_sn.csv`
    - `sortida_valors_7d.csv`

Per defecte, l'arrel de dades es llegeix de `data_dir` a `configs/experiment_config.json`. El valor per defecte és:

```json
  "data_dir": "V2/data"
```

- **Dataset mínim recomanat**:
  - Pots crear un subconjunt de dades per proves dins `V2/data/min` i, a continuació:
    - editar `configs/experiment_config.json` i posar `"data_dir": "V2/data/min"`, o
    - mantenir `"data_dir": "V2/data"` i col·locar el mínim de fitxers directament a `V2/data/`.

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

