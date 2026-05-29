"""v3.5.0-alpha.172.128 — Estrazione head-specs (TC/timeline/audio-config) dai
capitolati. PDF → vision (PyMuPDF page images); docx/xlsx/txt → testo.
"""
from __future__ import annotations
import logging
from typing import Optional
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

PAGE_CAP = 60          # cap di sicurezza: oltre logga warning (no silent truncation)
RENDER_DPI = 150


def render_document_for_llm(file_bytes: bytes, filename: str) -> dict:
    """Rende un capitolato per il consumo LLM.
    PDF → {mode:'vision', images:[png bytes], page_count}. Altro → {mode:'text', text}.
    """
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    if ext == "pdf":
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        page_count = doc.page_count
        if page_count > PAGE_CAP:
            logger.warning(
                "[head-extractor] %s ha %d pagine (> cap %d): tutte renderizzate, costo vision elevato.",
                filename, page_count, PAGE_CAP,
            )
        zoom = RENDER_DPI / 72.0
        mat = fitz.Matrix(zoom, zoom)
        images = []
        try:
            for page in doc:
                pix = page.get_pixmap(matrix=mat)
                images.append(pix.tobytes("png"))
        finally:
            doc.close()  # no leak del doc handle anche su errore pixmap mid-loop
        return {"mode": "vision", "images": images, "page_count": page_count}
    try:
        from app.services.deliverables_parser import extract_text_from_file
        text = extract_text_from_file(file_bytes, filename)
    except Exception as e:
        logger.warning("[head-extractor] text extraction failed for %s: %s", filename, e)
        text = ""
    return {"mode": "text", "text": text or ""}
