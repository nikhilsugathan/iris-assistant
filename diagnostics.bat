@echo off
title IRIS System Health Check
echo ======================================================
echo           IRIS PRODUCTION DIAGNOSTICS
echo ======================================================
echo.

set PYTHONPATH=.

echo [1/4] Checking Core Components ^& API Connectivity...
python -m tools.smoke_terminal_entry
echo.

echo [2/4] Testing Single Session Latency (Thinking Speed)...
python -m tools.smoke_single_session
echo.

echo [3/4] STARTING LIVE MIC TEST...
echo (Speak a few sentences to check word accuracy)
python -m tools.mic_check
echo.

echo [4/4] System Integrity Complete.
echo.
pause