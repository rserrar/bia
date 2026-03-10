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
V2_API_TOKEN = "<token>"
if "<api-real>" in V2_API_BASE_URL or "<token>" in V2_API_TOKEN:
    raise RuntimeError("Configura V2_API_BASE_URL i V2_API_TOKEN")
os.environ["V2_API_BASE_URL"] = V2_API_BASE_URL
os.environ["V2_API_TOKEN"] = V2_API_TOKEN
os.environ["V2_CODE_VERSION"] = "real-colab-v2"
os.environ["V2_CHECKPOINT_PATH"] = "/content/drive/MyDrive/bia_v2/run_state.json"
os.environ["V2_HEARTBEAT_INTERVAL_SECONDS"] = "30"
os.environ["V2_MAX_GENERATIONS"] = "3"
os.environ["V2_VERIFY_LEGACY_MODEL_BUILD"] = "true"
os.environ["V2_LEGACY_BUILD_CHECK_STRICT"] = "false"
os.environ["V2_LEGACY_MODEL_JSON_PATH"] = "/content/b-ia/models/base/model_exemple_complex_v1.json"
os.environ["V2_LEGACY_EXPERIMENT_CONFIG_PATH"] = "/content/b-ia/config_experiment.json"
os.environ["V2_LEGACY_BUILDER_PATH"] = "/content/b-ia/utils/model_builder.py"
```

## Cèl·lula 4: Go/No-Go previ

```python
!python ops/scripts/go_no_go_check.py
```

## Cèl·lula 5: Executar worker

```python
!python colab-worker/src/run_worker.py
```

## Cèl·lula 5b: Validació Fase 0 de models

```python
!python ops/scripts/run_phase0_model_validation.py
```

Config per defecte:

- `ops/configs/phase0_model_validation.json`

## Cèl·lula 6: Executar worker

```python
!python colab-worker/src/run_worker.py
```

## Cèl·lula 7: Verificacions post-run

```python
!python ops/scripts/check_legacy_model_compat.py
!python ops/scripts/watchdog_retry.py
```

## Notes

- El notebook és principalment codi d'orquestració.
- La lògica de negoci reutilitza els mòduls de `colab-worker/src`.
