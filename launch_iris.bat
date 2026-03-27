@echo off
title IRIS Agentic Core
cd /d D:\IRIS
echo [SYSTEM] Activating environment...
call .venv\Scripts\activate
echo [SYSTEM] Running IRIS Pre-flight Diagnostics...
:: This line runs the diagnostics silently before starting the main loop
python -c "from core.diagnostics import IRISDiagnostics; IRISDiagnostics().run_preflight()"
python main.py
pause