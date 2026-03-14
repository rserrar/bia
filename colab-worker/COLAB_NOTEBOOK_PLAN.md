# Guia de notebook Colab per a prova real

## Objectiu

Executar la V2 en Colab reutilitzant el codi existent del worker i el contracte API actual.

## Cèl·lula 1: Preparar entorn

```python
!pip install -q requests tensorflow
```

## Cèl·lula 2: Muntar Drive i clonar/actualitzar codi

```python
from google.colab import drive
drive.mount('/content/drive')
```

```python
%cd /content
!test -d b-ia && (cd b-ia && git pull) || git clone https://github.com/rserrar/bia.git b-ia
%cd /content/b-ia/V2
```

## Cèl·lula 3: Variables de run

```python
import os
V2_API_BASE_URL = "https://<api-real>"
V2_API_PATH_PREFIX = ""
V2_API_TOKEN = "<token>"
if "<api-real>" in V2_API_BASE_URL or "<token>" in V2_API_TOKEN:
    raise RuntimeError("Configura V2_API_BASE_URL i V2_API_TOKEN")
os.environ["V2_API_BASE_URL"] = V2_API_BASE_URL
os.environ["V2_API_PATH_PREFIX"] = V2_API_PATH_PREFIX
os.environ["V2_API_TOKEN"] = V2_API_TOKEN
os.environ["V2_CODE_VERSION"] = "real-colab-v2"
os.environ["V2_CHECKPOINT_PATH"] = "/content/drive/MyDrive/bia_v2/run_state.json"
os.environ["V2_HEARTBEAT_INTERVAL_SECONDS"] = "30"
os.environ["V2_MAX_GENERATIONS"] = "3"
os.environ["V2_AUTO_PROCESS_PROPOSALS_PHASE0"] = "true"
os.environ["V2_PROPOSALS_PHASE0_BATCH_SIZE"] = "20"
os.environ["V2_LLM_ENABLED"] = "false"
os.environ["V2_LLM_USE_LEGACY_INTERFACE"] = "true"
os.environ["V2_LLM_PROVIDER"] = "mock"
os.environ["V2_LLM_ENDPOINT"] = "https://api.openai.com/v1/chat/completions"
os.environ["V2_LLM_API_KEY"] = ""
os.environ["V2_LLM_MODEL"] = "gpt-5.3-codex"
os.environ["V2_LLM_CONFIG_FILE"] = "/content/b-ia/config/llm_settings.json"
os.environ["V2_LLM_PROMPT_TEMPLATE_FILE"] = "prompts/generate_new_models.txt"
os.environ["V2_LLM_ARCHITECTURE_GUIDE_FILE"] = "prompts/instruccions.md"
os.environ["V2_LLM_EXPERIMENT_CONFIG_FILE"] = "/content/b-ia/config_experiment.json"
os.environ["V2_LLM_NUM_NEW_MODELS"] = "1"
os.environ["V2_LLM_NUM_REFERENCE_MODELS"] = "3"
os.environ["V2_VERIFY_LEGACY_MODEL_BUILD"] = "true"
os.environ["V2_LEGACY_BUILD_CHECK_STRICT"] = "false"
os.environ["V2_LEGACY_MODEL_JSON_PATH"] = "/content/b-ia/models/base/model_exemple_complex_v1.json"
os.environ["V2_LEGACY_EXPERIMENT_CONFIG_PATH"] = "/content/b-ia/config_experiment.json"
os.environ["V2_LEGACY_BUILDER_PATH"] = "/content/b-ia/utils/model_builder.py"
```

## Cèl·lula 4: Go/No-Go previ

```python
!python ops/scripts/probe_api_prefix.py
!python ops/scripts/go_no_go_check.py
```

## Cèl·lula 5: Validació Fase 0 de models

```python
!python ops/scripts/run_phase0_model_validation.py
```

Config per defecte:

- `ops/configs/phase0_model_validation.json` (paths a `/content/b-ia`)

## Cèl·lula 6: Executar worker

```python
!python colab-worker/src/run_worker.py
```

La comanda executa correctament el worker tant en execució directa com en mode paquet.

## Cèl·lula 7: Verificacions post-run

```python
!python ops/scripts/check_legacy_model_compat.py
!python ops/scripts/watchdog_retry.py
```

## Cèl·lula 8: Prova multi-generació curta

```python
import os
os.environ["V2_TRIAL_MAX_GENERATIONS"] = "8"
os.environ["V2_TRIAL_HEARTBEAT_SECONDS"] = "5"
os.environ["V2_TRIAL_CODE_VERSION"] = "trial-multi-gen-8"
os.environ["V2_TRIAL_VERIFY_LEGACY"] = "false"
!python ops/scripts/run_multi_generation_trial.py
```

## Cèl·lula 9: Prova E2E de generació LLM (GPT real)

```python
import os
os.environ["V2_LLM_PROVIDER"] = "openai"
os.environ["V2_LLM_USE_LEGACY_INTERFACE"] = "true"
os.environ["V2_LLM_TRIAL_GENERATIONS"] = "4"
os.environ["OPENAI_API_KEY"] = "<nova_clau>"
if "<nova_clau>" in os.environ["OPENAI_API_KEY"]:
    raise RuntimeError("Configura OPENAI_API_KEY amb una clau real abans de la prova GPT.")
!cd /content/b-ia && git pull
!python ops/scripts/run_llm_generation_trial.py
```

## Notes

- El notebook és principalment codi d'orquestració.
- La lògica de negoci reutilitza els mòduls de `colab-worker/src`.
- Si l'API respon 404 a `/runs`, deixa `V2_API_PATH_PREFIX=""` o posa `/public/index.php`.
- Per usar LLM real, activa `V2_LLM_ENABLED=true` i configura `OPENAI_API_KEY` o `V2_LLM_API_KEY`.
