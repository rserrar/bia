# Arquitectura V2

## Visió general

La V2 adopta una arquitectura distribuïda en 3 capes:

1. Colab Worker (execució)
2. Server API (control plane)
3. Frontend Local (lectura i visualització)

Objectiu: desacoblar càlcul, coordinació i presentació per evitar bloquejos globals.

## Diagrama lògic

```text
[Google Drive] <----> [Colab Worker] <----HTTPS----> [Server API] <----HTTPS----> [Frontend Local]
      ^                      |                               |
      |                      |                               |
      +--------- artefactes i checkpoints -------------------+
```

## Flux principal

1. El worker inicia un `run` via API.
2. El worker executa generació/validació/avaluació en cicles.
3. El worker envia heartbeat, events i mètriques a l'API.
4. El worker desa artefactes a Drive.
5. Si Drive falla, el worker activa fallback a pujada al servidor.
6. El frontend local consulta l'API periòdicament i mostra estat.

## Contractes clau

- `run_state`: estat resumible del cicle d'evolució
- `event`: registre temporal d'accions i incidències
- `metrics`: rendiment de models i generacions
- `artifact`: metadades de fitxers (models, logs, plots, checkpoints)

## Requisits no funcionals

- Robustesa: recuperació automàtica després de caigudes
- Seguretat: autenticació per token, rotació de credencials, TLS
- Mantenibilitat: mòduls separats, configuració explícita, versió de codi
- Observabilitat: logs estructurats i estat traçable

## Decisió de codi font

Estratègia recomanada:

- Codi versionat com a font principal
- Càrrega des de Drive com a mecanisme de distribució/fallback
- No executar codi sense versió i hash de referència

