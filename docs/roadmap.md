# Roadmap

Aquest roadmap consolida la visio original i l'estat real actual.

## Fase 0 - Base de projecte

Objectiu:

- estructura V2,
- contractes API,
- convencions de configuracio.

Estat: completada.

## Fase 1 - MVP funcional

Objectiu:

- cicle executat a Colab amb control via API.

Entregables base:

- worker amb checkpoint,
- API amb runs/heartbeat/events/metrics,
- summary de run.

Estat: completada.

## Fase 2 - Robustesa

Objectiu:

- evitar perdua de progres i fallades silencioses.

Entregables base:

- retries/fallbacks,
- processament automatic phase0,
- normalitzacio de paths i prefix API.

Estat: completada en nivell de proves curtes.

## Fase 3 - Monitoratge operatiu

Objectiu:

- visibilitat clara de runtime i estat de propostes.

Entregables:

- monitor web funcional,
- scripts de watcher/health check,
- events de training per epoques.

Estat: completada en mode operatiu de prova.

## Fase 4 - Hardening i manteniment

Objectiu:

- passar de "funciona" a "operable de forma consistent".

Focus actual:

- supervisor amb auto-restart i auto-feed,
- persistencia completa de metadades training,
- documentacio centralitzada i auditada.

Estat: en curs.

Línies de treball actuals dins aquesta fase:

- fer el prompt V2 tan robust com la V1, però amb millor observabilitat
- evitar models duplicats o massa semblants
- reforçar `phase0` i repair/replacement automàtic
- assegurar que les execucions no es tanquen fins que la cua de training està drenada
- millorar la documentació de proves i interpretació d'execucions

## Proper resultat esperat

1. Seleccio dels millors models per KPI en una vista unica.
2. Traçabilitat explicita de quins models de referencia entren al prompt LLM.
3. Tancament de migracio documental i retirada de duplicats restants.
4. Visibilitat millor del provider LLM usat (`openai` o `gemini`) a monitor/autòpsia.
5. Validació estable de proves llargues sobre dataset gran des de Colab.
