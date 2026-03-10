# Ops

Conté scripts operatius, verificacions de salut i eines de desplegament.

Document de desplegament real:

- `REAL_ENV_ROLLOUT.md`
- `PLAN_TRACKER.md`

## Scripts disponibles

- `scripts/run_php_api_local.ps1`: inicia l'API PHP local a `127.0.0.1:8080`
- `scripts/smoke_test_api.py`: prova end-to-end dels endpoints principals
- `scripts/watchdog_retry.py`: marca runs stale com `retrying` via watchdog
- `scripts/check_legacy_model_compat.py`: comprova construcció de model com la versió antiga
- `scripts/go_no_go_check.py`: checklist previ abans d'executar run real
- `scripts/run_phase0_model_validation.py`: prova compilació/execució curta per varietat de models
