# Colab Worker

Conté el codi d'execució automàtica del pipeline d'evolució de models.

Guia de notebook per prova real:

- `COLAB_NOTEBOOK_PLAN.md`
- `V2_real_run_notebook.ipynb`
- Config de validació Fase 0: `../ops/configs/phase0_model_validation.json`

## Compatibilitat amb models legacy

El worker pot verificar que una definició de model de la versió antiga es continua construint.
Per executar aquesta verificació cal tenir TensorFlow instal·lat a l'entorn.

Variables:

- `V2_VERIFY_LEGACY_MODEL_BUILD`
- `V2_LEGACY_BUILD_CHECK_STRICT`
- `V2_LEGACY_MODEL_JSON_PATH`
- `V2_LEGACY_EXPERIMENT_CONFIG_PATH`
- `V2_LEGACY_BUILDER_PATH`
