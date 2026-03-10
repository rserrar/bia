# Components V2

## 1) Colab Worker

Responsabilitat:

- Executar el pipeline d'evolució de models de forma autònoma
- Reprendre execució des de checkpoints
- Publicar estat i resultats al Server API

Submòduls recomanats:

- `bootstrap/`: arrencada, dependències, càrrega de codi
- `engine/`: bucle principal d'evolució
- `state/`: checkpoints i control de resum
- `storage/`: Drive principal + fallback servidor
- `reporting/`: events, mètriques i artefactes

Entrades:

- Configuració de run
- Dades CSV (Drive)
- Models base

Sortides:

- Models generats/validats
- Mètriques
- Checkpoints
- Logs d'execució

## 2) Server API

Responsabilitat:

- Orquestrar runs/jobs
- Emmagatzemar estat i metadades
- Exposar endpoints segurs per worker i frontend

Endpoints mínims:

- `POST /runs`
- `POST /runs/{run_id}/heartbeat`
- `POST /runs/{run_id}/events`
- `POST /runs/{run_id}/metrics`
- `POST /runs/{run_id}/artifacts`
- `GET /runs/{run_id}`
- `GET /runs/{run_id}/summary`

Seguretat:

- Tokens amb expiració
- Rols separats (worker write / frontend read)
- Auditories bàsiques de canvis i errors

## 3) Frontend Local (Windows)

Responsabilitat:

- Visualitzar l'estat de runs
- Mostrar timeline, errors i mètriques
- Permetre inspecció de resultats sense tocar l'execució

Comportament:

- Polling cada 15-60 segons
- Mode tolerant a desconnexions
- Cache local de la darrera lectura vàlida

## 4) Shared (comú)

Conté:

- Esquemes JSON de contracte
- Client API compartit
- Helpers comuns de serialització/validació

