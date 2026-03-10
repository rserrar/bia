$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$publicDir = Join-Path $root "..\server-api\php\public"

Write-Host "Iniciant API PHP local a http://127.0.0.1:8080"
Set-Location $publicDir
php -S 127.0.0.1:8080
