# Colab Worker

Conté el codi d'execució automàtica del pipeline d'evolució de models.

Guia de notebook per prova real:

- `COLAB_NOTEBOOK_PLAN.md`
- `V2_runtime_ready_colab.ipynb`
- `V2_drive_zip_control_plane_colab.ipynb`
- Config de validació Fase 0: `../ops/configs/phase0_model_validation.json`

## Notebook nou per dataset gran des de Drive

Per a proves mes serioses amb dataset comprimit a Drive, fes servir:

- `V2_drive_zip_control_plane_colab.ipynb`

Pensat per al ZIP:

- `/content/drive/MyDrive/b-ia/dades/borsa_min.zip`

Aquest notebook:

- munta Drive i actualitza el repo
- extreu el ZIP dins `V2/data/runtime_drive/`
- detecta automàticament la carpeta que conté tots els CSV requerits
- imprimeix quantes files té cada CSV canònic per verificar que s'està usant el dataset correcte
- genera un `experiment_config.drive_runtime.json` apuntant al dataset extret
- configura l'entorn per al control plane server-driven
- arrenca `run_worker_loop.py`

Checklist abans d'arrencar el worker:

- verificar `csv_row_counts`
- confirmar que el ZIP i `dataset_dir` són els esperats
- confirmar:
  - `V2_LLM_USE_LEGACY_INTERFACE=false`
  - `V2_LLM_REPAIR_ON_VALIDATION_ERROR=true`
- si vols fallback Gemini:
  - `V2_LLM_FALLBACK_PROVIDER=gemini`
  - `GEMINI_API_KEY=...`
  - `V2_LLM_FALLBACK_MODEL=gemini-3-flash-preview`

Com llegir el log de Colab:

- `🪜 Generació 0 completada com a baseline` = correcte; no crea models nous
- `🤖 Fent petició... generació X` = crida LLM real
- `📩 Resposta rebuda...` = resposta LLM rebuda i parsejada
- `🧩 Proposal creada...` = proposal enviada a `phase0`
- `⏳ Esperant que la generació X es buidi...` = la generació està pendent de training/rebuig
- `⚡ Prefetch...` = s'està solapant la generació següent mentre l'últim model s'entrena
- `[trainer] 🔥 Training iniciat...` = el trainer ha començat realment
- `[trainer] 🔄 ... inici època` i `[trainer] ✅ Època ... completada` = seguiment d'entrenament útil
- `⛔ Rate limit LLM...` = toca esperar o activar fallback Gemini

Nota LLM:

- si vols fallback nadiu a Gemini, el notebook ha d'instal·lar `google-genai`
- defineix `V2_LLM_FALLBACK_PROVIDER=gemini` i `GEMINI_API_KEY` o `V2_LLM_FALLBACK_API_KEY`
- model recomanat per començar: `gemini-3-flash-preview`
- amb el fallback nadiu no cal indicar cap endpoint OpenAI-compatible per Gemini
- per al flux V2 actual, fixa `V2_LLM_USE_LEGACY_INTERFACE=false`
- deixa `V2_LLM_REPAIR_ON_VALIDATION_ERROR=true` per mantenir la reparació automàtica activa

## Layout de dades per al worker

El pipeline de training/validació fa servir la configuració d'experiment a `configs/experiment_config.json`.

- Camp clau:

```json
  "data_dir": "data/min"
```

- CSV esperats (relatius a `data_dir`):
  - `entrada_valors.csv`
  - `entrada_extra.csv`
  - `min.csv`
  - `max.csv`
  - `sortida_min.csv`
  - `sortida_max.csv`
  - `sortida_tb.csv`
  - `sortida_sl.csv`
  - `sortida_sn.csv`
  - `sortida_valors.csv`

### Mode de prova amb dataset mínim

Per a un test ràpid pots treballar amb un subconjunt de dades dins `data/min`:

1. Crea el directori `data/min` i col·loca-hi els CSV mínims necessaris amb els noms anteriors.
2. Edita `configs/experiment_config.json` i posa:

```json
  "data_dir": "data/min"
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
- `V2_API_TIMEOUT_SECONDS`
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
- `V2_BOOTSTRAP_SEED_MODEL_IF_EMPTY`
- `V2_TRIAL_MAX_GENERATIONS`
- `V2_TRIAL_HEARTBEAT_SECONDS`
- `V2_TRIAL_CODE_VERSION`
- `V2_TRIAL_VERIFY_LEGACY`

Quan `V2_AUTO_PROCESS_PROPOSALS_PHASE0=true`, el worker processa automàticament propostes en estat `queued_phase0`.
Quan `V2_BOOTSTRAP_SEED_MODEL_IF_EMPTY=true`, si no hi ha cap proposta al servidor es crea un model seed automàtic des de `V2_PROMPT_REFERENCE_MODEL_PATH`.
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
- El trainer actualitza events per època i registra artifact `trained_model` quan finalitza.

## Robustesa i Optimització de Memòria (V2.1)

El worker de Colab inclou millores crítiques per gestionar datasets grans i evitar bloquejos:

### Gestió de Memòria
- **Càrrega en float32**: Totes les dades es carreguen en precisió simple, reduint el consum de RAM al 50%.
- **Binary Cache (.npy)**: Els CSVs es converteixen automàticament a format binari en la primera lectura. Les següents càrregues són instantànies.
- **Memory Mapping (mmap)**: Les dades font no ocupen RAM física fins que no s'utilitzen realment, permetent treballar amb datasets que superen la RAM del sistema.
- **Pre-escalat Global**: Les dades s'escalen una sola vegada al principi del run, eliminant el temps de preparació per a cada model.

### Arquitectura Supervisada (Watchdog)
- **Multiprocessing**: El Trainer s'executa en un procés independent del Worker. Això aïlla el flux de generació de l'entrenament pesat de TensorFlow.
- **Supervisor**: El Worker monitoritza el Trainer. Si detecta que el Trainer està encallat (més de 10 minuts sense registrar activitat a l'API), el mata i el reinicia automàticament.
- **Flux Fluid**: S'ha eliminat la restricció rígida de generacions. El sistema ara treballa per **quota global**: seguirà generant i reparant models fins a assolir el nombre total de models entrenats configurat (ex: 4 gens x 2 models = 8 models totals).
- **Campions Globals**: L'LLM rep sempre els millors models de tota la run com a referència, garantint que l'evolució es basa en el millor coneixement disponible en cada moment.
- **Neteja Automàtica**: En iniciar, el worker tanca qualsevol procés orfe de sessions anteriors per evitar conflictes de recursos.
