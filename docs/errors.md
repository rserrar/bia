# Known Errors

Errors reals ja trobats i resolts.

## 1) `LLM model_definition has empty used_inputs`

Cause habitual:

- variables d'entorn residuals,
- path de config/prompt incorrecte,
- resposta LLM parcial sense estructura completa.

Accio:

- forcar paths actuals (`configs/...`, `prompts/...`, `models/...`),
- `V2_LLM_USE_LEGACY_INTERFACE=false`,
- mantenir `V2_LLM_REPAIR_ON_VALIDATION_ERROR=true`.

## 2) API 404 en `model-proposals` o `runs`

Cause habitual:

- prefix desplegat no coincident (`/public/index.php`).

Accio:

- executar `ops/scripts/probe_api_prefix.py`,
- usar `V2_API_PATH_PREFIX` resolt.

## 3) `trained_model_uri=None` i `training_kpis` buit

Cause habitual:

- backend no persistia `metadata_updates` al `POST /model-proposals/{id}/status`.

Accio:

- verificar desplegament actual de `index.php` i `ApiService.php`,
- fer prova `probe_meta` de persistencia.

## 4) Trainer en idle permanent (`Mantenint cerca...`)

Cause habitual:

- no hi ha propostes `accepted` o `validated_phase0`.

Accio:

- activar supervisor amb auto-feed,
- o generar trial manual.

## 5) Paths legacy `/content/b-ia/V2/...` en Colab

Cause habitual:

- layout actual real es `/content/b-ia`.

Accio:

- usar rutes relatives modernes (`configs/...`, `data/min`, etc.),
- mantenir normalitzacio de paths al codi.
