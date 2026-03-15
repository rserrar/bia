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

## Tasques Completades Recentment

- Prova E2E LLM executada amb èxit (mock i real).
- Monitor definit com a dashboard PHP al servidor (`monitor.php`).
- Panell al monitor configurat per veure events globals, mètriques per model i tracking de quotes consumides (V2_LLM_MAX_TOKENS_PER_RUN).
- Generació i validació Phase0 integrada.
- Sistema de Promoció KPI automàtica incrustada al dashboard.

## P3: Phase 4: Hardening & Maintenance
- [x] **Pipeline Entrenament complet (post-Phase0)**
    - Afegit un Worker Independent (`run_trainer.py` i `trainer.py`) que processa els models en estat 'accepted' cap a 'trained'.
    - Afegits logs i controls de callbacks de limitació de temps/èpoques dins els Colab enviant status pel terminal.
    - Actualitzada l'API PHP per incorporar l'estat `training` i el mètode de lock.
- [ ] **Integration Testing**
    - [ ] Escriure proves per verificar canvis d'estat de worker a local monitor (comprovar robustesa connexió API).
    - [ ] Afegir timeouts resilients i retries al client HTTP.
- [ ] **Buidatge Codi V1**
    - [ ] Localitzar referències inútils i netejar el directori d'antics runscripts.
- [ ] **Documentació Final**
    - [ ] Crear manual final per V2.
    - [ ] Confirmar compatibilitats amb l'entorn de notebook final al drive.

## Decisions obertes

- Com articular l'entrenament d'Epochs complets post-Phase0 al Colab? (S'ha de fer dins el bucle d'evolució o en un job apart?)

## Criteris de pas de fase

- Pas a Fase `stability`: `smoke` amb `ok=true` i cap error de compilació
- Pas a entrenament més llarg: `stability` amb mètriques guardades i run recuperable
- Pas a LLM en producció: candidats validats i auditable end-to-end
