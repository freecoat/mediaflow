@echo off
REM ═══════════════════════════════════════════════════════
REM  MediaFlow — Tunnel cloudflared (ephemeral trycloudflare)
REM  Prerequisito: avvia_muto.bat (o avvia.bat) gia' in esecuzione
REM  Stop tunnel: CTRL+C
REM ═══════════════════════════════════════════════════════

title MediaFlow Tunnel
set CFD=%USERPROFILE%\cloudflared\cloudflared.exe

if not exist "%CFD%" (
    echo [ERRORE] cloudflared non trovato in %CFD%
    echo Scaricalo da: https://github.com/cloudflare/cloudflared/releases/latest
    pause & exit /b 1
)

echo.
echo ─────────────────────────────────────────────────────────────
echo  Avvio tunnel verso http://localhost:8000
echo  L'URL pubblico (trycloudflare.com) appare sotto.
echo  Stop: CTRL+C
echo ─────────────────────────────────────────────────────────────
echo.

"%CFD%" tunnel --url http://localhost:8000
