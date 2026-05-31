"""Orologio centralizzato — v3.5.0-alpha.172.149.

`datetime.utcnow()` è deprecato (Python lo rimuoverà) e ritorna un datetime
NAIVE. Tutto il codebase confronta/persiste datetime naive (colonne SQLite
senza tzinfo, comparazioni naive-vs-naive). Per non cambiare semantica:

    now_utc() == datetime.now(timezone.utc).replace(tzinfo=None)

cioè l'ora UTC corrente SENZA tzinfo — identica a quanto restituiva
`datetime.utcnow()`, ma senza il warning di deprecazione e senza il rischio
di mischiare datetime aware/naive (che solleva TypeError in confronto).

Nessun import da `app.*`: usabile anche da `app.models.models` (default=...)
senza creare import circolari.
"""
from __future__ import annotations

from datetime import datetime, timezone


def now_utc() -> datetime:
    """Ora UTC corrente come datetime NAIVE (drop-in per datetime.utcnow())."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
