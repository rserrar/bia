# V2 Documentation Core

La V2 es una plataforma distribuida per generar, validar i entrenar models de forma automatitzada amb tres peces: worker (Colab), API PHP i monitor/ops.

L'objectiu practic es mantenir cicles curts i repetibles on es pugui:

- generar propuestas (LLM o seed),
- entrenarlas,
- guardar artefactos,
- i traçar en quin context es va generar cada proposta.

## General flow

1. El worker crea o recupera `run`.
2. Si no hi ha propostes i bootstrap esta activat, crea un seed model.
3. El worker genera propostes LLM per generacio i les envia a phase0.
4. El trainer pren propostes, les entrena i publica events, metrics i artifacts.
5. El monitor/API permet consultar estat, propostes, events i metadades finals.

## Skill structure

- `core.md`: visio global, flux i mapa de coneixement.
- `runtime_flow.md`: flux operatiu curt per proves (Colab/API).
- `server_api.md`: contractes i comportament real d'endpoints.
- `operations.md`: comandes/scripts recomanats per operar.
- `observability.md`: on mirar estat, logs i artefactes.
- `errors.md`: errors reals ja vistos i diagnostic.
- `inventory.md`: inventari de tots els `.md` actuals del repo V2.

## Detail and navigation

Per operar en proves curtes (5-10 minuts) i validar pipeline complet:

<runtime_flow>

Per entendre detalls de rutes/API, prefixes i metadades persistides:

<server_api>

Per estandarditzar arrencada/aturada i scripts P0:

<operations>

Per observar progres real en execucio (events/artifacts/proposals):

<observability>

Per resoldre incidencies ja conegudes sense repetir debugging:

<errors>

Per localitzar tota la documentacio existent i no perdre res:

<inventory>
