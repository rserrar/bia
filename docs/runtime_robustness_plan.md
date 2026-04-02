# Runtime Robustness Plan

Aquest document defineix el redisseny objectiu del runtime V2 per prioritzar robustesa, recuperacio i operabilitat en execucions llargues a Colab o en workers separats.

## Context

L'arquitectura actual ja te peces utiles:

- API com a font de veritat operativa.
- proposals amb estats persistents.
- trainer separat del flux principal.
- monitor, autopsia, events i heartbeats.

Pero encara arrossega una semantica de `generacio` massa forta per a un sistema que en realitat ha de funcionar com una cua continua.

Problemes observats:

- una proposta rebutjada pot deixar el sistema sense relleu i bloquejar el progrés,
- la generacio de models i l'entrenament encara comparteixen massa responsabilitats dins el mateix loop,
- no es diferencia prou be entre un component lent i un component realment encallat,
- els timeouts de watchdog poden donar falsos positius si un entrenament dura 5-15 minuts,
- hi ha logica de repair parcial i dispersa entre phase0, training i control del loop.

## Principis de disseny

- La robustesa passa per davant de la simplicitat aparent.
- El runtime ha de continuar produint treball encara que alguns models fallin.
- `generation` es mante com a etiqueta de telemetria, no com a barrera de control.
- Cap rol ha de concentrar decisions, feina pesada i vigilancia alhora.
- Els heartbeats han de mesurar vida del component; el progrés ha de mesurar activitat util.
- L'API es mante com a source of truth per estat, assignacions, progress i recuperacio.

## Arquitectura objectiu

El runtime es divideix en quatre processos o agents logics independents.

### 1. Run Controller

Responsabilitats:

- crear o recuperar la `run`,
- mantenir `target_models_total`,
- mantenir `active_buffer_target`,
- decidir quan cal generar relleu,
- decidir quan la run pot finalitzar,
- publicar resum de progres agregat,
- no entrenar ni fer validacio pesada.

No ha de fer:

- compilacio o entrenament de models,
- crides LLM llargues com a feina principal,
- deteccio final de processos encallats.

### 2. Generator Worker

Responsabilitats:

- crear noves propostes via LLM,
- enviar-les a `queued_phase0`,
- processar `phase0`,
- fer repair o replacement de rebuigs estructurals,
- generar substituts quan una proposta queda exhausta,
- mantenir el buffer de treball preparat per al trainer.

No ha de fer:

- entrenament,
- finalitzacio global de la run,
- reinici d'altres processos.

### 3. Trainer Worker

Responsabilitats:

- bloquejar propostes `accepted`,
- entrenar exactament una proposta alhora per worker,
- publicar heartbeats i events de progrés durant training,
- tancar la proposta en `trained` o `rejected`,
- persistir checkpoints i metadades de resum.

No ha de fer:

- decidir quants models s'han de generar,
- interpretar la semantica de `generation`,
- vigilar la salut global del sistema.

### 4. Watchdog

Responsabilitats:

- observar heartbeats per rol,
- detectar diferencia entre lentitud, stall i mort del procés,
- reiniciar el rol minim necessari,
- marcar incidents operatius a events,
- mai assumir que un entrenament llarg equival a deadlock.

No ha de fer:

- gestionar la cua de models,
- prendre decisions de qualitat del model,
- escriure estat funcional del domini si no hi ha incident.

## Model operatiu continu

La logica deixa de ser "N generacions de M models" i passa a ser:

- objectiu: `target_models_total`,
- buffer viu: `active_buffer_target`,
- replenishment automatic quan el buffer cau,
- repair/replacement immediat quan un model falla,
- finalitzacio nomes quan s'ha assolit el target i la cua esta drenada.

### Definicions operatives

- `target_models_total`: nombre de models entrenats que volem obtenir a la run.
- `active_buffer_target`: nombre minim de models que volem tenir entre `draft`, `queued_phase0`, `validated_phase0`, `accepted` i `training`.
- `active_models_count`: recompte real dels estats actius.
- `terminal_models_count`: models en `trained` o `rejected` sense mes intents.
- `generation_label`: etiqueta incremental per observabilitat i context del prompt.

### Regla principal de planificacio

El controller calcula periodicament:

- `trained_count`,
- `active_models_count`,
- `remaining_needed = target_models_total - trained_count`,
- `buffer_gap = active_buffer_target - active_models_count`.

