"""v3.5.0-alpha.71 — Parser AI per fattura passiva da PDF/docx/xlsx.

Estrae i campi chiave (supplier_name, vat_number, number, issue_date,
amount_net, vat_rate, amount_total, due_date) da un file di fattura
ricevuto via upload. Usa l'AI provider configurato.

Limite noto: solo testo. Per fatture scansionate (immagini) serve OCR
(tesseract o cloud). Scope futuro.
"""
from __future__ import annotations
import logging
from typing import Optional

from app.services.ai_provider import get_provider, safe_json_parse

logger = logging.getLogger(__name__)


PARSE_INVOICE_SYSTEM_PROMPT = """Sei un assistente esperto in fatturazione italiana / europea.

Compito: leggere il testo di una fattura ricevuta da un fornitore (es. fattura
elettronica italiana, FatturaPA, fattura europea, fattura semplificata) ed
estrarre i campi chiave in JSON strutturato.

Schema output:
{
  "supplier_name": "ragione sociale fornitore (cedente/prestatore)",
  "supplier_vat_number": "P.IVA fornitore (es. IT12345678901)",
  "supplier_tax_code": "Codice Fiscale fornitore (se diverso da P.IVA)",
  "supplier_address": "indirizzo completo (opzionale)",
  "supplier_iban": "IBAN per bonifico (opzionale)",
  "supplier_email": "email contatto (opzionale)",
  "number": "numero fattura (es. '2026/001', 'FT-12-2026')",
  "issue_date": "data emissione YYYY-MM-DD",
  "due_date": "data scadenza YYYY-MM-DD (opzionale)",
  "currency": "EUR/USD/GBP (default EUR)",
  "amount_net": 1000.00,
  "vat_rate": 22.0,
  "amount_vat": 220.00,
  "amount_total": 1220.00,
  "description": "descrizione lavorazione (riassunto in 1 riga)",
  "payment_terms_days": 30,
  "confidence": "high/medium/low",
  "notes": "eventuali dubbi o info mancanti"
}

REGOLE:
- Identificare il CEDENTE (chi ha emesso la fattura) come supplier — NON il
  cessionario (chi la riceve).
- Date sempre in formato YYYY-MM-DD.
- Importi come numeri (no simboli valuta nel valore).
- Se un campo non è chiaramente presente, omettilo (non inventare valori).
- supplier_name è OBBLIGATORIO. Se non identificabile, ritorna confidence=low + notes.
"""


def parse_supplier_invoice(text: str, user_id: Optional[int] = None,
                           db=None) -> Optional[dict]:
    """Analizza testo fattura. Ritorna dict con campi estratti."""
    if user_id is not None and db is not None:
        from app.services.ai_provider import get_provider_for_user
        provider = get_provider_for_user(user_id, db)
    else:
        provider = get_provider()
    if not provider:
        logger.warning("AI provider non disponibile — parse_supplier_invoice disabilitato")
        return None
    if not text or len(text.strip()) < 30:
        return None
    MAX = 20000
    if len(text) > MAX:
        text = text[:MAX] + "\n\n[testo troncato]"
    user_prompt = f"Testo fattura da analizzare:\n\n---\n{text}\n---\n\nEstrai i campi."
    return provider.extract_json(PARSE_INVOICE_SYSTEM_PROMPT, user_prompt, max_tokens=2000)
