# Sets up the voting site on a Windows laptop, part by part. A part that fails does
# not stop the others: at the end a summary says what worked, what failed and how to
# fix it. Safe to run again: finished parts are quick the second time.
# Run with defence\install.bat. Everything shown is also saved to defence\install-log.txt.

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest is very slow with the progress bar
$here = $PSScriptRoot
$root = Split-Path $here -Parent
. (Join-Path $here "common.ps1")
Set-Location $root
Import-LocalEnv $here
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}

$logFile = Join-Path $here "install-log.txt"
try { Start-Transcript -Path $logFile -Force | Out-Null } catch {}

$results = New-Object System.Collections.ArrayList
$state = @{}   # what later parts need from earlier ones

$env:PYTHONUNBUFFERED = "1"

function Note($text) { Write-Host "   $text" }
# Shows a command's output (and errors) on screen and in the log, without it being
# mistaken for a part's result.
filter Show { Write-Host "$_" }
function Warn($text) { Write-Host "   $text" -ForegroundColor Yellow }

# Runs one part. The script block returns $null when the part worked, or a short
# message saying what is wrong and how to fix it. "WARN:" at the start means it is not
# needed for the site to run.
function Part($number, $name, $needs, [scriptblock]$body) {
    Write-Host "`n== Part $number of 10: $name" -ForegroundColor Cyan
    foreach ($need in $needs) {
        if (-not $state[$need]) {
            Warn "Skipped: needs '$need', which did not finish above."
            [void]$results.Add([pscustomobject]@{ Part = "$number. $name"; Status = "SKIPPED"; Fix = "Fix '$need' first, then run install.bat again." })
            return
        }
    }
    $problem = $null
    try { $problem = & $body } catch { $problem = "Unexpected error: $($_.Exception.Message)" }
    if (-not $problem) {
        Write-Host "   OK" -ForegroundColor Green
        [void]$results.Add([pscustomobject]@{ Part = "$number. $name"; Status = "OK"; Fix = "" })
    } elseif ("$problem".StartsWith("WARN:")) {
        $text = "$problem".Substring(5).Trim()
        Warn $text
        [void]$results.Add([pscustomobject]@{ Part = "$number. $name"; Status = "WARNING"; Fix = $text })
    } else {
        Write-Host "   FAILED: $problem" -ForegroundColor Red
        [void]$results.Add([pscustomobject]@{ Part = "$number. $name"; Status = "FAILED"; Fix = $problem })
    }
}

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

function Winget-Install($id) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { return $false }
    Note "Installing $id with winget (a few minutes; click Yes if Windows asks)..."
    winget install -e --id $id --accept-package-agreements --accept-source-agreements --silent 2>&1 | Show
    Refresh-Path
    return $true
}

# A 64-bit Python 3.10, 3.11 or 3.12 (TensorFlow has no packages for newer or 32-bit ones).
function Test-Python($exe) {
    if (-not $exe -or -not (Test-Path $exe)) { return $false }
    try {
        $out = & $exe -c "import sys, struct; print(sys.version_info[0]*100 + sys.version_info[1], struct.calcsize('P')*8)" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $out) { return $false }
        $version, $bits = "$out".Trim() -split " "
        return ([int]$version -ge 310 -and [int]$version -le 312 -and [int]$bits -eq 64)
    } catch { return $false }
}

function Find-Python {
    foreach ($v in @("3.12", "3.11", "3.10")) {
        try {
            $exe = & py "-$v" -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $exe -and (Test-Python "$exe".Trim())) { return "$exe".Trim() }
        } catch {}
    }
    foreach ($v in @("312", "311", "310")) {
        foreach ($base in @("$env:LOCALAPPDATA\Programs\Python", "$env:ProgramFiles")) {
            $exe = Join-Path $base "Python$v\python.exe"
            if (Test-Python $exe) { return $exe }
        }
    }
    return $null
}

# Makes a venv at $venv. Returns $null on success, otherwise the error text.
function New-Venv($python, $venv) {
    if (Test-Path $venv) {
        Note "Removing an unfinished or broken venv at $venv ..."
        Remove-Item -Recurse -Force $venv -ErrorAction SilentlyContinue
        if (Test-Path $venv) { return "could not delete the old folder $venv (close any window or editor using it, or delete it by hand)" }
    }
    $parent = Split-Path $venv -Parent
    try { New-Item -ItemType Directory -Force -Path $parent -ErrorAction Stop | Out-Null } catch { return "cannot create folder $parent : $($_.Exception.Message)" }

    $out = & $python -m venv $venv 2>&1 | ForEach-Object { "$_" } | Out-String
    if ($LASTEXITCODE -eq 0 -and (Test-Path (Join-Path $venv "Scripts\python.exe"))) { return $null }
    Warn "Normal venv creation failed: $($out.Trim())"

    # Most often the pip set-up step (ensurepip) is what fails, e.g. blocked by antivirus.
    # Make the venv without pip, then fetch pip directly.
    Remove-Item -Recurse -Force $venv -ErrorAction SilentlyContinue
    $out2 = & $python -m venv --without-pip $venv 2>&1 | ForEach-Object { "$_" } | Out-String
    $vpy = Join-Path $venv "Scripts\python.exe"
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $vpy)) { return "$($out.Trim()) / $($out2.Trim())" }
    Note "Made the venv without pip; downloading pip..."
    $getPip = Join-Path $env:TEMP "get-pip.py"
    try { Invoke-WebRequest "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPip -UseBasicParsing } catch { return "venv made but pip could not be downloaded: $($_.Exception.Message)" }
    & $vpy $getPip 2>&1 | Show
    if ($LASTEXITCODE -ne 0) { return "venv made but installing pip into it failed (see above)" }
    return $null
}