Si `remaining_needed > 0` i `buffer_gap > 0`, es demana al generator que crei mes treball.

La quantitat a crear per iteracio ha de ser petita i segura:

- recomanat: 1 proposta per iteracio,
- opcional: fins a 2 si el trainer esta ocupat i el buffer cau a 0,
- no omplir de cop la cua si el LLM esta inestable o lent.

## `generation` com a etiqueta, no com a barrera

Es mantindran els camps actuals de `generation` per compatibilitat amb monitor, scripts i prompting, pero amb semantica nova:

- `generation` no bloqueja l'inici del seguent model,
- `generation` no defineix lot tancat,
- `from_generation` serveix per saber en quin moment o tanda visual es va crear una proposta,
- els champions de referencia es trien per KPI actuals, no per generacio.

Regla funcional:

- qualsevol proposta nova ha d'utilitzar els millors champions actuals disponibles a la run o a l'abast configurat, sigui quina sigui la seva `generation`.

## Deteccio de salut: viu, lent, stalled, mort

Cal separar clarament quatre estats operatius.

### Viu

- el procés envia heartbeat dins del termini esperat.

### Lent

- no hi ha resultat nou encara,
- pero el procés segueix enviant heartbeat,
- especialment valid per training llarg.

### Stalled

- el procés continua viu o no esta clar si ha mort,
- pero no hi ha ni heartbeat de progrés ni actualitzacio de camp operatiu durant massa temps.

### Mort

- no hi ha heartbeat de procés,
- o el supervisor/launcher confirma que el subprocess ha acabat,
- o el lock d'una proposta ha quedat abandonat mes enlla del llindar.

## Estrategia de heartbeat i progress

Cada rol envia dos tipus de senyal:

- heartbeat de liveness: prova que el procés principal continua viu,
- progress heartbeat: prova que hi ha activitat util de domini.

### Valors inicials recomanats

- `worker_heartbeat_interval_seconds`: 10-15
- `trainer_progress_heartbeat_seconds`: 20-30
- `watchdog_warn_after_seconds`: 300
- `watchdog_stall_after_seconds`: 900
- `watchdog_dead_after_seconds`: 1800

Notes:

- un entrenament sense final d'epoca no es considera error si segueix enviant `model_training_heartbeat`,
- el watchdog no ha de mirar nomes l'ultim event global de la run,
- la deteccio ha de ser per rol i, en el cas del trainer, tambe per proposta lockejada.

## Maquina d'estats de propostes

Es mantenen els estats principals actuals, pero s'unifica millor la semantica.

Flux base:

- `draft`
- `queued_phase0`
- `validated_phase0`
- `accepted`
- `training`
- `trained` o `rejected`

Metadades addicionals necessaries:

- `repair_attempts_total`
- `repair_depth`
- `repair_origin`
- `repair_last_error`
- `replacement_for_proposal_id`
- `repair_exhausted`
- `training_locked_by`
- `training_lock_acquired_at`
- `last_progress_at`
- `last_worker_role`

Regles importants:

- els rebuigs de `phase0` i de training han de compartir model mental de repair,
- no s'ha de reintentar infinitament la mateixa proposta fallida,
- quan una proposta queda exhausta, s'ha de poder crear un substitut nou sense bloquejar la run,
- la run no depen d'un proposal concret; depen del target total.

## Repair i replacement unificats

La logica de repair actual s'ha de simplificar conceptualment.

### Tipus de resposta a una fallada

- `repair`: l'LLM intenta arreglar la proposta concreta.
- `replacement`: l'LLM genera un model nou inspirat en el context actual.
- `abandon`: es marca la proposta com a exhausta i el controller omple el buffer amb una nova proposta.

### Politica recomanada

- 1 intent de repair directe,
- 1-2 intents de replacement,
- si tots fallen, marcar `repair_exhausted=true` i reposar buffer,
- no superar `repair_depth` configurable.

### Regles de duplicat

- mantenir fingerprint exacte,
- afegir control de lineage per no regenerar repetidament el mateix error,
- si un replacement es detecta com a duplicat, compta com intent consumit.

## Scheduler del controller

El controller ha d'executar un loop lleuger i idempotent.

### Responsabilitats del loop

- llegir estat actual des de l'API,
- calcular counts globals de la run,
- demanar replenishment si cal,
- detectar si la run ha assolit condicio de finalitzacio,
- publicar `result_summary` actualitzat,
- no fer feina pesada dins del loop.

