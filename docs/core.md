# V2 Documentation Core

La V2 es una plataforma distribuida per generar, validar i entrenar models de forma automatitzada amb tres peces: worker (Colab), API PHP i capa d'operacio/monitoratge.

L'objectiu practic actual es executar cicles curts, repetibles i auditables on es pugui:

- generar propostes (LLM o seed bootstrap),
- entrenar-les,
- guardar artifacts,
- i traçar exactament en quin context es va crear cada model.

## General flow

1. El worker crea o recupera `run`.
2. Si no hi ha propostes i el bootstrap esta actiu, crea una proposta seed.
3. El worker genera propostes LLM per generacio i les envia a phase0.
4. El trainer bloqueja propostes, entrena i publica events/metrics/artifacts.
5. L'API i el monitor permeten inspeccionar estat, metadades i resultats finals.

## Skill structure

- `core.md`: visio global i mapa de navegacio.
- `runtime_flow.md`: flux curt executable de proves.
- `architecture.md`: visio tecnica i contractes que no han de regressar.
- `components.md`: responsabilitats i limits de cada component.
- `roadmap.md`: estat de fases i outcomes esperats.
- `structure.md`: estructura actual i politica documental.
- `selection_policy_v1.md`: contracte de scoring/promocio/traçabilitat per seleccio de referencies.
- `selection_policy_v1_1.md`: champion selection i perfils de thresholds per context.
- `clean_state_policy.md`: politica de cleanup i criteris d'estat net abans d'un run.
- `legacy_inventory.md`: inventari de peces legacy encara vives.
- `runbook_operations.md`: cami canonic d'operacio per un tecnic.
- `data_contract_frontend.md`: quines dades s'envien, es persisteixen i es serveixen a frontend.
- `server_api.md`: contractes i comportament real d'endpoints.
- `operations.md`: arrencada, parada i scripts operatius.
- `observability.md`: visibilitat runtime i interpretacio rapida.
- `errors.md`: incidencies reals i patrons de resolucio.
- `decisions_and_outcomes.md`: que hem canviat, per que i que esperem obtenir.
- `coverage_audit.md`: comparativa originals vs hub centralitzat.
- `inventory.md`: inventari complet dels `.md` del repo.

## Detail and navigation

Per executar en fase de proves (5-10 minuts):

<runtime_flow>

Per arquitectura i contractes essencials:

<architecture>

Per mapa de components i responsabilitats:

<components>

Per estat de fases i orientacio propera:

<roadmap>

Per estructura i politica de documentacio:

<structure>

Per contracte de seleccio i relacio policy <-> LLM:

<selection_policy_v1>

Per extensio v1.1 amb champion i context profiles:

<selection_policy_v1_1>

Per cleanup i estat net operatiu:

<clean_state_policy>

Per inventari de restes legacy a eliminar mes endavant:

<legacy_inventory>

Per operacio diària i checklist final:

<runbook_operations>

Per contracte de dades frontend-ready:

<data_contract_frontend>

Per entendre el contracte real de l'API i metadades de proposals:

<server_api>

Per operar scripts P0 en local/Colab:

<operations>

Per veure progres real de run/proposals/training:

<observability>

Per entendre decisions de fons i resultats esperats:

<decisions_and_outcomes>

Per revisar buits de cobertura abans d'eliminar docs antics:

<coverage_audit>

Per troubleshooting basat en experiencia:

<errors>

Per localitzar tota la documentacio existent:

<inventory>
