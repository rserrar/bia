# Colab Worker

Conté el codi d'execució automàtica del pipeline d'evolució de models.

Guia de notebook per prova real:

- `COLAB_NOTEBOOK_PLAN.md`
- `V2_real_run_notebook.ipynb`
- Config de validació Fase 0: `../ops/configs/phase0_model_validation.json`

## Layout de dades per al worker

El pipeline de training/validació fa servir la configuració d'experiment a `configs/experiment_config.json`.

- Camp clau:

```json
  "data_dir": "V2/data"
```

- CSV esperats (relatius a `data_dir`):
  - `entrada_valors.csv`
  - `entrada_extra.csv`
  - `min.csv`
  - `max.csv`
  - `sortida_min_7d.csv`
  - `sortida_max_7d.csv`
  - `sortida_tb.csv`
  - `sortida_sl.csv`
  - `sortida_sn.csv`
  - `sortida_valors_7d.csv`

### Mode de prova amb dataset mínim

Per a un test ràpid pots treballar amb un subconjunt de dades dins `V2/data/min`:

1. Crea el directori `V2/data/min` i col·loca-hi els CSV mínims necessaris amb els noms anteriors.
2. Edita `configs/experiment_config.json` i posa:

```json
  "data_dir": "V2/data/min"
```

Després d'això, el worker (`colab-worker/src/run_worker.py`) i els scripts d'`ops` que usen l'experiment podran llegir directament el dataset des d'aquest directori.

## Compatibilitat amb models legacy (opcional)

El worker pot verificar que una definició de model de la versió antiga es continua construint.
Per executar aquesta verificació cal tenir TensorFlow instal·lat a l'entorn.

En entorns antics de Colab es feia servir aquest layout:

- `/content/b-ia/models/base/model_exemple_complex_v1.json`
- `/content/b-ia/config_experiment.json`
- `/content/b-ia/utils/model_builder.py`

Ara, el flux recomanat és usar els equivalents dins `V2/`:

- `models/base/model_exemple_complex_v1.json`
- `configs/experiment_config.json`
- `shared/utils/model_builder.py`

Les variables `V2_LEGACY_*` continuen existint només com a mode de compatibilitat.

Variables:

- `V2_API_BASE_URL`
- `V2_API_PATH_PREFIX`
- `V2_API_TOKEN`
- `V2_VERIFY_LEGACY_MODEL_BUILD`
- `V2_LEGACY_BUILD_CHECK_STRICT`
- `V2_LEGACY_MODEL_JSON_PATH`
- `V2_LEGACY_EXPERIMENT_CONFIG_PATH`
- `V2_LEGACY_BUILDER_PATH`
- `V2_AUTO_PROCESS_PROPOSALS_PHASE0`
- `V2_PROPOSALS_PHASE0_BATCH_SIZE`
- `V2_LLM_ENABLED`
- `V2_LLM_USE_LEGACY_INTERFACE`
- `V2_LLM_PROVIDER`
- `V2_LLM_ENDPOINT`
- `V2_LLM_API_KEY`
- `V2_LLM_MODEL`
- `V2_LLM_TIMEOUT_SECONDS`
- `V2_LLM_TEMPERATURE`
- `V2_LLM_MAX_TOKENS`
- `V2_LLM_SYSTEM_PROMPT`
- `V2_LLM_CONFIG_FILE`
- `V2_LLM_PROMPT_TEMPLATE_FILE`
- `V2_LLM_FIX_ERROR_PROMPT_FILE`
- `V2_LLM_ARCHITECTURE_GUIDE_FILE`
- `V2_LLM_EXPERIMENT_CONFIG_FILE`
- `V2_LLM_NUM_NEW_MODELS`
- `V2_LLM_NUM_REFERENCE_MODELS`
- `V2_LLM_MIN_INTERVAL_SECONDS`
- `V2_LLM_REPAIR_ON_VALIDATION_ERROR`
- `V2_TRIAL_MAX_GENERATIONS`
- `V2_TRIAL_HEARTBEAT_SECONDS`
- `V2_TRIAL_CODE_VERSION`
- `V2_TRIAL_VERIFY_LEGACY`

Quan `V2_AUTO_PROCESS_PROPOSALS_PHASE0=true`, el worker processa automàticament propostes en estat `queued_phase0`.
El client API prova automàticament els prefixes ``, `/public/index.php` i `/public` quan rep 404.
Quan `V2_LLM_ENABLED=true`, el worker genera propostes de model per generació i les envia a `/model-proposals`.
Amb `V2_LLM_USE_LEGACY_INTERFACE=true` reaprofita `utils/llm_interface.py` existent; si no, usa client OpenAI-compatible intern.
`V2_LLM_CONFIG_FILE` permet carregar clau i model des de JSON (ex: `config/llm_settings.json`) i admet `openai_api_key_env_var`.
`V2_LLM_MIN_INTERVAL_SECONDS` ajuda a reduir errors 429 separant crides LLM entre generacions.
`V2_LLM_REPAIR_ON_VALIDATION_ERROR=true` activa reparació automàtica reutilitzant `prompts/fix_model_error.txt` quan el candidat no és compilable.
Per prova de múltiples generacions curtes: `python ops/scripts/run_multi_generation_trial.py`.
Per provar models i límits disponibles d'OpenAI: `python ops/scripts/probe_openai_models.py`.
Per provar prompt complet i crear proposta a API: `python ops/scripts/run_llm_full_prompt_check.py`.
`run_llm_full_prompt_check.py` fa mode sec per defecte (`V2_PROMPT_SEND_TO_LLM=false`), útil per validar el prompt sense gastar tokens.
Per compilar propostes creades en un run concret: `python ops/scripts/run_generated_proposals_compile_check.py` amb `V2_TARGET_RUN_ID`.

Flux recomanat per validar V2 amb LLM real:

1. `python ops/scripts/probe_openai_models.py`
2. `python ops/scripts/run_llm_generation_trial.py`
3. `python ops/scripts/run_generated_proposals_compile_check.py`

Variables clau per estabilitzar trial:

- `V2_LLM_TRIAL_MODEL=gpt-5.4`
- `V2_LLM_TRIAL_ENDPOINT=https://api.openai.com/v1/chat/completions`
- `V2_LLM_REPAIR_ON_VALIDATION_ERROR=true`
- `V2_LLM_FIX_ERROR_PROMPT_FILE=prompts/fix_model_error.txt`

Notes operatives:

- Si el trial mostra endpoint amb backticks o espais, fes `git pull` a `/content/b-ia` i torna a executar.
- Missatges CUDA/cuDNN a Colab CPU són informatius; no impliquen error funcional del worker.
