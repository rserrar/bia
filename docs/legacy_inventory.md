# Legacy Inventory

Aquest document recull compatibilitats i restes legacy que encara existeixen, pero no formen part del flux canonic ideal.

## Legacy paths and flags still alive

- `V2_LLM_USE_LEGACY_INTERFACE`
- `V2_VERIFY_LEGACY_MODEL_BUILD`
- `V2_LEGACY_BUILD_CHECK_STRICT`
- `V2_LEGACY_MODEL_JSON_PATH`
- `V2_LEGACY_EXPERIMENT_CONFIG_PATH`
- `V2_LEGACY_BUILDER_PATH`

## Legacy helpers still referenced

- `colab-worker/src/legacy_model_compat.py`
- `ops/scripts/check_legacy_model_compat.py`
- `ops/scripts/run_generated_proposals_compile_check.py`

## Legacy fallback imports still present

- `trainer.py` encara intenta `utils.*` com a fallback despres de `shared.utils.*`
- `llm_client.py` manté mode `legacy_interface`
- `engine.py` encara pot verificar compatibilitat de model legacy

## Why these still exist

- han ajudat a fer transicio segura des del layout/contracte V1,
- han estat utils per detectar regressions de notebook i models base,
- encara hi ha fitxers/scripts de validacio que depenen d'aquesta compatibilitat.

## Not part of canonical happy path

El happy path actual es:

- `use_legacy_interface=false`
- `shared.utils.*` com a font principal
- rutes modernes (`configs/...`, `prompts/...`, `models/...`, `data/min`)

## Removal policy

No eliminar fins que:

- el runbook final no depengui de cap flag legacy,
- compile-check i checks de compatibilitat tinguin substitut modern,
- i no hi hagi notebooks/entorns productius que encara els facin servir.
