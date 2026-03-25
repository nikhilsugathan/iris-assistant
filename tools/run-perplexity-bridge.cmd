@echo off
set SCRIPT_DIR=%~dp0
powershell -NoLogo -ExecutionPolicy Bypass -File "%SCRIPT_DIR%run-perplexity-bridge.ps1" %*
