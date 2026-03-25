# Ops

Conté scripts operatius, verificacions de salut i eines de desplegament.

Document de desplegament real:

- `REAL_ENV_ROLLOUT.md`
- `PLAN_TRACKER.md`
- `IMPLEMENTATION_TODO.md`

## Scripts disponibles

- `scripts/run_php_api_local.ps1`: inicia l'API PHP local a `127.0.0.1:8080`
- `scripts/smoke_test_api.py`: prova end-to-end dels endpoints principals
- `scripts/watchdog_retry.py`: marca runs stale com `retrying` via watchdog
- `scripts/check_legacy_model_compat.py`: comprova construcció de model com la versió antiga
- `scripts/go_no_go_check.py`: checklist previ abans d'executar run real
- `scripts/run_phase0_model_validation.py`: prova compilació/execució curta per varietat de models
- `scripts/run_llm_generation_trial.py`: trial E2E de generació LLM sobre l'API real
- `scripts/probe_openai_models.py`: comprova models disponibles i headers de rate-limit
- `scripts/run_llm_full_prompt_check.py`: valida prompt complet (mode sec o amb enviament LLM/API)
- `scripts/run_generated_proposals_compile_check.py`: compila propostes d'un `run_id` i reporta errors de schema
- `scripts/preview_selection_policy.py`: calcula ranking deterministic de models segons Selection Policy v1
- `scripts/run_integration_matrix.py`: executa matriu d'integracio multi-run i genera report JSON+MD
- `scripts/cleanup_inconsistent_state.py`: detecta i neteja estats inconsistents (`dry-run` / `apply`)
- `scripts/test_api_retry_policy.py`: simula errors transitoris locals (503, 429, 200) per validar retries del client API
- `scripts/verify_artifact_persistence.py`: valida artifacts descarregables d'un model/proposta i en guarda una copia local
- `scripts/p0_health_check.py`: comprovació P0 (API reachable, cues pendents encallades, resum PASS/FAIL)
- `scripts/run_trainer_supervisor.py`: manté `run_trainer.py` actiu amb auto-restart i health check cada 5 minuts
- `scripts/run_e2e_final_smoke.py`: prova E2E final automàtica (trial LLM + trainer + validació trained/artifacts/metadata)
- `scripts/watch_runtime_status.py`: visor de runtime en temps real per Colab (run/proposals/events/artifacts)

Variables útils del supervisor:

- `V2_SUPERVISOR_AUTO_FEED=true|false`: si no hi ha feina pendent, genera feina automàticament
- `V2_SUPERVISOR_AUTO_FEED_MIN_INTERVAL_SECONDS=180`: interval mínim entre auto-feeds
- `V2_SUPERVISOR_FEED_GENERATIONS=1`: generacions per trial quan auto-feed usa LLM

Variables utiles de selection/champion:

- `V2_SELECTION_POLICY_PROFILE=default|small_test|real_large`
- `V2_CHAMPION_SCOPE=run|global`
- `V2_CHAMPION_MIN_SCORE=...` (override opcional)
- `V2_CHAMPION_MARGIN_MIN=...` (override opcional)

Variables utiles de integration matrix:

- `V2_MATRIX_MODE=plan|run`
- `V2_MATRIX_RUNS=5`
- `V2_MATRIX_PROFILES=small_test`
- `V2_MATRIX_GENERATIONS=1`
- `V2_MATRIX_STALE_MINUTES=20`
- La matrix fixa per defecte `V2_LLM_MAX_TOKENS=6000` i `V2_LLM_NUM_REFERENCE_MODELS=2` per reduir truncaments a proves.

Variables utiles de HTTP hardening:

- `V2_API_CONNECT_TIMEOUT_SECONDS`
- `V2_API_READ_TIMEOUT_SECONDS`
- `V2_API_MAX_RETRIES`
- `V2_API_CIRCUIT_BREAKER_THRESHOLD`
- `V2_API_CIRCUIT_BREAKER_COOLDOWN_SECONDS`

Variables utiles de checkpoints / resume:

- `V2_CHECKPOINT_EVERY_EPOCHS`
- `V2_MAX_RESUME_ATTEMPTS`
- `V2_MODEL_CHECKPOINTS_DIR`

Variables utiles de cleanup:

- `V2_CLEANUP_MODE=dry-run|apply`
- `V2_CLEANUP_STALE_RUN_MINUTES=10`
- `V2_CLEANUP_STALE_RETRY_MINUTES=20`
- `V2_CLEANUP_STALE_TRAINING_MINUTES=20`
- `V2_CLEANUP_STALE_PHASE0_MINUTES=10`
- `V2_CLEANUP_STALE_ACCEPTED_MINUTES=20`

## Flux curt recomanat (fase de proves)

1. Prova E2E automàtica (1 generació + entrenament + validació final):

```bash
cd V2
python ops/scripts/run_e2e_final_smoke.py
```

2. Operació contínua (trainer persistent + auto-feed):

```bash
cd V2
python ops/scripts/run_trainer_supervisor.py
```

3. Observabilitat en temps real per CLI:

```bash
cd V2
python ops/scripts/watch_runtime_status.py
```
