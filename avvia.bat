@echo off
REM ═══════════════════════════════════════════════════════
REM  MediaFlow — Installazione e avvio su Windows
REM  Doppio clic su questo file per installare e avviare
REM ═══════════════════════════════════════════════════════

title MediaFlow Setup

echo.
echo  ███╗   ███╗███████╗██████╗ ██╗ █████╗ ███████╗██╗      ██████╗ ██╗    ██╗
echo  ████╗ ████║██╔════╝██╔══██╗██║██╔══██╗██╔════╝██║     ██╔═══██╗██║    ██║
echo  ██╔████╔██║█████╗  ██║  ██║██║███████║█████╗  ██║     ██║   ██║██║ █╗ ██║
echo  ██║╚██╔╝██║██╔══╝  ██║  ██║██║██╔══██║██╔══╝  ██║     ██║   ██║██║███╗██║
echo  ██║ ╚═╝ ██║███████╗██████╔╝██║██║  ██║██║     ███████╗╚██████╔╝╚███╔███╔╝
echo  ╚═╝     ╚═╝╚══════╝╚═════╝ ╚═╝╚═╝  ╚═╝╚═╝     ╚══════╝ ╚═════╝  ╚══╝╚══╝
echo.
echo  Piattaforma gestione risorse, pianificazione, finanza e DAM
echo  ─────────────────────────────────────────────────────────────
echo.

REM Controlla Python (preferisce il launcher "py", evita lo stub Microsoft Store)
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY (
    python --version >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo [ERRORE] Python non trovato.
    echo Scaricalo da: https://www.python.org/downloads/
    echo Assicurati di spuntare "Add Python to PATH" durante l'installazione.
    echo (Se Python e' gia' installato, potrebbe essere l'alias Microsoft Store:
    echo  disattivalo in Impostazioni ^> App ^> Alias di esecuzione app.)
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('%PY% --version 2^>^&1') do set PYVER=%%v
echo [OK] Python %PYVER% trovato (%PY%)

REM Crea venv se non esiste
if not exist ".venv\" (
    echo.
    echo [1/3] Creazione ambiente virtuale...
    %PY% -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERRORE] Impossibile creare l'ambiente virtuale
        pause & exit /b 1
    )
    echo [OK] Ambiente virtuale creato
) else (
    echo [OK] Ambiente virtuale già presente
)

REM Attiva venv
call .venv\Scripts\activate.bat

REM Aggiorna pip per evitare problemi di compatibilità wheel
python -m pip install --upgrade pip --quiet --disable-pip-version-check

REM Installa dipendenze
echo.
echo [2/3] Installazione dipendenze Python...
pip install -r requirements.txt --quiet --disable-pip-version-check
if %errorlevel% neq 0 (
    echo [ERRORE] Installazione dipendenze fallita
    pause & exit /b 1
)
echo [OK] Dipendenze installate

REM Seed database se non esiste
if not exist "mediaflow.db" (
    echo.
    echo [3/3] Inizializzazione database con dati demo...
    python scripts\seed_demo.py
    if %errorlevel% neq 0 (
        echo [ATTENZIONE] Seed fallito, il database verrà creato al primo avvio
    ) else (
        echo [OK] Database inizializzato
    )
) else (
    echo [OK] Database esistente trovato
)

REM Crea cartella uploads
if not exist "uploads\assets\" mkdir uploads\assets
if not exist "uploads\thumbnails\" mkdir uploads\thumbnails

echo.
echo ─────────────────────────────────────────────────────────────
echo  MediaFlow e' pronto!
echo.
echo  Credenziali demo:
echo    Admin  : admin@mediaflow.it  / admin123
echo    Editor : editor@mediaflow.it / editor123
echo.
echo  Apertura browser su http://localhost:8000 ...
echo  (premi CTRL+C nella finestra per fermare il server)
echo ─────────────────────────────────────────────────────────────
echo.

REM Apri browser dopo 2 secondi
start "" /b cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:8000"

REM Avvia server
python run.py

pause
