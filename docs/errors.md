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

## 6) Request queda a `starting_trial` pero el run real ja esta treballant

Cause habitual:

- `result_summary` de `execution_request` va endarrerit respecte al run real,
- o hi havia una request antiga pendent i el worker n'ha reclamat una altra.

Accio:

- mirar primer el log directe de Colab,
- comprovar `GET /runs` i `GET /events`,
- si cal, netejar el servidor abans de llançar una prova nova.

## 7) `429 Too Many Requests` d'OpenAI

Cause habitual:

- massa pressio de prompt o massa execucions seguides.

Accio:

- esperar una estona abans de reiniciar el worker,
- mantenir `V2_LLM_MIN_INTERVAL_SECONDS` raonable,
- configurar fallback nadiu a Gemini,
- amb la politica actual, el worker s'atura quan detecta `rate limit` persistent.

## 8) `Legacy LLM interface returned empty response`

Cause habitual:

- Colab ha arrencat amb `V2_LLM_USE_LEGACY_INTERFACE=true`.

Accio:

- fixar al notebook:
  - `V2_LLM_USE_LEGACY_INTERFACE=false`
  - `V2_LLM_REPAIR_ON_VALIDATION_ERROR=true`

## 9) `inputs not connected to outputs`

Cause habitual:

- arquitectura generada amb graf Keras desconnectat.

Accio:

- deixar que el circuit de `repair/replacement` reintenti el model,
- revisar `model_repair_started`, `model_repair_enqueued` i `model_repair_exhausted` als events.

## 10) `loss_weights must match the number of losses`

Cause habitual:

- `training_config.compile` desalineat amb `output_heads`.

Accio:

- el sistema ja normalitza `loss`, `loss_weights` i `metrics` abans del training,
- si encara passa, el model s'ha d'enviar a repair/replacement automàtic.

## 11) Generacions completes pero models encara a `validated_phase0`

Cause habitual antiga:

- el run es marcava `completed` massa aviat, abans de buidar la cua de training.

Accio actual:

- el worker espera `training_drain_wait_completed` abans de fer `run_completed`.
- si es torna a veure, mirar els events `generation_drain_wait_*` i `training_drain_wait_*`.
