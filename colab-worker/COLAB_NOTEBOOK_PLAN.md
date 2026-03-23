# Guia de notebook Colab per a prova real (V2 runtime-ready)

## Objectiu

Executar V2 a Colab amb comprovacions *fail-fast* perquè, si falta algun fitxer o configuració, el notebook falli de seguida amb un error clar.

## Notebook recomanat

Fes servir el notebook nou:

- `V2/colab-worker/V2_runtime_ready_colab.ipynb`

Aquest fitxer està pensat per executar-se des de `/content/b-ia`.
Per defecte, les rutes operatives són relatives a aquesta arrel (`config/`, `prompts/`, `configs/`, `shared/`, etc.).

## Flux resumit

1. Muntar Drive i clonar/actualitzar repo.
2. Instal·lar dependències Python.
3. Definir variables d'entorn (API, checkpoint, LLM, paths).
4. Verificar fitxers i estructura requerida.
5. Verificar dataset i aplicar compatibilitat de noms CSV (si cal).
6. Verificar connectivitat amb servidor (`probe_api_prefix` + `go_no_go_check`).
7. Executar `run_phase0_model_validation.py`.
8. Executar `run_llm_full_prompt_check.py` en mode sec.
9. Executar worker (`run_worker.py`).
10. Recuperar `run_id` i (opcional) executar compile-check de propostes.

## Notes importants

- Executa des de `/content/b-ia` (no des de `/content/b-ia/V2`) per mantenir consistència amb `data_dir: data/min`.
- Si el servidor requereix token, posa `V2_API_TOKEN` real abans de córrer les cèl·lules de connectivitat.
- El notebook no activa enviament real a LLM per defecte (`V2_PROMPT_SEND_TO_LLM=false`).
