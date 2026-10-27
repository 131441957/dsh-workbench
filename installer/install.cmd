@echo off
rem Double-click entry: run the PowerShell installer (Chinese text is in the .ps1,
rem this file stays pure ASCII so cmd can never mangle it).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -NoExit -File "%~dp0install.ps1"
