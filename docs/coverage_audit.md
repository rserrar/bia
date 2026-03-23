# Coverage Audit

Objectiu: comprovar cobertura 1:1 entre docs originals i hub centralitzat abans/el mateix moment de retirar duplicats.

## Resultat actual

- Cobertura global del coneixement funcional: **alta**.
- Duplicats retirats: **si** (docs root migrats al hub).
- Tracking viu mantingut fora del hub: **si** (`ops/PLAN_TRACKER.md`, `ops/IMPLEMENTATION_TODO.md`).

## Mapping de migracio principal

`ARCHITECTURE.md` -> `docs/architecture.md`

- Estat: cobert i consolidat.

`COMPONENTS.md` -> `docs/components.md`

- Estat: cobert i consolidat.

`ROADMAP.md` -> `docs/roadmap.md`

- Estat: cobert i actualitzat a context real de proves curtes.

`STRUCTURE.md` -> `docs/structure.md`

- Estat: cobert i simplificat per operacio actual.

## Docs que continuen fora del hub (intencional)

- `ops/PLAN_TRACKER.md`: seguiment viu de fase/backlog.
- `ops/IMPLEMENTATION_TODO.md`: backlog viu amb checkbox.
- `ops/REAL_ENV_ROLLOUT.md`: context historic de desplegament.
- `ops/REPO_SETUP.md`: guia practica de repo.

## Pending for full single-folder policy

Per tenir absolutament tota la documentacio sota `docs/`, caldria migrar tambe els fitxers de tracking viu d'`ops/` i deixar alias curts.

Avui no s'ha fet per evitar trencar el flux operatiu durant proves.
