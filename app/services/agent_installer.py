"""Installer ZIP self-service per Claqo Agent (spec 2026-06-11).

Costruisce in-memory un pacchetto pronto-all'uso: sorgenti `agent/`,
config `claqo-agent.json` pre-compilata (server_url + token plain) e
script di avvio per Windows/Mac. Il token viene rigenerato dal chiamante
PRIMA di costruire lo zip: qui arriva già il plain da imbustare.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

ZIP_ROOT = "claqo-agent"

# Radice repo: app/services/agent_installer.py → parents[2]
_AGENT_SRC_DIR = Path(__file__).resolve().parents[2] / "agent"

_BAT = """@echo off\r
cd /d "%~dp0"\r
if not exist .venv ( py -3 -m venv .venv || python -m venv .venv )\r
.venv\\Scripts\\python -m pip install -r agent\\requirements.txt -q\r
.venv\\Scripts\\python -m agent.main\r
pause\r
"""

_COMMAND = """#!/bin/bash
cd "$(dirname "$0")"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
.venv/bin/python -m pip install -r agent/requirements.txt -q
exec .venv/bin/python -m agent.main
"""

_LEGGIMI = """CLAQO AGENT — installazione
===========================

Requisiti: Python 3.11+ sulla macchina della facility (con accesso alla SAN).
Per i metadati tecnici dei file media serve ffprobe (ffmpeg) nel PATH; senza,
l'agent funziona lo stesso ma le specifiche tecniche restano vuote.

Avvio
-----
* Windows: doppio click su avvia-agent.bat
* Mac:     doppio click su avvia-agent.command
           (se bloccato: tasto destro > Apri, oppure da Terminale:
            chmod +x avvia-agent.command && ./avvia-agent.command)

Al primo avvio crea un ambiente Python locale (.venv) e installa le due
dipendenze (requests, xxhash). Poi resta in esecuzione e dialoga col server.

Configurazione
--------------
claqo-agent.json contiene già l'indirizzo del server e il token di questo
agent. ATTENZIONE: il token è un segreto — non condividere questo pacchetto.
Ogni download dell'installer rigenera il token: il pacchetto scaricato prima
smette di autenticarsi.

Nessun contenuto media lascia la facility: l'agent manda al server solo
metadata JSON (nomi file, dimensioni, checksum, specifiche tecniche).
"""


def build_installer_zip(*, server_url: str, token_plain: str,
                        agent_name: str) -> bytes:
    """Ritorna i byte dello zip `claqo-agent/` pronto da scaricare."""
    cfg = {
        "server_url": server_url.rstrip("/"),
        "token": token_plain,
        "poll_seconds": 5,
        "heartbeat_seconds": 30,
        "agent_name": agent_name,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for src in sorted(_AGENT_SRC_DIR.iterdir()):
            if src.name == "__pycache__" or src.is_dir():
                continue
            zf.writestr(f"{ZIP_ROOT}/agent/{src.name}",
                        src.read_bytes())
        zf.writestr(f"{ZIP_ROOT}/claqo-agent.json",
                    json.dumps(cfg, indent=2, ensure_ascii=False))
        zf.writestr(f"{ZIP_ROOT}/avvia-agent.bat", _BAT)
        _write_executable(zf, f"{ZIP_ROOT}/avvia-agent.command", _COMMAND)
        zf.writestr(f"{ZIP_ROOT}/LEGGIMI.txt", _LEGGIMI)
    return buf.getvalue()


def _write_executable(zf: zipfile.ZipFile, arcname: str, content: str):
    """writestr con bit eseguibile Unix (0o755) per gli script .command."""
    info = zipfile.ZipInfo(arcname)
    info.external_attr = 0o755 << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    zf.writestr(info, content)
