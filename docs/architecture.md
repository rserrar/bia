# Architecture

La V2 separa calcul, coordinacio i observabilitat en tres capes:

1. Worker (Colab) per generar i entrenar models.
2. Server API (PHP) per estat, cues, events, metrics i artifacts.
3. Capa d'operacio (monitor web + scripts ops) per visibilitat i control.

## Logical data flow

- El worker crea/recupera `run`.
- Cada generacio publica events i metrics.
- Les propostes entren a `model_proposals` i passen per phase0.
- El trainer bloqueja propostes i actualitza estats (`training`, `trained`, etc.).
- Els models entrenats es registren com artifact `trained_model`.

## Why this architecture

- Evitar bloquejos globals: si falla una part, la resta pot continuar.
- Traçabilitat: cada transicio queda registrada via events/metadata.
- Recuperacio: checkpoints + estat persistent a servidor.

## Non-functional requirements

- Robustesa: recuperacio automatica despres de tall de sessio.
- Seguretat: token, HTTPS, separacio de permisos operatius.
- Mantenibilitat: configuracio explicita i components desacoblats.
- Observabilitat: events, metrics, artifacts i status consultables.

## Stability constraints discovered in practice

- Prefix API variable segons desplegament (``, `/public/index.php`, `/public`).
- Sessions Colab curtes: millor cicles de prova de pocs minuts.
- Entorn CPU a Colab: warnings CUDA no impliquen error funcional.

## Contracts that must not regress

- `POST /model-proposals/{id}/status` ha de persistir `metadata_updates`.
- `POST /model-proposals/lock-for-training` ha d'existir per assignar feina al trainer.
- `GET /runs/{run_id}/summary` ha de retornar event/artifact final per seguiment.

## Source-of-truth policy

- Codi versionat al repositori com a font principal.
- Drive i estat API com a persistencia operativa/fallback.
- Evitar execucio de codi sense versio identificable.
