# Components V2

## 1) Colab Worker

Responsabilitat:

- Executar el pipeline d'evolució de models de forma autònoma
- Reprendre execució des de checkpoints
- Publicar estat i resultats al Server API

Submòduls a `src/` recomanats/implementats:

- `run_worker.py`: arrencada, dependències, càrrega de codi
- `engine.py`: bucle principal d'evolució
- `checkpoint_store.py`: persistència d'estat
- `api_client.py`: comunicació amb el servidor API i fallback
- `llm_client.py` / `v2_prompt_builder.py`: generació i reparació de propostes
- `config.py`: configuració de l'entorn

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

S'ha implementat principalment sota `server-api/php/`:

- Orquestrar runs/jobs (Emmagatzematge SQLite o JSON fallback)
- Proveir interfície web per al monitoratge (`public/monitor.php`)
- Exposar endpoints segurs per worker i frontend

Endpoints mínims implementats (`public/index.php`):

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

