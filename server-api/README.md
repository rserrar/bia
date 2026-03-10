# Server API

Conté l'API de coordinació, estat, seguretat i persistència del sistema.

## Implementació actual

- Implementació principal en PHP: `server-api/php/public/index.php`
- Persistència JSON local: `server-api/state/state.json`
- Contracte de referència: `V2/shared/schemas/api_contract.json`

## Execució local ràpida

```bash
cd V2/server-api/php/public
php -S 0.0.0.0:8080
```

Variables d'entorn opcionals:

- `V2_STATE_FILE` per canviar la ruta del fitxer d'estat
- `V2_API_TOKEN` per activar validació simple Bearer token
