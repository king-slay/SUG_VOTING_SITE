# Shared by install.ps1, start.ps1 and manage.ps1.

$UnnvoteHome = Join-Path $env:LOCALAPPDATA "unnvote"

# Where the venv may live, best first. New installs put it in %LOCALAPPDATA%\unnvote\venv:
# a short path (TensorFlow has very long file names), outside OneDrive, and not copied
# along when the project folder moves to another laptop.
function Get-VenvCandidates($root) {
    @(
        (Join-Path $UnnvoteHome "venv"),
        "C:\unnvote\venv",
        (Join-Path $root "venv")
    )
}

# Python inside a venv that actually runs on this laptop, or $null.
function Find-VenvPython($root) {
    $ErrorActionPreference = "Continue"
    foreach ($venv in Get-VenvCandidates $root) {
        $python = Join-Path $venv "Scripts\python.exe"
        if (Test-Path $python) {
            try {
                & $python -c "import django" 2>$null | Out-Null
                if ($LASTEXITCODE -eq 0) { return $python }
            } catch {}
        }
    }
    return $null
}

function Find-Cloudflared {
    $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($p in @("${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe", "$env:ProgramFiles\cloudflared\cloudflared.exe",
                     (Join-Path $UnnvoteHome "cloudflared.exe"))) {
        if ($p -and (Test-Path $p)) { return $p }
    }
    return $null
}

# Optional extra settings (for example the MYSQL_ ones), one NAME=value per line.
function Import-LocalEnv($here) {
    $localEnv = Join-Path $here "local.env"
    if (Test-Path $localEnv) {
        Get-Content $localEnv | Where-Object { $_ -match "^\s*[A-Z_]+=" } | ForEach-Object {
            $name, $value = $_.Trim() -split "=", 2
            Set-Item "env:$name" $value
        }
    }
}
