@echo off
REM ═══════════════════════════════════════════════════════
REM  MediaFlow — Avvio "muto" (no browser auto)
REM  Stesso setup di avvia.bat ma NON apre nessuna pagina.
REM  Stop: CTRL+C nella finestra.
REM ═══════════════════════════════════════════════════════

title MediaFlow (muto)
cd /d "%~dp0"

REM Controllo Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERRORE] Python non trovato nel PATH.
    pause & exit /b 1
)

REM Crea venv se mancante
if not exist ".venv\" (
    echo [setup] Creo ambiente virtuale...
    python -m venv .venv
    if %errorlevel% neq 0 ( echo [ERRORE] venv KO & pause & exit /b 1 )
)

call .venv\Scripts\activate.bat

REM Aggiorna pip + deps in silent
python -m pip install --upgrade pip --quiet --disable-pip-version-check
pip install -r requirements.txt --quiet --disable-pip-version-check
if %errorlevel% neq 0 (
    echo [ERRORE] Installazione dipendenze fallita
    pause & exit /b 1
)

REM Seed DB se mancante
if not exist "mediaflow.db" (
    echo [setup] Inizializzo DB demo...
    python scripts\seed_demo.py
)

REM Cartelle upload
if not exist "uploads\assets\"     mkdir uploads\assets
if not exist "uploads\thumbnails\" mkdir uploads\thumbnails

echo.
echo ─────────────────────────────────────────────────────────────
echo  MediaFlow in ascolto su http://localhost:8000
echo  Browser NON aperto in automatico.
echo  Per esporlo via tunnel apri altra finestra e lancia:
echo      cloudflared tunnel --url http://localhost:8000
echo  Stop server: CTRL+C
echo ─────────────────────────────────────────────────────────────
echo.

REM ── Libera la porta 8000 da server zombie ─────────────────────
REM OneDrive rompe il file-watcher di uvicorn --reload: i restart manuali
REM accumulano processi che restano in LISTEN su :8000 (SO_REUSEADDR), e le
REM richieste finiscono su una vecchia versione del codice. Killa SOLO chi
REM ascolta su :8000 prima di avviare (non tocca altri python).
echo [setup] Libero la porta 8000 da eventuali server precedenti...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }"

python run.py
