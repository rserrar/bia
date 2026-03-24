# Runbook Operations

Aquest document defineix el cami canonic d'operacio de V2 per a una persona tecnica que no conegui els detalls interns del codi.

## 1. Quick start at Colab

Objectiu: aixecar un entorn curt de prova i validar que el loop funciona.

Passos minimals:

1. Clonar o actualitzar repo a `/content/b-ia`.
2. Configurar variables:
   - `V2_API_BASE_URL`
   - `V2_API_TOKEN`
   - `OPENAI_API_KEY`
3. Fixar perfil de proves:
   - `V2_SELECTION_POLICY_PROFILE=small_test`
4. Validar prefix API:
   - `python ops/scripts/probe_api_prefix.py`
5. Smoke curt:
   - `python ops/scripts/run_e2e_final_smoke.py`

Quan aquest smoke passa, el sistema esta llest per proves repetides.

## 2. Server start / restart

Objectiu: garantir que el backend realment executa la versio correcta.

Checklist:

1. `git pull`
2. reinici PHP/Apache o PHP-FPM
3. validar sintaxi minima:
   - `php -l server-api/php/public/index.php`
   - `php -l server-api/php/public/monitor.php`
   - `php -l server-api/php/src/ApiService.php`
4. comprovar prefix viu:
   - `probe_api_prefix.py` des de Colab

## 3. Continuous operation

Supervisor:

```bash
python ops/scripts/run_trainer_supervisor.py
```

Watcher:

```bash
python ops/scripts/watch_runtime_status.py
```

Mode habitual de proves:

- supervisor actiu
- watcher o `monitor.php` oberts
- run curt sota demanda o auto-feed

## 4. Integration matrix

Prova funcional repetida:

```bash
V2_MATRIX_MODE=run V2_MATRIX_RUNS=3 V2_MATRIX_PROFILES=small_test V2_MATRIX_GENERATIONS=1 V2_MATRIX_STALE_MINUTES=20 python ops/scripts/run_integration_matrix.py
```

Smoke puntual de perfil `default`:

```bash
V2_MATRIX_MODE=run V2_MATRIX_RUNS=1 V2_MATRIX_PROFILES=default V2_MATRIX_GENERATIONS=1 V2_MATRIX_STALE_MINUTES=20 python ops/scripts/run_integration_matrix.py
```

Reports generats:

- `ops/reports/integration_matrix_*.json`
- `ops/reports/integration_matrix_*.md`

## 5. Cleanup

Dry-run:

```bash
V2_CLEANUP_MODE=dry-run python ops/scripts/cleanup_inconsistent_state.py
```

Apply:

```bash
V2_CLEANUP_MODE=apply python ops/scripts/cleanup_inconsistent_state.py
```

Politica:

- reencua `training` stale
- reprocessa `queued_phase0` stale
- marca `retrying` massa antic com `failed`
- `accepted` i `validated_phase0` antics es deixen com a casos auditables

## 6. Pre-run checklist

Abans de provar:

- servidor actualitzat i reiniciat
- token/API key vigents
- `probe_api_prefix.py` resol 200
- `p0_health_check.py` sense errors
- `cleanup_inconsistent_state.py` sense residus inesperats
- perfil de policy correcte (`small_test` per proves)

## 7. Post-run checklist

Despres de provar:

- run `completed`
- almenys una proposta `trained`
- `trained_model` o `champion_model` artifact present
- `training_kpis` i `trained_model_uri` persistits
- event `champion_selected`, `champion_kept` o equivalent
- report matrix guardat a `ops/reports/`

## 8. Troubleshooting

### API 404

- causa habitual: prefix erroni
- accio: `probe_api_prefix.py`

### Proposal no entrenada

- mirar `monitor.php`, watcher i events
- executar cleanup dry-run

### `trained_model_uri` buit o KPI absent

- revisar desplegament backend real
- validar persistencia de `metadata_updates`

### `OpenAI response content is empty` o JSON truncat

- revisar `logs/llm_interactions/`
- repetir run curt
- si es recurrent, reduir context o ajustar budget de resposta

### Champion score diferent entre event i board

- causa habitual: perfil de policy diferent entre worker i monitor
- revisar `policy_profile` i avisos de mismatch

## 9. Canonical operation path

Per a un tecnic nou al sistema, el cami recomanat es:

1. `probe_api_prefix.py`
2. `p0_health_check.py`
3. `run_e2e_final_smoke.py`
4. `run_trainer_supervisor.py`
5. `watch_runtime_status.py` o `monitor.php`
6. `run_integration_matrix.py`
7. `cleanup_inconsistent_state.py`

Aquest es el happy path operatiu actual de V2.

## 10. API-first UI note

El monitor web actual ha de consumir dades de la read API en comptes de calcular ranking/summaries localment.

Endpoints UI canònics:

- `GET /runs`
- `GET /runs/{id}`
- `GET /runs/{id}/summary`
- `GET /runs/{id}/references`
- `GET /proposals`
- `GET /champion/run/{id}`
- `GET /champion/global`
- `GET /models/shortlist`
