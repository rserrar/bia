# Pla d'implementació en entorn real

## Resposta curta

No cal escriure molt codi nou per al notebook de Colab. Podem reutilitzar la major part del codi existent.

Estimació de reutilització:

- Colab worker: 80-90%
- API PHP: 95%
- Monitor local: 85-90%

## Què reutilitzem directament

- Bucle principal del worker (`colab-worker/src/engine.py`)
- Client API (`colab-worker/src/api_client.py`)
- Checkpoints (`colab-worker/src/checkpoint_store.py`)
- Compatibilitat legacy (`colab-worker/src/legacy_model_compat.py`)
- Contracte API (`shared/schemas/api_contract.json`)
- Scripts de smoke/watchdog (`ops/scripts/*.py`)

## Què falta implementar per al notebook

- Cèl·lules d'arrencada d'entorn (pip, paths, variables)
- Càrrega de configuració de run per entorn real
- Check Go/No-Go previ (`ops/scripts/go_no_go_check.py`)
- Validació Fase 0 de models (`ops/scripts/run_phase0_model_validation.py`)
- Fitxer de control de mida de dades i temps (`ops/configs/phase0_model_validation.json`)
- Invocació de `run_worker.py` amb variables d'entorn correctes
- Cèl·lules de validació final (summary de run, legacy check opcional)

## Fases d'execució

1. Validació local API + smoke test
2. Arrencada Colab amb Drive i dependències
3. Validació Fase 0 amb dataset reduït i entrenament curt
4. Execució worker real amb heartbeat
5. Validació de resultats des de frontend local
6. Tancament i checklist de robustesa

## Riscos i mitigació

- TensorFlow no disponible en local: executar build legacy a Colab
- API sense persistència avançada: mantenir còpia d'estat i snapshots
- Tall de sessió Colab: checkpoint cada pas i recuperació de run existent
