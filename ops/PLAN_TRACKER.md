# Seguiment del pla pactat

## Estat general

- Fase 0 Base de projecte: completada
- Fase 1 MVP funcional: gairebé completada
- Fase 2 Robustesa: en curs
- Fase 3 Frontend local: en curs
- Fase 4 Enduriment i manteniment: pendent

## Backlog immediat

1. Executar Go/No-Go (`ops/scripts/go_no_go_check.py`) en Colab
2. Executar validació Fase 0 (`ops/scripts/run_phase0_model_validation.py`)
3. Activar verificació legacy en entorn amb TensorFlow
4. Definir persistència avançada server-side
5. Millorar monitor local amb vista resum/timeline
6. Afegir test d'integració run complet

## Checkpoint operatiu

- API local validada amb smoke test
- Watchdog operatiu per runs stale
- Worker amb recuperació de run i checkpoint
- Contracte API compartit actualitzat
- Notebook executable preparat per entorn real
- Checklist Go/No-Go implementat
- Config Fase 0 i runner de validació implementats
