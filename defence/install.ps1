# One-time setup of the voting site on a Windows laptop. Safe to run again:
# it skips whatever is already in place. Run with defence\install.bat.
#   1. Python 3.12 and cloudflared (installed with winget if missing)
#   2. The venv and the Python packages
#   3. The face models (about 300 MB, downloaded once)
#   4. The database, and the first committee (chair) account
#   5. A "Start UNN Voting" shortcut on the desktop

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$root = Split-Path $here -Parent
Set-Location $root

# Optional extra settings (for example the MYSQL_ ones), the same file start.bat reads.
$localEnv = Join-Path $here "local.env"
if (Test-Path $localEnv) {
    Get-Content $localEnv | Where-Object { $_ -match "^\s*[A-Z_]+=" } | ForEach-Object {
        $name, $value = $_.Trim() -split "=", 2
        Set-Item "env:$name" $value
    }
}

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "`n$text" -ForegroundColor Red; exit 1 }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}
function Winget-Install($id, $name) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Fail "winget is missing, so $name cannot be installed automatically. Install 'App Installer' from the Microsoft Store, then run this again."
    }
    Write-Host "Installing $name (this can take a few minutes)..."
    winget install -e --id $id --accept-package-agreements --accept-source-agreements --silent
    Refresh-Path
}

Step "1/5  Python 3.12 and cloudflared"
function Find-Python {
    try { $p = & py -3.12 -c "import sys; print(sys.executable)" 2>$null; if ($LASTEXITCODE -eq 0 -and $p) { return $p.Trim() } } catch {}
    foreach ($p in @("$env:LOCALAPPDATA\Programs\Python\Python312\python.exe", "C:\Program Files\Python312\python.exe")) {
        if (Test-Path $p) { return $p }
    }
    return $null
}
$python312 = Find-Python
if (-not $python312) {
    Winget-Install "Python.Python.3.12" "Python 3.12"
    $python312 = Find-Python
    if (-not $python312) { Fail "Python 3.12 did not install. Install it from python.org (64-bit), then run this again." }
}
Write-Host "Python: $python312"

$cloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $cloudflared -and -not (Test-Path "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe")) {
    Winget-Install "Cloudflare.cloudflared" "cloudflared"
}
Write-Host "cloudflared: ready"

Step "2/5  Python packages (the first time this downloads about 1 GB)"
$venvPython = Join-Path $root "venv\Scripts\python.exe"
$venvWorks = $false
if (Test-Path $venvPython) {
    try { & $venvPython -c "import sys" 2>$null; $venvWorks = ($LASTEXITCODE -eq 0) } catch {}
}
if (-not $venvWorks) {
    # A venv copied from another laptop points at that laptop's Python, so it is rebuilt.
    if (Test-Path (Join-Path $root "venv")) { Write-Host "Rebuilding the venv (it came from another computer)..."; Remove-Item -Recurse -Force (Join-Path $root "venv") }
    & $python312 -m venv venv
    if ($LASTEXITCODE -ne 0) { Fail "Could not create the venv." }
}
& $venvPython -m pip install --upgrade pip -q
& $venvPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    # mysqlclient is only needed for MySQL; the laptop uses SQLite unless told otherwise.
    Write-Host "Retrying without the MySQL driver..." -ForegroundColor Yellow
    $reqs = Join-Path $env:TEMP "unnvote-requirements.txt"
    Get-Content requirements.txt | Where-Object { $_ -notmatch "^\s*mysqlclient" } | Set-Content $reqs
    & $venvPython -m pip install -r $reqs
    if ($LASTEXITCODE -ne 0) { Fail "Installing the Python packages failed (see the messages above). Check the internet connection and run this again." }
}

Step "3/5  Face models"
& $venvPython manage.py practice_election warmup
if ($LASTEXITCODE -ne 0) { Fail "Downloading the face models failed. Check the internet connection and run this again." }

Step "4/5  Database and the first committee account"
& $venvPython manage.py migrate --noinput
if ($LASTEXITCODE -ne 0) { Fail "Setting up the database failed (see above)." }
$chairs = & $venvPython manage.py shell -c "from django.contrib.auth.models import User; print(User.objects.filter(is_superuser=True, is_active=True).count())"
if ([int]($chairs | Select-Object -Last 1) -eq 0) {
    Write-Host "Create the first chair account. Chairs sign in at /staff/ and add the other committee members there."
    Write-Host "(Email can be left blank. The password does not show while you type.)"
    & $venvPython manage.py createsuperuser
    if ($LASTEXITCODE -ne 0) { Fail "The chair account was not created. Run this again to retry." }
} else {
    Write-Host "A chair account already exists. Add more committee members on the site under Committee."
}

Step "5/5  Desktop shortcut"
try {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desktop "Start UNN Voting.lnk"))
    $shortcut.TargetPath = Join-Path $here "start.bat"
    $shortcut.WorkingDirectory = $here
    $shortcut.Save()
    Write-Host "Added 'Start UNN Voting' to the desktop."
} catch {
    Write-Host "Could not add the desktop shortcut. Use defence\start.bat instead." -ForegroundColor Yellow
}

Write-Host "`nAll set. Double-click 'Start UNN Voting' on the desktop to run the site." -ForegroundColor Green
