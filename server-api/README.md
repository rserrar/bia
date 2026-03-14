# Server API

Conté l'API de coordinació, estat, seguretat i persistència del sistema.

## Implementació actual

- Implementació principal en PHP: `server-api/php/public/index.php`
- Persistència recomanada: SQLite (`server-api/state/state.sqlite`)
- Persistència alternativa: JSON (`server-api/state/state.json`)
- Contracte de referència: `V2/shared/schemas/api_contract.json`

## Execució local ràpida

```bash
cd V2/server-api/php/public
php -S 0.0.0.0:8080
```

Variables d'entorn opcionals:

- `V2_STATE_FILE` per canviar la ruta del fitxer d'estat
- `V2_STORAGE_BACKEND` (`sqlite` o `json`)
- `V2_SQLITE_PATH` per canviar la ruta del fitxer SQLite
- `V2_STORAGE_FALLBACK_JSON` per fer fallback automàtic a JSON si falla SQLite
- `V2_API_TOKEN` per activar validació simple Bearer token
- `V2_WATCHDOG_STALE_SECONDS` per ús del script watchdog
- `V2_DOTENV_PATH` per carregar un fitxer `.env` explícit

## Configuració amb fitxer .env

L'entrada PHP carrega `.env` automàticament des de:

- `server-api/php/.env`
- `server-api/.env`

També pots indicar una ruta concreta amb `V2_DOTENV_PATH`.

Exemple ràpid:

```bash
cd V2/server-api/php
cp .env.example .env
```

Exemple recomanat (persistència SQLite):

```env
V2_STORAGE_BACKEND=sqlite
V2_SQLITE_PATH=../state/state.sqlite
V2_STORAGE_FALLBACK_JSON=true
```

Rutes acceptades segons desplegament:

- `/runs`
- `/public/runs`
- `/public/index.php/runs`
- `/public/model-proposals`
- `/public/index.php/model-proposals`

Contracte de propostes LLM:

- `POST /model-proposals`
- `GET /model-proposals?limit=100`
- `GET /model-proposals/{proposal_id}`
- `POST /model-proposals/{proposal_id}/status`
- `POST /model-proposals/{proposal_id}/enqueue-phase0`
- `POST /maintenance/process-model-proposals-phase0`
- `GET /runs/{run_id}/events?limit=200`

L'endpoint de manteniment de phase0 processa propostes `queued_phase0` i les marca automàticament com `validated_phase0` o `rejected`.

## Rewrite Apache

Si el servidor és Apache, fes servir:

- `server-api/php/public/.htaccess`

Requisits:

- `mod_rewrite` actiu
- `AllowOverride All` al directori `public`

## Monitor web bàsic

Pàgina de monitor:

- `server-api/php/public/monitor.php`

URL exemple:

- `https://<host>/public/monitor.php?token=<V2_API_TOKEN>`

Després de validar el token una vegada, el monitor guarda sessió PHP i ja no cal repetir el token a cada clic.
El monitor també mostra `model_proposals`, permet veure'n el detall JSON i canviar l'estat.
Inclou acció ràpida `Enviar a phase0`, que marca la proposta com `queued_phase0`.
Inclou botó `Reset dades prova`, que esborra runs, events, mètriques, artifacts i proposals.

## Smoke test

Amb l'API en marxa:

```bash
cd V2
python ops/scripts/smoke_test_api.py
```

## Watchdog de heartbeat

Per marcar runs `queued/running` sense senyal com `retrying`:

```bash
cd V2
python ops/scripts/watchdog_retry.py
```
