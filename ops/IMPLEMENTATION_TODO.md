# TODO d'implementació V2

## Estat confirmat

- API reachable amb token
- Go/No-Go previ completat
- Validació Fase 0 `smoke` completada
- Compatibilitat de model legacy validada
- Cicle complet worker -> API -> summary completat (`run_2101e6896a01`)
- Persistència SQLite opcional implementada al servidor PHP
- Validació Fase 0 `stability` completada (`train_seconds=26.992`)
- Monitor web bàsic implementat (`server-api/php/public/monitor.php`)
- Contracte i endpoints base de propostes LLM implementats (`/model-proposals`)
- Monitor amb vista i accions d'estat per `model_proposals`
- Estat intermedi `queued_phase0` i acció de cua disponibles
- Processament automàtic de cua phase0 disponible al worker i API
- Resolució automàtica de ruta API implementada al client del worker
- `watchdog_retry` i sonda de ruta API preparats per entorns amb prefix
- Validació real de producció completada (`run_1678ab3c965d` i proposal `validated_phase0`)
- Monitor amb reset de dades de prova disponible
- Script de prova multi-generació curta afegit
- Capa LLM al worker integrada amb `utils/llm_interface.py` existent (mode reutilització)
- Prompt generator V2 basat en plantilla antiga integrat al worker
- Script de prova E2E LLM mock afegit

## Prioritat P0 (ara)

1. Executar prova E2E LLM mock (4+ generacions) i validar proposals per generació

## Prioritat P1 (següent bloc)

1. Definir monitor d'estat operatiu
2. Decidir ubicació del monitor: app local o dashboard PHP al servidor
3. Afegir panell de runs, errors i mètriques principals
4. Afegir traça de versions de codi i configuració per run

## Prioritat P2 (evolució de models)

1. Validar generació automàtica de proposals per generació amb LLM mock
2. Activar LLM real i validar candidats amb Fase 0 abans d'entrenament llarg
3. Guardar historial complet de prompts, candidates i resultats
4. Definir control de costos i límits de crides per run

## Decisions obertes

- Monitor local vs monitor web en PHP
- Estratègia final de persistència (SQLite únic o híbrid amb export JSON)
- Mecanisme de control de costos i límits per l'ús de LLM

## Criteris de pas de fase

- Pas a Fase `stability`: `smoke` amb `ok=true` i cap error de compilació
- Pas a entrenament més llarg: `stability` amb mètriques guardades i run recuperable
- Pas a LLM en producció: candidats validats i auditable end-to-end
