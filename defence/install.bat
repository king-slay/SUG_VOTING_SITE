@echo off
rem Double-click once on a new laptop: installs everything the voting site needs.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
pause
