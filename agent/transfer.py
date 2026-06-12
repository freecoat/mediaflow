"""agent/transfer.py — F5: esecuzione transfer Aspera (ascp) dall'agent.

Nessun import da app.*: il codice gira in facility, senza accesso al server.
Credenziali SOLO da env (ASPERA_SSH_KEY_PATH, ASPERA_EXTRA_ARGS).
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from typing import Optional


def build_ascp_cmd(
    files_abs: list[str],
    destination: str,
    *,
    key_path: Optional[str] = None,
    extra_args: Optional[list[str]] = None,
) -> list[str]:
    """Costruisce la lista argv per ascp (puro, testabile).

    Args:
        files_abs: path assoluti sorgenti (già risolti, già guardati da traversal).
        destination: destinazione formato ascp (user@host:/path).
        key_path: path alla chiave SSH privata (opzionale).
        extra_args: argomenti extra passati dopo la chiave (opzionali).

    Returns:
        Lista stringhe argv pronta per subprocess.
    """
    cmd: list[str] = ["ascp"]
    if key_path:
        cmd += ["-i", key_path]
    if extra_args:
        cmd += extra_args
    cmd += ["-d"]
    cmd += files_abs
    cmd += [destination]
    return cmd


def run_transfer(payload: dict, volumes_by_id: dict) -> dict:
    """Esegue il transfer Aspera per i file nel payload.

    Args:
        payload: dict con chiavi {"files": [{volume_id, rel_path}, ...],
                 "destination": str, "extra_args": list opzionale}.
        volumes_by_id: mappa {volume_id (int) -> {"mount_path": str, ...}}.

    Returns:
        {"ok": True, "files": N, "log_tail": str}

    Raises:
        RuntimeError: ascp non trovato nel PATH, o rc != 0.
        ValueError: volume_id sconosciuto, o path fuori dal volume (traversal).
        FileNotFoundError: file sorgente non trovato sul disco.
    """
    # Guard binario: ascp presente nel PATH?
    if not shutil.which("ascp"):
        raise RuntimeError(
            "ascp non trovato nel PATH — Aspera CLI non installata su questo agent. "
            "Installare IBM Aspera Connect o Aspera CLI e riprovare."
        )

    destination = payload.get("destination") or ""
    files_spec: list[dict] = payload.get("files") or []
    extra_args_raw: list = payload.get("extra_args") or []

    # Risoluzione path assoluti + guard traversal per ogni file
    files_abs: list[str] = []
    for spec in files_spec:
        vid = int(spec.get("volume_id") or 0)
        vol = volumes_by_id.get(vid)
        if vol is None:
            raise ValueError(
                f"volume_id {vid!r} sconosciuto all'agent — "
                "controllare la configurazione dei volumi."
            )
        rel = (spec.get("rel_path") or "").strip().strip("/\\")
        base = os.path.realpath(vol["mount_path"])
        full = os.path.realpath(os.path.join(base, rel)) if rel else base
        # Guard traversal (stesso pattern di agent/browse.py)
        if full != base and not full.startswith(base + os.sep):
            raise ValueError(
                f"percorso fuori dal volume: {spec.get('rel_path')!r} "
                f"(volume mount_path={vol['mount_path']!r})"
            )
        if not os.path.isfile(full):
            raise FileNotFoundError(
                f"file non trovato: {full!r} "
                f"(rel_path={spec.get('rel_path')!r}, volume={vid})"
            )
        files_abs.append(full)

    # Credenziali da env — mai nel payload
    key_path: Optional[str] = os.environ.get("ASPERA_SSH_KEY_PATH") or None
    extra_env_raw: str = os.environ.get("ASPERA_EXTRA_ARGS") or ""
    extra_args: list[str] = list(extra_args_raw)
    if extra_env_raw.strip():
        extra_args = shlex.split(extra_env_raw) + extra_args

    cmd = build_ascp_cmd(files_abs, destination, key_path=key_path, extra_args=extra_args or None)

    proc = subprocess.run(
        cmd,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=43200,  # 12 ore
    )

    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    log_tail = combined.strip()[-800:] if combined.strip() else ""

    if proc.returncode != 0:
        raise RuntimeError(
            f"ascp rc={proc.returncode}: {(proc.stderr or '')[-800:]}"
        )

    bytes_total = 0
    for f in files_abs:
        try:
            bytes_total += os.path.getsize(f)
        except OSError:
            pass  # file sparito post-transfer: la size manca, l'esito resta ok

    return {
        "ok": True,
        "files": len(files_abs),
        "bytes_total": bytes_total,
        "log_tail": log_tail,
    }
