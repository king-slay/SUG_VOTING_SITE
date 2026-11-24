@echo off
rem Runs a Django management command with the installed Python, for example:
rem   defence\manage.bat createsuperuser
rem   defence\manage.bat changepassword chair
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0manage.ps1" %*