### Pseudologic

```text
while run active:
  refresh counts and worker health
  if trained >= target and active == 0:
    complete run
    break
  if generator healthy and active < buffer_target and trained < target:
    request generation of 1 proposal
  if rejected irrecoverable consumed active slot:
    request replacement through normal replenish path
  sleep short interval
```

## Contractes API nous o ajustats

No cal trencar l'API actual d'entrada, pero si ampliar-la.

### `run` summary

Afegir o consolidar:

- `target_models_total`
- `trained_count`
- `rejected_count`
- `active_models_count`
- `active_buffer_target`
- `queue_health`
- `generator_health`
- `trainer_health`
- `controller_health`
- `watchdog_health`
- `latest_progress_at`

### Worker heartbeats

Nou recurs o estructura equivalent:

- `worker_id`
- `role`
- `run_id`
- `heartbeat_at`
- `progress_at`
- `health`
- `payload_summary`

### Proposal metadata

Cal unificar claus de repair per no barrejar `phase0_repair_*` amb `training repair_*` quan signifiquen el mateix tipus de lineage.

## Monitor i observabilitat

El monitor ha de canviar el focus de "generacions completades" a "salut de la cua i del runtime".

### Widgets recomanats

- `trained / target`
- `active buffer / buffer target`
- `accepted waiting`
- `training now`
- `rejected recoverable`
- `rejected exhausted`
- salut per rol: generator, trainer, controller, watchdog
- ultims incidents operatius

### Alertes recomanades

- `buffer_empty_while_target_pending`
- `trainer_alive_but_no_progress_warning`
- `generator_rate_limited`
- `proposal_repair_exhausted`
- `worker_restart_detected`
- `abandoned_training_lock_recovered`

## Compatibilitat i migracio

El canvi s'ha de fer per fases, mantenint compatibilitat temporal.

### Fase A - Estabilitzacio immediata

- arreglar incoherencies actuals del loop fluid,
- corregir signatures trencades,
- unificar metadades de repair,
- eliminar logica duplicada o contradictoria,
- evitar reintents infinits.

### Fase B - Runtime continu

- introduir `target_models_total` i `active_buffer_target`,
- mantenir `generations` i `models_per_generation` com a entrada legacy,
- derivar internament el target des de camps legacy mentre el monitor es migra.

### Fase C - Salut per rols

- afegir heartbeats per rol,
- afegir watchdog extern,
- desacoblar deteccio de stall de la logica funcional.

### Fase D - Neteja de contracte

- reduir la dependencia funcional de `generation`,
- ajustar scripts de prova,
- actualitzar docs i monitor com a model continu per defecte.

## Ordre d'implementacio recomanat

1. Arreglar bugs i incoherencies actuals del worker.
2. Unificar repair metadata i lineage.
3. Introduir scheduler de buffer continu.
4. Afegir heartbeat per rol i watchdog extern.
5. Migrar monitor i summaries.
6. Actualitzar scripts de smoke i e2e.
7. Tancar documentacio i runbook de recuperacio.

## Criteris d'acceptacio

- la run no queda encallada si una proposta falla i no es pot reparar,
- mentre `trained_count < target_models_total`, el sistema intenta mantenir buffer viu,
- el trainer pot estar 15 minuts entrenant sense ser marcat falsament com a mort,
- si cau un subprocess, nomes es recupera aquell rol,
- `run_completed` nomes arriba quan el target esta assolit i no queden propostes actives,
- el monitor permet distingir clarament lentitud, stall i error real.

## Decisions obertes

- si els quatre rols viuran dins un sol notebook com subprocessos locals o si s'han de permetre workers distribuits,
- si `worker_heartbeats` es guarda com a recurs API separat o com a metadata agregada per run,
- si es vol limit de concurrencia de trainers a 1 per defecte o configurable,
- si la recuperacio d'un training lock abandonat l'ha de fer el watchdog o l'API en reclamar feina.

## Propera execucio recomanada

Per minimitzar risc, la primera iteracio d'implementacio hauria d'abordar nomes:

- estabilitzacio del codi actual,
- metadata de repair coherent,
- scheduler de buffer,
- progress summary amb `target`, `active`, `trained`, `rejected`.

Els subprocessos addicionals i el watchdog extern poden entrar a la segona iteracio, un cop el model continu ja funcioni sense deadlocks.
