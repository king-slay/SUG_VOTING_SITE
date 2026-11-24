. (Join-Path $PSScriptRoot "common.ps1")
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
Import-LocalEnv $PSScriptRoot
$python = Find-VenvPython $root
if (-not $python) { Write-Host "The site is not installed on this laptop yet. Run defence\install.bat first." -ForegroundColor Red; exit 1 }
& $python manage.py @args
exit $LASTEXITCODE
