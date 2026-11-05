# Starts the voting site on this laptop in production mode, opens a public https
# link with a Cloudflare quick tunnel, and shows the link as a QR code.
# Run with defence\start.bat. Press Enter in this window to stop everything.

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$root = Split-Path $here -Parent
$python = Join-Path $root "venv\Scripts\python.exe"
Set-Location $root

function Fail($message) { Write-Host "`n$message" -ForegroundColor Red; exit 1 }

if (-not (Test-Path $python)) { Fail "No venv found in $root. Create it first (see README)." }
if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Fail "cloudflared is not installed. Run: winget install --id Cloudflare.cloudflared"
}

# Production settings. The secret key is made once and kept in defence\secret.txt.
$secretFile = Join-Path $here "secret.txt"
if (-not (Test-Path $secretFile)) {
    $bytes = New-Object byte[] 48
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    [Convert]::ToBase64String($bytes) | Set-Content -NoNewline $secretFile
}
$env:DJANGO_SECRET_KEY = (Get-Content $secretFile -Raw).Trim()
$env:DJANGO_DEBUG = "false"
$env:DJANGO_ALLOWED_HOSTS = "localhost,127.0.0.1,.trycloudflare.com"
$env:DJANGO_CSRF_TRUSTED_ORIGINS = "https://*.trycloudflare.com,http://localhost:8000,http://127.0.0.1:8000"
$env:PYTHONUNBUFFERED = "1"

# Optional extra settings, one NAME=value per line (for example the MYSQL_ ones).
$localEnv = Join-Path $here "local.env"
if (Test-Path $localEnv) {
    Get-Content $localEnv | Where-Object { $_ -match "^\s*[A-Z_]+=" } | ForEach-Object {
        $name, $value = $_.Trim() -split "=", 2
        Set-Item "env:$name" $value
    }
}

Write-Host "Preparing the database and static files..."
& $python manage.py migrate --noinput
if ($LASTEXITCODE -ne 0) { Fail "Database migration failed (see above)." }
& $python manage.py collectstatic --noinput -v 0
if ($LASTEXITCODE -ne 0) { Fail "collectstatic failed (see above)." }

Write-Host "Starting the site (a second window shows its log, including face scan times)..."
$server = Start-Process $python -ArgumentList "-m", "waitress", "--listen=127.0.0.1:8000", "--threads=8", "unnvote.wsgi:application" -PassThru

$up = $false
foreach ($i in 1..60) {
    try {
        Invoke-WebRequest "http://127.0.0.1:8000/" -UseBasicParsing -TimeoutSec 5 | Out-Null
        $up = $true; break
    } catch { Start-Sleep -Seconds 2 }
}
if (-not $up) { Stop-Process -Id $server.Id -ErrorAction SilentlyContinue; Fail "The site did not start. Check the server window for errors." }

Write-Host "Opening the public link..."
$log = Join-Path $here "tunnel.log"
Remove-Item $log -ErrorAction SilentlyContinue
$tunnel = Start-Process cloudflared -ArgumentList "tunnel", "--url", "http://localhost:8000" -RedirectStandardError $log -WindowStyle Hidden -PassThru

$url = $null
foreach ($i in 1..60) {
    Start-Sleep -Seconds 1
    if (Test-Path $log) {
        $match = Select-String -Path $log -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" | Select-Object -First 1
        if ($match) { $url = $match.Matches[0].Value; break }
    }
}
if (-not $url) {
    Write-Host "No public link yet. Check the internet connection; the site still works at http://localhost:8000" -ForegroundColor Yellow
} else {
    & $python defence\show_link.py $url
    Write-Host ""
    Write-Host "  Public link:  $url" -ForegroundColor Green
    Write-Host "  Committee:    $url/staff/login/"
    Write-Host "  The QR code is open in your browser for examiners to scan."
}

Write-Host "`nThe face models finish loading about a minute after start ('Face models loaded' in the server window)."
Read-Host "`nPress Enter to stop the site and the link"
Stop-Process -Id $tunnel.Id -ErrorAction SilentlyContinue
Stop-Process -Id $server.Id -ErrorAction SilentlyContinue
Write-Host "Stopped."
