# Configuració del repositori V2

Aquest projecte V2 està inicialitzat com a repositori Git independent dins `V2/`.

## Remote configurat

- `origin`: `https://github.com/rserrar/bia.git`

## Flux recomanat

1. Treballar només dins `V2/`
2. Validar el codi localment
3. Fer commit de canvis petits per component
4. Fer push a `main` o a branques de feature

## Comandes útils

```bash
git status
git add .
git commit -m "feat: base api service and colab worker skeleton"
git push -u origin main
```

## Política de seguretat pràctica (API privada)

Encara que l'API sigui privada:

- no pujar secrets al repositori
- mantenir token en variables d'entorn
- evitar logs amb credencials
- usar HTTPS sempre

