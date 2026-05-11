"""
MediaFlow — AI legacy parser markdown action (v3.5.0-alpha.66.17.1)

Estratto da ai_assistant.py (sprint R6 dell'audit). Path legacy per
provider che NON supportano tool_use nativo (Ollama/Perplexity):
l'AI risponde in markdown e i blocchi action vengono estratti via regex
+ balanced-brace parser.

Per provider con tool_use nativo (Claude/OpenAI/Gemini) questo path
NON viene usato: ai_loop.advance_loop gestisce tool_use direttamente.

Il parser e' lenient: accetta 3 formati che i modelli piccoli emettono
(
action
..., action
...) e usa safe_json_parse
(che tollera commenti // e trailing commas — vedi memoria
feedback_ai_json_lenient).

VALID_ACTION_TYPES qui SOLO per validation del path legacy. Il vero
registry handler vive in ai_assistant._ACTION_HANDLERS. Drift noto
documentato in audit (R6.2 follow-up: derivare automaticamente).
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from app.services.ai_provider import safe_json_parse

logger = logging.getLogger(__name__)


# ── Estrazione azioni proposte ───────────────────────────────

VALID_ACTION_TYPES = {
    "propose_client",
    "propose_project",
    "propose_project_metadata",
    "propose_quote",
    "propose_quote_line",
    "propose_price_item",
    "propose_new_item_and_line",
    "propose_resource",
    "propose_booking",
    # v3.5.0-alpha.50 — Planning operations (move/resize/delete su booking esistenti)
    "propose_move_booking",
    "propose_resize_booking",
    "propose_delete_booking",
    # v3.5.0-alpha.68.5 — Supplier / fatture passive
    "propose_supplier",
    "propose_supplier_invoice",
    # v3.5.0-alpha.69 — Capitolati template → quote
    "propose_quote_from_template",
    # v3.5.0-alpha.71 — Query supplier/fatture passive
    "query_suppliers",
    "query_supplier_invoices",
    # v3.5.0-alpha.76 — Asset/inventory
    "query_physical_assets",
    "query_asset_contents",
    "propose_asset_movement",
    "web_search",
}


def _balanced_json_at(text: str, start: int) -> tuple[Optional[str], int]:
    """
    Estrae un blocco JSON balanced partendo da text[start] (deve essere `{`).
    Ritorna (json_str, end_index_after_closing_brace) oppure (None, start).
    """
    if start >= len(text) or text[start] != "{":
        return None, start
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False; continue
        if ch == "\\":
            escape = True; continue
        if ch == '"':
            in_string = not in_string; continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1], i + 1
    return None, start


def extract_proposed_actions(reply_text: str) -> tuple[str, list[dict]]:
    """
    Estrae i blocchi azione dalla risposta dell'AI. Tollera tre formati che
    i modelli piccoli (Llama 8B, Qwen 7B) emettono con frequenza:

      1. ```action\n{...}\n```    (canonica)
      2. ```\naction\n{...}\n```  (action su riga successiva)
      3. action\n{...}            (senza code fence)

    Usa parsing balanced delle parentesi così supporta JSON annidato.
    Ritorna (testo_ripulito, [azioni_valide]).
    """
    if not reply_text:
        return "", []

    actions: list[dict] = []
    text = reply_text

    # Trova tutti i punti di partenza dei blocchi action e estraili in ordine
    # Pattern 1+2: tre apici opzionali + parola action + JSON balanced
    # Pattern 3: solo parola action a inizio linea + JSON balanced
    fence_pat = re.compile(
        r"(```)?\s*\n?\s*action\s*\n", re.IGNORECASE)

    # Iteriamo finché troviamo "action\n{"
    pos = 0
    spans_to_strip: list[tuple[int, int]] = []
    while True:
        m = fence_pat.search(text, pos)
        if not m:
            break
        # cerca la prima `{` subito dopo il match
        brace_idx = text.find("{", m.end() - 1)
        if brace_idx < 0 or brace_idx > m.end() + 5:
            pos = m.end()
            continue
        payload, after = _balanced_json_at(text, brace_idx)
        if not payload:
            pos = m.end()
            continue
        parsed = safe_json_parse(payload)
        if not parsed:
            logger.warning(
                "Blocco action trovato ma JSON non parsabile (probabilmente "
                "contiene commenti o virgole finali). Primi 200 char: %r",
                payload[:200],
            )
            pos = after
            continue
        if parsed.get("type") not in VALID_ACTION_TYPES:
            logger.warning(
                "Blocco action con type non riconosciuto: %r (validi: %s)",
                parsed.get("type"), sorted(VALID_ACTION_TYPES),
            )
            pos = after
            continue
        actions.append(parsed)
        # estendi span per togliere anche eventuali ``` di chiusura
        end = after
        tail = text[end:end + 8]
        m2 = re.match(r"\s*```", tail)
        if m2:
            end += m2.end()
        spans_to_strip.append((m.start(), end))
        pos = end

    # Rimuovi gli span (in ordine inverso per non shiftare gli indici)
    for s, e in reversed(spans_to_strip):
        text = text[:s] + text[e:]

    cleaned = re.sub(r"\n{3,}", "\n\n", text).strip()
    return cleaned, actions

