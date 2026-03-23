# Coverage Audit

Objectiu: verificar que la documentacio centralitzada cobreix el coneixement dels fitxers originals abans de retirar docs antics.

## Resum

- Estat global: **cobertura funcional alta** per operacio P0.
- Estat per retirada immediata: **no recomanat encara**.
- Motiu: alguns fitxers antics son "living docs" (tracking i backlog) i no equival unificable 1:1.

## Mapping originals -> docs hub

`README.md`

- Cobert a: `core.md`, `runtime_flow.md`, `operations.md`, `inventory.md`
- Estat: gairebe complet.

`ARCHITECTURE.md`

- Cobert a: `core.md`
- Estat: parcial (arquitectura historicament mes extensa al fitxer original).

`COMPONENTS.md`

- Cobert a: `core.md`, `server_api.md`, `operations.md`
- Estat: parcial.

`ROADMAP.md`

- Cobert a: `decisions_and_outcomes.md` (des del que realment s'ha executat)
- Estat: parcial (roadmap original segueix sent referencia de planificacio).

`STRUCTURE.md`

- Cobert a: `inventory.md`, `core.md`
- Estat: parcial.

`colab-worker/README.md`

- Cobert a: `runtime_flow.md`, `operations.md`, `errors.md`
- Estat: gairebe complet.

`colab-worker/COLAB_NOTEBOOK_PLAN.md`

- Cobert a: `runtime_flow.md`
- Estat: parcial (les cel.les detallades encara viuen al document original).

`server-api/README.md`

- Cobert a: `server_api.md`, `operations.md`
- Estat: gairebe complet.

`ops/README.md`

- Cobert a: `operations.md`, `observability.md`
- Estat: complet per P0.

`ops/PLAN_TRACKER.md`

- Cobert a: no es replica intencionalment.
- Estat: mantenir com a document viu de seguiment.

`ops/IMPLEMENTATION_TODO.md`

- Cobert a: no es replica intencionalment.
- Estat: mantenir com a backlog viu.

`ops/REAL_ENV_ROLLOUT.md`

- Cobert a: `runtime_flow.md`, `decisions_and_outcomes.md`
- Estat: parcial.

`ops/REPO_SETUP.md`

- Cobert a: `operations.md` (part operativa)
- Estat: parcial.

`local-frontend/README.md`, `shared/README.md`, `tests/README.md`

- Cobert a: `inventory.md`
- Estat: minim, recomanat mantenir originals per ara.

## Gaps detectats (a completar abans d'eliminar originals)

1. Crear fitxa especifica de frontend local i contractes de polling.
2. Crear fitxa especifica de `shared/` i contractes de clients/utils.
3. Consolidar roadmap historic + estat actual en un sol document de estrategia.

## Criteri de retirada de docs antics

Eliminar docs antics nomes quan:

- cada original tingui cobertura equivalent explicitada al hub,
- no perdi detall executable,
- i els fitxers de tracking viu (`PLAN_TRACKER`, `IMPLEMENTATION_TODO`) tinguin substitut clar.
