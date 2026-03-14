# Seguiment del pla pactat

Backlog detallat actual: `ops/IMPLEMENTATION_TODO.md`

## Estat general

- Fase 0 Base de projecte: completada
- Fase 1 MVP funcional: gairebé completada
- Fase 2 Robustesa: en curs
- Fase 3 Frontend local: en curs
- Fase 4 Enduriment i manteniment: pendent

## Backlog immediat

1. Activar backend `sqlite` al servidor i validar persistència
2. Validar monitor web bàsic en servidor (`public/monitor.php`)
3. Decidir monitor local o dashboard PHP com a opció principal
4. Connectar pipeline de generació amb servei LLM real
5. Afegir test d'integració run complet

## Checkpoint operatiu

- API local validada amb smoke test
- Watchdog operatiu per runs stale
- Worker amb recuperació de run i checkpoint
- Contracte API compartit actualitzat
- Notebook executable preparat per entorn real
- Checklist Go/No-Go implementat
- Config Fase 0 i runner de validació implementats
- Fase 0 `smoke` validada amb resultat `ok=true`
- Fase 0 `stability` validada (`train_seconds=26.992`)
- Cicle complet worker -> API -> summary validat (`run_2101e6896a01`)
- Persistència SQLite opcional implementada al servidor PHP
- Monitor web bàsic implementat (`server-api/php/public/monitor.php`)
- Contracte de propostes LLM implementat (`/model-proposals`)
- Monitor ampliat amb gestió de `model_proposals` i canvi d'estat
- Acció ràpida `Enviar a phase0` implementada al monitor (`queued_phase0`)
- Processament automàtic de `queued_phase0` implementat (maintenance + worker)
- Worker amb autodetecció de prefix API (``, `/public/index.php`, `/public`)
- Scripts operatius amb autodetecció de prefix i sonda (`probe_api_prefix.py`)
- Validació real correcta a producció (`run_1678ab3c965d`, `prop_b49d7f78a20a`)
- Monitor amb botó de reset de dades de prova implementat
- Script de prova multi-generació curta preparat (`run_multi_generation_trial.py`)
- Comunicació LLM del worker connectada a `utils/llm_interface.py` (reutilització)
- Generador de prompt V2 connectat a plantilla antiga (`prompts/generate_new_models.txt`)
- Script E2E de prova LLM disponible (`run_llm_generation_trial.py`)
