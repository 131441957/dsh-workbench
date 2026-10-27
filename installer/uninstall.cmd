@echo off
rem Double-click entry: run the PowerShell uninstaller (Chinese text lives in the .ps1,
rem this file stays pure ASCII so cmd can never mangle it).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -NoExit -File "%~dp0uninstall.ps1"
