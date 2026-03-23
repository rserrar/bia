# Decisions and Outcomes

Aquest document recull que hem canviat, per que ho hem canviat i que esperem obtenir en operacio real.

## 1) Unificacio de paths de runtime (Colab real)

Que hem fet:

- Hem normalitzat rutes per funcionar sobre `/content/b-ia`.
- Hem afegit fallback automatic quan apareixen rutes legacy amb prefix `V2/`.

Per que:

- Les sessions de Colab no mantenien sempre el mateix layout esperat i apareixien errors `FileNotFoundError`.

Que esperem obtenir:

- Menys errors de configuracio manual.
- Menys regressions en proves curtes.

## 2) Persistencia real de metadades de training

Que hem fet:

- L'endpoint de status de proposals ara persisteix `metadata_updates` dins `llm_metadata`.

Per que:

- Els models quedaven `trained`, pero faltaven camps clau (`training_kpis`, `trained_model_uri`).

Que esperem obtenir:

- Traçabilitat completa proposal -> KPI -> artifact.
- Seleccio fiable dels millors models per retroalimentar l'LLM.

## 3) Flux automatic trainer + cua

Que hem fet:

- Endpoint `lock-for-training` operatiu.
- Auto-promocio `validated_phase0 -> accepted` al trainer quan cal.
- Supervisor de trainer amb auto-restart.

Per que:

- El trainer podia quedar-se en idle sense proposta `accepted`.

Que esperem obtenir:

- Pipeline autonom sense passos manuals constants.
- Millor recuperacio davant caigudes del procés.

## 4) Auto-feed de feina en estat idle

Que hem fet:

- Si la cua es buida, el supervisor genera feina (trial LLM) o fallback seed bootstrap.

Per que:

- En proves a Colab, si no hi ha propostes, el sistema sembla bloquejat encara que estigui sa.

Que esperem obtenir:

- Flux continu i visible per tests curts.
- Menys temps mort en sessions gratuïtes.

## 5) Observabilitat runtime

Que hem fet:

- Events per epoques (`model_training_epoch_start/end`) i events de cicle.
- Watcher CLI (`watch_runtime_status.py`) i health check P0.

Per que:

- A Colab no sempre es veu clar el progres real del sistema.

Que esperem obtenir:

- Diagnosi rapida sense esperar al final del run.
- Deteccio primerenca de cues encallades o errors de ruta API.

## 6) Bootstrap seed model en servidor buit

Que hem fet:

- Si no hi ha cap proposta, el worker crea una proposta seed des del model de prova.

Per que:

- Despres d'un reset total, el pipeline no tenia base inicial.

Que esperem obtenir:

- Arrencada automàtica desde zero sense preparacio manual prèvia.