Write-Host "UNN SUG E-Voting installer" -ForegroundColor Cyan
Write-Host "Project folder: $root"

Part 1 "Check the project folder" @() {
    $state.folder = $true
    if ($root -like "*\AppData\Local\Temp\*" -or $root -match "\.zip\\") {
        return "WARN: This looks like it is running from inside the zip. Right-click the zip, choose Extract All, and run install.bat from the extracted folder."
    }
    try {
        $probe = Join-Path $root "write-test.tmp"
        Set-Content $probe "ok" -ErrorAction Stop; Remove-Item $probe
    } catch {
        return "WARN: Cannot write in $root. Move the project folder somewhere like Documents (not inside OneDrive or Program Files) and run again."
    }
    if ($root -like "*OneDrive*") { return "WARN: The folder is inside OneDrive, which can lock files while syncing. If something fails, move it to e.g. C:\Users\<you>\Documents and run again." }
}

Part 2 "Python 3.12" @() {
    $python = Find-Python
    if (-not $python) {
        if (Winget-Install "Python.Python.3.12") { $python = Find-Python }
    }
    if (-not $python) {
        return "Install Python 3.12 (64-bit) from https://www.python.org/downloads/release/python-3128/ (tick 'Add python.exe to PATH'), then run install.bat again. Python 3.13 or newer does not work with TensorFlow."
    }
    Note "Using $python"
    $state.python = $python
}

Part 3 "Long file paths" @() {
    $key = "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem"
    $on = (Get-ItemProperty $key -Name LongPathsEnabled -ErrorAction SilentlyContinue).LongPathsEnabled
    if ($on -eq 1) { return $null }
    Note "Windows long paths are off; TensorFlow needs them on some laptops. Asking Windows to turn them on (click Yes)..."
    try {
        Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList "-NoProfile", "-Command",
            "Set-ItemProperty -Path '$key' -Name LongPathsEnabled -Value 1 -Type DWord"
    } catch {}
    $on = (Get-ItemProperty $key -Name LongPathsEnabled -ErrorAction SilentlyContinue).LongPathsEnabled
    if ($on -ne 1) { return "WARN: Long paths are still off (Yes was not clicked, or no admin rights). Usually fine because the venv uses a short path." }
}

