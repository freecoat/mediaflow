"""app/services/contact_extract.py — Client email F3.

Estrazione contatti da thread email: ibrido deterministico (nessuna
dipendenza AI, regex su header From/To/Cc + euristiche sul blocco firma)
+ arricchimento AI opzionale (enrich_with_ai), chiamato solo su richiesta
esplicita utente. Best-effort, mai eccezione al chiamante."""
from __future__ import annotations

import json
import re
from typing import Optional

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?<!\d)(\+?\d[\d\s\-.]{7,}\d)(?!\d)")
_COMPANY_HINTS = ("srl", "s.r.l", "spa", "s.p.a", "ltd", "llc", "gmbh", "inc", "sas", "snc")
_QUOTE_MARKERS = ("ha scritto:", "wrote:")


def _parse_address(raw: str) -> Optional[dict]:
    """'Display Name <addr@x.com>' o 'addr@x.com' -> {name, email}. None se
    non contiene un indirizzo valido."""
    raw = (raw or "").strip()
    if not raw:
        return None
    m = re.match(r'^"?([^"<]*)"?\s*<([^<>]+)>$', raw)
    if m:
        name = m.group(1).strip()
        email = m.group(2).strip()
    else:
        email_m = EMAIL_RE.search(raw)
        if not email_m:
            return None
        email = email_m.group(0)
        name = raw[: email_m.start()].strip(' "<')
    if not EMAIL_RE.fullmatch(email):
        return None
    return {"name": name or email.split("@")[0], "email": email.lower()}


def _participants(thread: dict) -> list[dict]:
    seen: dict[str, dict] = {}
    for msg in thread.get("messages") or []:
        for field in ("from", "to", "cc"):
            raw = msg.get(field) or ""
            for part in raw.split(","):
                cand = _parse_address(part)
                if cand and cand["email"] not in seen:
                    seen[cand["email"]] = cand
    return list(seen.values())


def _signature_block(text: str) -> list[str]:
    """Ultime righe non vuote del corpo, tagliate alla prima riga di
    citazione (euristica firma dell'ultimo messaggio)."""
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    cut = len(lines)
    for i, l in enumerate(lines):
        low = l.lower()
        if l.startswith(">") or any(marker in low for marker in _QUOTE_MARKERS):
            cut = i
            break
    return lines[:cut][-8:]


def _extract_signature_fields(lines: list[str]) -> dict:
    """Euristica firma: telefono/azienda per pattern, ruolo per posizione.
    Le firme seguono la convenzione Nome / Ruolo / Azienda / recapiti: le
    righe di 'testo' (non frase, non azienda, non recapito) sono nome poi
    ruolo, quindi il ruolo è la 2ª riga di testo."""
    out: dict = {}
    text_lines: list[str] = []
    for l in lines:
        if "phone" not in out:
            pm = PHONE_RE.search(l)
            if pm and sum(ch.isdigit() for ch in pm.group(1)) >= 8:
                out["phone"] = pm.group(1).strip()
                continue
        low = l.lower()
        if any(h in low for h in _COMPANY_HINTS):
            if "company_text" not in out:
                out["company_text"] = l
            continue
        if EMAIL_RE.search(l) or PHONE_RE.search(l):
            continue
        # righe-frase (contengono virgola o finiscono con punteggiatura) non
        # sono nome/ruolo → scartate
        if "," in l or l.rstrip().endswith((".", "!", "?", ":")):
            continue
        if 1 <= len(l.split()) <= 6:
            text_lines.append(l)
    if len(text_lines) >= 2:  # [nome, ruolo, ...]
        out["role"] = text_lines[1]
    return out


def extract_from_thread(thread: dict) -> list[dict]:
    """Ritorna candidati deterministici: partecipanti (From/To/Cc) arricchiti
    con phone/role/company_text euristici dal blocco firma dell'ultimo
    messaggio con corpo testuale. Dedup per email."""
    candidates = _participants(thread or {})
    if not candidates:
        return []
    sig_fields: dict = {}
    for msg in reversed((thread or {}).get("messages") or []):
        body = msg.get("body_text") or ""
        if body.strip():
            sig_fields = _extract_signature_fields(_signature_block(body))
            break
    for c in candidates:
        c["phone"] = sig_fields.get("phone")
        c["role"] = sig_fields.get("role")
        c["company_text"] = sig_fields.get("company_text")
        c["source"] = "email"
    return candidates


def enrich_with_ai(candidate: dict, signature_text: str, provider) -> dict:
    """Arricchisce role/company_text dalla firma via LLM. Best-effort:
    provider assente/errore -> candidato invariato. Non alza mai eccezioni."""
    if not provider or not signature_text:
        return candidate
    prompt = (
        "Estrai da questa firma email SOLO ruolo e azienda della persona, "
        'in JSON: {"role": str|null, "company_text": str|null}. '
        f"Nome noto: {candidate.get('name')}. Firma:\n{signature_text}"
    )
    try:
        raw = provider.complete(
            "Sei un estrattore di dati strutturati. Rispondi SOLO con JSON valido.",
            prompt, max_tokens=200, temperature=0,
        )
        data = json.loads((raw or "").strip().strip("`"))
        out = dict(candidate)
        if data.get("role"):
            out["role"] = data["role"]
        if data.get("company_text"):
            out["company_text"] = data["company_text"]
        return out
    except Exception:
        return candidate
