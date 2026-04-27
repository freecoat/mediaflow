"""
MediaFlow — Deliverables Parser
Estrae voci di capitolato da PDF / Word / Excel / testo libero
e le matcha con il listino prezzi tramite AI.
"""
from __future__ import annotations
import io, json, logging
from pathlib import Path
from typing import Optional
from app.services.ai_provider import get_provider

logger = logging.getLogger(__name__)


# ── Estrazione testo dai vari formati ───────────────────────

def extract_text_from_pdf(file_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as e:
        logger.error(f"PDF extraction failed: {e}")
        return ""


def extract_text_from_docx(file_bytes: bytes) -> str:
    try:
        from docx import Document
        doc = Document(io.BytesIO(file_bytes))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        # Estrai anche contenuto tabelle
        for table in doc.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    paragraphs.append(" | ".join(cells))
        return "\n".join(paragraphs)
    except Exception as e:
        logger.error(f"DOCX extraction failed: {e}")
        return ""


def extract_text_from_xlsx(file_bytes: bytes) -> str:
    try:
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(file_bytes), data_only=True, read_only=True)
        rows_text = []
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            rows_text.append(f"=== Foglio: {sheet_name} ===")
            for row in ws.iter_rows(values_only=True):
                cells = [str(c) for c in row if c is not None]
                if cells:
                    rows_text.append(" | ".join(cells))
        return "\n".join(rows_text)
    except Exception as e:
        logger.error(f"XLSX extraction failed: {e}")
        return ""


def extract_text_from_file(file_bytes: bytes, filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return extract_text_from_pdf(file_bytes)
    elif ext in (".docx", ".doc"):
        return extract_text_from_docx(file_bytes)
    elif ext in (".xlsx", ".xls"):
        return extract_text_from_xlsx(file_bytes)
    elif ext in (".txt", ".md"):
        try:
            return file_bytes.decode("utf-8", errors="ignore")
        except Exception:
            return ""
    return ""


# ── Prompt per parsing capitolato ───────────────────────────

PARSE_SYSTEM_PROMPT = """Sei un assistente esperto in postproduzione audiovisiva (cinema, TV, pubblicità).

Il tuo compito: analizzare un capitolato di consegne di un cliente e tradurlo in un elenco strutturato di voci operative.

Per ogni consegna/lavorazione richiesta, estrai:
- description: descrizione tecnica breve (es. "DCP 4K Mastering VF")
- detail: eventuale dettaglio aggiuntivo (es. "incl. QC e subtitling")
- quantity: quantità numerica (es. 1, 2, 90)
- unit: unità di misura (day/hr/min/pc/week/TB/GB/m/allow)
- category: categoria di postproduzione (PICTURE/SOUND/VFX/MASTERING/DELIVERABLES DCI/DELIVERABLES SOUND/DAILIES/ARCHIVE/TRANSFER/MATERIALS)
- section: sezione suggerita per raggruppamento in preventivo (A=Mastering/Delivery, B=Picture/Grading, C=Sound, D=VFX, E=Archive/Transfer)
- confidence: tuo livello di confidenza (high/medium/low)
- notes: eventuali ambiguità o info mancanti che l'utente deve verificare

Se il capitolato menziona durata del prodotto (es. "film 90 minuti"), usala per calcolare quantità per le voci "per min" (es. H264 encoding).

Se il capitolato è vago, fai ipotesi ragionevoli ma indica confidence:"low" e spiega in notes.

Schema output:
{
  "project_info": {
    "title": "...",
    "client": "...",
    "length_minutes": 90,
    "fps": "24",
    "delivery_format": "4K DCI",
    "shooting_format": "ARRI Alexa",
    "delivery_deadline": "2024-12-31"
  },
  "deliverables": [
    {
      "description": "4K DCP Mastering VF",
      "detail": "incl. full QC - EN Version",
      "quantity": 1,
      "unit": "pc",
      "category": "MASTERING",
      "section": "A",
      "confidence": "high",
      "notes": null
    },
    ...
  ],
  "global_notes": "Note generali sul capitolato nel suo insieme"
}"""


def parse_deliverables(text: str, hint: Optional[str] = None) -> Optional[dict]:
    """
    Analizza un capitolato e restituisce la struttura voci + info progetto.
    hint: testo addizionale dell'utente (es. "è un documentario da 52 minuti").
    """
    provider = get_provider()
    if not provider:
        logger.warning("AI provider non disponibile — parser disabilitato")
        return None

    if len(text.strip()) < 20:
        logger.warning("Testo troppo breve per il parsing")
        return None

    # Limita lunghezza testo per non saturare il context
    MAX_CHARS = 30000
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n\n[... testo troncato ...]"

    user_prompt = f"""Capitolato da analizzare:

---
{text}
---
"""
    if hint:
        user_prompt += f"\nInfo aggiuntiva dall'utente: {hint}\n"

    result = provider.extract_json(PARSE_SYSTEM_PROMPT, user_prompt, max_tokens=6000)
    return result


# ── Matching voci capitolato ↔ listino prezzi ───────────────

MATCH_SYSTEM_PROMPT = """Sei un assistente che mappa voci di capitolato di un cliente sul listino prezzi interno della casa di postproduzione.

Dato un elenco di voci da capitolato e un listino prezzi, per ogni voce del capitolato:
1. Trova la voce di listino più simile (se esiste)
2. Restituisci l'id del match migliore, oppure null se nessuna voce è abbinabile
3. Indica il livello di confidenza del match

Criteri di matching:
- Terminologia tecnica (DCP, DCDM, ProRes, H264, grading, mix, conform, etc.)
- Unità di misura compatibile (day/min/pc)
- Categoria coerente (SOUND→SOUND, PICTURE→PICTURE)

Schema output:
{
  "matches": [
    {
      "deliverable_index": 0,
      "price_item_id": 42,
      "confidence": "high",
      "reasoning": "Match esatto: '4K DCP Mastering' = listino #42 '4K DCP Mastering VF'"
    },
    ...
  ]
}

Se una voce non ha corrispondenza chiara nel listino, imposta price_item_id: null e spiega in reasoning."""


def match_deliverables_to_pricelist(deliverables: list[dict],
                                     pricelist: list[dict]) -> Optional[dict]:
    """
    Matcha le voci di capitolato con le voci del listino.
    deliverables: output di parse_deliverables['deliverables']
    pricelist: lista voci dal DB con campi id, name, category, unit, price_list
    """
    provider = get_provider()
    if not provider:
        return None

    deliverables_text = json.dumps(
        [{"index": i, **d} for i, d in enumerate(deliverables)],
        ensure_ascii=False, indent=2)
    pricelist_text = json.dumps(
        [{"id": p["id"], "name": p["name"], "category": p.get("category"),
          "unit": p["unit"], "price_list": p.get("price_list")} for p in pricelist],
        ensure_ascii=False, indent=2)

    user_prompt = f"""Voci capitolato da matchare:
{deliverables_text}

Listino prezzi disponibile:
{pricelist_text}

Genera le mappature."""

    result = provider.extract_json(MATCH_SYSTEM_PROMPT, user_prompt, max_tokens=4000)
    return result