Part 4 "Cloudflare tunnel (public link)" @() {
    if (Find-Cloudflared) { return $null }
    Winget-Install "Cloudflare.cloudflared" | Out-Null
    if (Find-Cloudflared) { return $null }
    Note "Downloading cloudflared directly..."
    try {
        New-Item -ItemType Directory -Force -Path $UnnvoteHome | Out-Null
        Invoke-WebRequest "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" `
            -OutFile (Join-Path $UnnvoteHome "cloudflared.exe") -UseBasicParsing
    } catch {}
    if (-not (Find-Cloudflared)) { return "Download cloudflared-windows-amd64.exe from https://github.com/cloudflare/cloudflared/releases, rename it cloudflared.exe and put it in $UnnvoteHome. Without it the site only works on this laptop." }
}

Part 5 "Virtual environment (venv)" @("python") {
    # Keep a venv that already works on this laptop.
    foreach ($venv in Get-VenvCandidates $root) {
        $vpy = Join-Path $venv "Scripts\python.exe"
        if ((Test-Path $vpy) -and (Test-Python $vpy)) {
            & $vpy -m pip --version 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { Note "Using the existing venv at $venv"; $state.venv = $vpy; return $null }
        }
    }
    $errors = @()
    # The first place is short and outside the project folder; the others are fallbacks.
    foreach ($venv in Get-VenvCandidates $root) {
        Note "Creating the venv at $venv ..."
        $err = New-Venv $state.python $venv
        if (-not $err) { $state.venv = Join-Path $venv "Scripts\python.exe"; Note "Created at $venv"; return $null }
        Warn "Could not create it there: $err"
        $errors += "$venv -> $err"
    }
    return "Could not create a venv anywhere. Usual causes: antivirus blocking python.exe (allow it or pause protection), or a broken Python install (repair it from Settings > Apps). Details: $($errors -join ' | ')"
}

Part 6 "Python packages (about 1 GB the first time; TensorFlow alone can take 10+ minutes)" @("venv") {
    $py = $state.venv
    & $py -m pip install --upgrade pip --disable-pip-version-check -q 2>&1 | Show
    Note "Installing everything in requirements.txt. Big downloads can look stuck for several minutes; leave it running."
    & $py -m pip install --disable-pip-version-check -r requirements.txt 2>&1 | Show
    if ($LASTEXITCODE -eq 0) { $state.packages = $true; return $null }

    # Something failed: install the packages one at a time so one bad package does not block the rest.
    Warn "Installing everything at once failed. Trying the packages one by one..."
    $specs = Get-Content requirements.txt | ForEach-Object { ($_ -split "#", 2)[0].Trim() } | Where-Object { $_ }
    $failed = @()
    foreach ($spec in $specs) {
        Note "-> $spec"
        & $py -m pip install --disable-pip-version-check -q $spec 2>&1 | Show
        if ($LASTEXITCODE -ne 0) { $failed += $spec; Warn "   failed: $spec" }
    }
    $required = $failed | Where-Object { $_ -notmatch "^mysqlclient" }
    if (-not $required) {
        $state.packages = $true
        if ($failed) { return "WARN: Only the MySQL driver (mysqlclient) failed. It is not needed: the laptop uses its built-in SQLite database." }
        return $null
    }
    return "These packages did not install: $($required -join ', '). Check the internet connection and run install.bat again (it continues where it stopped). If it keeps failing, send defence\install-log.txt to the developer."
}

Part 7 "Face models (about 300 MB, downloaded once)" @("packages") {
    & $state.venv manage.py practice_election warmup 2>&1 | Show
    if ($LASTEXITCODE -ne 0) { return "The face models did not download or load (see the messages above). Check the internet connection and run install.bat again." }
}

Part 8 "Database" @("packages") {
    & $state.venv manage.py migrate --noinput 2>&1 | Show
    if ($LASTEXITCODE -ne 0) { return "Setting up the database failed (see the messages above). Send defence\install-log.txt to the developer." }
    $state.database = $true
}

Part 9 "First committee (chair) account" @("database") {
    $count = & $state.venv manage.py shell -c "from django.contrib.auth.models import User; print(User.objects.filter(is_superuser=True, is_active=True).count())" 2>$null
    if ([int]("$($count | Select-Object -Last 1)".Trim() -replace "\D", "0") -gt 0) {
        Note "A chair account already exists. Add the other committee members on the site under Committee."
        return $null
    }
    Note "Create the first chair account. Chairs sign in at /staff/ and add the other committee members there."
    Note "(Email can be left blank. The password does not show while you type.)"
    # Run straight in this window so its questions show while you type.
    $p = Start-Process -FilePath $state.venv -ArgumentList "manage.py", "createsuperuser" -WorkingDirectory $root -NoNewWindow -Wait -PassThru
    if ($p.ExitCode -ne 0) { return "The chair account was not created. Run install.bat again, or run: defence\manage.bat createsuperuser" }
}

Part 10 "Desktop shortcut" @() {
    try {
        $desktop = [Environment]::GetFolderPath("Desktop")
        $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desktop "Start UNN Voting.lnk"))
        $shortcut.TargetPath = Join-Path $here "start.bat"
        $shortcut.WorkingDirectory = $here
        $shortcut.Save()
        Note "Added 'Start UNN Voting' to the desktop."
    } catch {
        return "WARN: Could not add the desktop shortcut. Use defence\start.bat instead."
    }
}

Write-Host "`n================ SUMMARY ================" -ForegroundColor Cyan
foreach ($r in $results) {
    $colour = @{ OK = "Green"; WARNING = "Yellow"; SKIPPED = "DarkYellow"; FAILED = "Red" }[$r.Status]
    Write-Host ("{0,-9} {1}" -f $r.Status, $r.Part) -ForegroundColor $colour
    if ($r.Fix) { Write-Host "          $($r.Fix)" }
}
$bad = @($results | Where-Object { $_.Status -eq "FAILED" -or $_.Status -eq "SKIPPED" })
if ($bad.Count -eq 0) {
    Write-Host "`nAll set. Double-click 'Start UNN Voting' on the desktop to run the site." -ForegroundColor Green
} else {
    Write-Host "`n$($bad.Count) part(s) need attention (see above). Fix them and run install.bat again;" -ForegroundColor Red
    Write-Host "the parts that already worked are quick the second time."
}
Write-Host "A full copy of this window is saved in: $logFile"
try { Stop-Transcript | Out-Null } catch {}
