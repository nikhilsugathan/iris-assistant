@echo off
TITLE IRIS v5.2.5 - Boot Sequence
COLOR 0B
cd /d "%~dp0"

echo ======================================================
echo   IRIS v5.2.5 : Production Environment
echo ======================================================
echo.

if /I "%IRIS_USE_OLLAMA_WARMUP%"=="true" (
  echo [1/3] Optional Ollama model warmup...
  powershell -ExecutionPolicy Bypass -File warmup.ps1
) else (
  echo [1/3] Skipping optional Ollama warmup. Set IRIS_USE_OLLAMA_WARMUP=true to enable.
)

echo.
echo [2/3] Running lightweight integrity audit...
python -c "from core.diagnostics import run_smoke_tests; [print(f'  [OK] {r.name}' if r.ok else f'  [FAIL] {r.name}: {r.message}') for r in run_smoke_tests()]"

echo.
echo Starting Performance Monitor...
start /min cmd /c "title VRAM Monitor && python tools\vram_monitor.py"

echo.
echo [3/3] Launching Core Engine...
echo.
python main.py

echo.
echo [SYSTEM]: IRIS session terminated.
pause
