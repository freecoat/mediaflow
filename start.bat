@echo off
REM ═══════════════════════════════════════════════════════
REM  Claqo — avvio rapido (usa il .venv esistente)
REM  Doppio clic. Presuppone .venv + mediaflow.db già creati.
REM ═══════════════════════════════════════════════════════
title Claqo
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERRORE] .venv non trovato. Esegui prima avvia.bat una volta.
    pause
    exit /b 1
)

echo  Avvio Claqo su http://localhost:8000
echo  (CTRL+C per fermare)
echo.
start "" /b cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:8000"

".venv\Scripts\python.exe" run.py

pause
