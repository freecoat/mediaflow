"""Persistenza file capitolato sorgente + cleanup orphan.
Salva i documenti caricati per ri-analisi/audit; pulisce i file non
referenziati da alcun DeliveryTemplate. v3.5.0-alpha.172.228."""
import logging
import os
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

UPLOAD_DIR = Path("data/capitolato_uploads")
_ALLOWED_EXT = {".pdf", ".docx", ".doc", ".xlsx", ".txt"}


def save_capitolato_upload(file_bytes: bytes, filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in _ALLOWED_EXT:
        ext = ".bin"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_DIR / name
    dest.write_bytes(file_bytes)
    return f"data/capitolato_uploads/{name}"


def read_capitolato_text(rel_path: str) -> str:
    from app.services.deliverables_parser import extract_text_from_file
    p = Path(rel_path)
    if not p.exists():
        raise FileNotFoundError(rel_path)
    return extract_text_from_file(p.read_bytes(), p.name)


def sweep_capitolato_uploads(db, max_age_h: int = 24) -> int:
    """Elimina i file più vecchi di max_age_h non referenziati da template.
    Best-effort: errori loggati, non sollevati."""
    from app.models.models import DeliveryTemplate
    if not UPLOAD_DIR.exists():
        return 0
    try:
        referenced = {
            r[0] for r in db.query(DeliveryTemplate.source_document_path)
            .execution_options(include_deleted=True)
            .filter(DeliveryTemplate.source_document_path.isnot(None)).all()
        }
    except Exception as e:
        logger.warning(f"sweep: query referenced fallita: {e}")
        referenced = set()
    cutoff = time.time() - max_age_h * 3600
    removed = 0
    for f in UPLOAD_DIR.iterdir():
        if not f.is_file():
            continue
        rel = f"data/capitolato_uploads/{f.name}"
        if rel in referenced:
            continue
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except OSError as e:
            logger.warning(f"sweep: unlink {f} fallito: {e}")
    return removed
