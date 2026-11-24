@echo off
rem Double-click once on a new laptop: installs everything the voting site needs.
rem Each part runs on its own; a summary at the end says what to fix, if anything.
if not exist "%~dp0install.ps1" goto notextracted
if not exist "%~dp0common.ps1" goto notextracted
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
echo.
echo The window stays open so you can read the summary. A copy is in defence\install-log.txt
pause
exit /b

:notextracted
echo.
echo This was opened from inside the zip file, so the installer cannot find its other files.
echo Close this window, right-click the downloaded zip, choose "Extract All",
echo then open the extracted folder and double-click defence\install.bat there.
echo.
pause
