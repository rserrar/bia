# Clean State Policy

Objectiu: definir que vol dir "estat net" abans d'un run nou i quines neteges son segures.

## Clean state minimum

Abans d'un run nou, el sistema hauria de complir:

- no hi ha runs en `retrying` massa antics,
- no hi ha proposals en `training` massa antigues,
- la cua `queued_phase0` no porta massa temps sense reprocessar-se,
- metadades de training i artifacts estan persistides per a proposals `trained`.

## Safe automatic cleanup

Accions considerades segures per automatitzar:

1. `queued/running -> retrying`
   - via watchdog quan el run no envia heartbeat dins del llindar.

2. `retrying -> failed`
   - quan el run continua encallat massa temps despres del retry.

3. `training -> accepted`
   - quan una proposta queda bloquejada en training sense activitat suficient.
   - objectiu: reencuar per nou intent.

4. reprocessar cua `queued_phase0`
   - quan hi ha propostes pendents i el run origen ja es terminal.

## Audit-only states

Aquests casos es detecten pero no es modifiquen automaticament per defecte:

- `accepted` massa antic
- `validated_phase0` massa antic

Rao:

- poden ser decisions operatives legitimes,
- forcar reclassificacio automàtica podria amagar errors de planificacio o de govern.

## Cleanup outputs required

Qualsevol cleanup ha de produir:

- resum de deteccio,
- llista d'accions aplicades,
- motiu (`cleanup_reason`) quan es toca una proposal,
- event d'auditoria al run si es modifica estat.

## Script

Script canonic:

- `ops/scripts/cleanup_inconsistent_state.py`

Modes:

- `V2_CLEANUP_MODE=dry-run`
- `V2_CLEANUP_MODE=apply`
