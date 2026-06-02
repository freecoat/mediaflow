"""v3.5.0-alpha.172.164 — Utility SMPTE timecode (SMPTE 12M).

Formato: ``HH:MM:SS:FF`` (non-drop, separatore frame ``:``) oppure
``HH:MM:SS;FF`` (drop-frame, separatore frame ``;``). Drop-frame esiste SOLO
per le frequenze NTSC 29.97 / 59.94 fps: salta la numerazione dei frame 00 e 01
all'inizio di ogni minuto, tranne i minuti multipli di 10 — compensa la deriva
fra 30 fps nominali e i 29.97 reali (~3.6 s/ora). NESSUN frame video è perso:
si salta solo l'etichetta TC.

Riferimento: https://en.wikipedia.org/wiki/SMPTE_timecode + algoritmo classico
Heidelberger per la conversione drop-frame ↔ numero di frame.

Tutte le funzioni lavorano con fps NOMINALE (arrotondato all'intero: 23.976→24,
29.97→30, 59.94→60) per la dimensione dei campi; il drop-frame è gestito a parte.
"""
from __future__ import annotations
import re
from typing import Optional

# HH:MM:SS<sep>FF — separatori tollerati in input: : ; . , (frame sep distingue drop)
_TC_RE = re.compile(r"^\s*(\d{1,2})[:;.,](\d{1,2})[:;.,](\d{1,2})([:;.,])(\d{1,3})\s*$")


def nominal_fps(fps) -> int:
    """fps nominale intero usato per la dimensione del campo frame (29.97→30)."""
    try:
        return int(round(float(fps)))
    except (TypeError, ValueError):
        return 0


def _drop_per_min(nom: int) -> int:
    """Frame saltati per minuto in drop-frame: 2 @30fps, 4 @60fps."""
    return (nom // 30) * 2 if nom in (30, 60) else 0


def parse_tc(s) -> dict:
    """Parsa un TC → ``{hh,mm,ss,ff,drop}``. Solleva ValueError se malformato.

    ``drop`` è dedotto dal separatore frame (``;`` o ``.`` → drop-frame).
    NON valida i range (usa :func:`is_valid_tc`)."""
    if s is None:
        raise ValueError("timecode vuoto")
    m = _TC_RE.match(str(s))
    if not m:
        raise ValueError(f"timecode malformato: {s!r} (atteso HH:MM:SS:FF)")
    hh, mm, ss, sep, ff = m.groups()
    return {"hh": int(hh), "mm": int(mm), "ss": int(ss),
            "ff": int(ff), "drop": sep in (";", ".")}


def is_valid_tc(s, fps=None, drop: Optional[bool] = None) -> bool:
    """True se ``s`` è un TC ben formato e nei range. Se ``fps`` dato, valida
    anche FF < fps_nominale e (per drop-frame) i frame 00/01 saltati."""
    try:
        t = parse_tc(s)
    except ValueError:
        return False
    if not (0 <= t["hh"] <= 23):
        return False
    if not (0 <= t["mm"] <= 59):
        return False
    if not (0 <= t["ss"] <= 59):
        return False
    nom = nominal_fps(fps) if fps else 30
    if nom and not (0 <= t["ff"] < nom):
        return False
    eff_drop = t["drop"] if drop is None else drop
    if eff_drop and fps:
        dp = _drop_per_min(nominal_fps(fps))
        if dp and t["ss"] == 0 and (t["mm"] % 10) != 0 and t["ff"] < dp:
            return False  # frame "saltato" dal drop-frame → non esiste
    return True


def normalize_tc(s, fps=None, drop: Optional[bool] = None) -> Optional[str]:
    """Forma canonica zero-padded ``HH:MM:SS:FF`` (``;FF`` se drop-frame).
    None su input vuoto; solleva ValueError se malformato o fuori range."""
    if s in (None, ""):
        return None
    t = parse_tc(s)
    eff_drop = t["drop"] if drop is None else drop
    cand = f'{t["hh"]:02d}:{t["mm"]:02d}:{t["ss"]:02d}{";" if eff_drop else ":"}{t["ff"]:02d}'
    if not is_valid_tc(cand, fps=fps, drop=eff_drop):
        raise ValueError(
            f"timecode fuori range: {s!r} "
            f"(HH 00-23, MM/SS 00-59, FF 00-{(nominal_fps(fps)-1) if fps else 29})"
        )
    return cand


def tc_to_frames(s, fps, drop: Optional[bool] = None) -> int:
    """Numero totale di frame dall'inizio (00:00:00:00). fps reale o nominale."""
    t = parse_tc(s)
    nom = nominal_fps(fps)
    eff_drop = t["drop"] if drop is None else drop
    base = ((t["hh"] * 3600 + t["mm"] * 60 + t["ss"]) * nom) + t["ff"]
    dp = _drop_per_min(nom) if eff_drop else 0
    if dp:
        total_min = t["hh"] * 60 + t["mm"]
        base -= dp * (total_min - (total_min // 10))
    return base


def frames_to_tc(n: int, fps, drop: bool = False) -> str:
    """Converte un numero di frame in TC. Wrappa a 24h."""
    nom = nominal_fps(fps)
    if nom <= 0:
        raise ValueError("fps non valido")
    sep = ":"
    if drop and nom in (30, 60):
        dp = _drop_per_min(nom)
        frames_per_10m = nom * 600 - dp * 9
        frames_per_min = nom * 60
        n %= (nom * 3600 * 24)
        d, m = divmod(n, frames_per_10m)
        if m > dp:
            n += dp * 9 * d + dp * ((m - dp) // (frames_per_min - dp))
        else:
            n += dp * 9 * d
        sep = ";"
    fr = n % nom
    secs = n // nom
    return f"{(secs // 3600) % 24:02d}:{(secs // 60) % 60:02d}:{secs % 60:02d}{sep}{fr:02d}"


def add_frames(s, n: int, fps, drop: Optional[bool] = None) -> str:
    """Somma ``n`` frame (anche negativi) a un TC, rispettando drop-frame."""
    t = parse_tc(s)
    eff_drop = t["drop"] if drop is None else drop
    return frames_to_tc(tc_to_frames(s, fps, eff_drop) + n, fps, eff_drop)


def coerce_tc(value, fps=None, drop: Optional[bool] = None, field: str = "timecode") -> Optional[str]:
    """Validatore per i router: '' / None → None; valore valido → normalizzato;
    malformato/fuori-range → ValueError con nome campo (il router lo mappa a 422)."""
    if value is None:
        return None
    v = str(value).strip()
    if v == "":
        return None
    try:
        return normalize_tc(v, fps=fps, drop=drop)
    except ValueError as e:
        raise ValueError(f"{field}: {e}")

