@echo off
TITLE IRIS v4.8.3 [Aletheia] - Boot Sequence
COLOR 0B
cd /d "%~dp0"

echo ======================================================
echo   IRIS v4.8.3 : Aletheia Production Environment
echo ======================================================
echo.

:: 1. Model Warmup (GPU Optimization)
echo [1/3] Initializing RTX 5050 VRAM Tier...
powershell -ExecutionPolicy Bypass -File warmup.ps1

:: RANDOMIZED VOICE NOTIFICATION
powershell -Command "$acks = @('On it. Aletheia is online.', 'Checking... all systems nominal.', 'Right. I am ready.', 'One sec... and we are live.'); $pick = $acks | Get-Random; Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak($pick)"

:: 2. System Integrity Audit (Smoke Tests)
echo.
echo [2/3] Running 12-Module Integrity Audit...
python -c "from core.diagnostics import run_smoke_tests; [print(f'  [OK] {r.name}' if r.ok else f'  [FAIL] {r.name}: {r.message}') for r in run_smoke_tests()]"

:: --- NEW: VRAM MONITOR ---
:: Starts the real-time monitor in a separate small window
echo.
echo Starting Performance Monitor...
start /min cmd /c "title VRAM Monitor && python tools\vram_monitor.py"

:: 3. Core Engine Launch
echo.
echo [3/3] Launching Core Engine...
echo.
python main.py

echo.
echo [SYSTEM]: IRIS session terminated.
pause
