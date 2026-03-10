# Roadmap V2

## Fase 0 - Base de projecte

Objectiu:

- Crear estructura de carpetes V2
- Definir contractes i convencions

Entregables:

- Estructura inicial de directoris
- Especificació d'API i esquemes JSON
- Plantilla de configuració d'entorns

## Fase 1 - MVP funcional

Objectiu:

- Pipeline executant-se a Colab amb control via API

Entregables:

- Worker amb bucle bàsic i checkpoints
- API amb runs/heartbeat/events/metrics
- Persistència bàsica de metadades i estat

Criteri d'acceptació:

- Un run complet amb mínim 1 generació i monitoratge remot

## Fase 2 - Robustesa

Objectiu:

- Evitar bloquejos i pèrdua de progrés

Entregables:

- Reintents amb backoff exponencial
- Idempotència de crides crítiques
- Fallback Drive -> servidor per artefactes
- Recuperació automàtica després d'aturada de sessió

Criteri d'acceptació:

- Simulació de fallades superada sense pèrdua d'estat

## Fase 3 - Frontend local

Objectiu:

- Visualització estable i útil per seguiment operatiu

Entregables:

- Dashboard local de runs, mètriques i errors
- Vista de timeline d'execució
- Històric resumit de generacions i models

## Fase 4 - Enduriment i manteniment

Objectiu:

- Preparar la plataforma per evolució contínua

Entregables:

- Tests d'integració
- Validació de contractes API
- Traçabilitat de versions de codi i configuració
- Guia d'operació i checklist de release

## Prioritat inicial recomanada

1. API mínima
2. Worker Colab resumible
3. Persistència i fallback
4. Frontend local

