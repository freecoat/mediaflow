"""v3.5.0-alpha.172.128 — Estrazione head-specs (TC/timeline/audio-config) dai
capitolati. PDF → vision (PyMuPDF page images); docx/xlsx/txt → testo.
"""
from __future__ import annotations
import base64
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


# ── Taxonomy + prompt ──────────────────────────────────────────────────────

from app.models.models import (  # noqa: E402  (post-function import per evitare cicli)
    AudioChannelConfig, AudioMixType, MixStandard, AudioCodec,
)

_SYS_PROMPT = (
    "Sei un estrattore tecnico di capitolati di post-produzione audiovisiva. "
    "Estrai SOLO: testa/coda del file (barre, toni, slate, counter, nero, loghi, "
    "titoli, code), timecode di partenza e di programma, e configurazione audio. "
    "I codici audio d'emittente (es. RAI 8T07, 16T09) mappano configurazioni "
    "standard tramite TABELLE con SIGLE spiegate in una LEGENDA: leggi sia la "
    "tabella sia la legenda e fai il cross-reference, espandendo ogni sigla. "
    "Mappa i termini ai NOMI CANONICI forniti quando possibile; se un termine non "
    "esiste fra i canonici, usalo grezzo ed elencalo in suggested_taxonomy. "
    "Timecode in formato HH:MM:SS:FF; se il documento da' prosa, estrai il TC e "
    "metti il resto in notes. Cio' che non riesci a strutturare va in source_notes. "
    "Rispondi SOLO con JSON valido, nessun altro testo."
)


def _taxonomy_vocab(db: Session, tenant_id: int) -> dict:
    """Nomi canonici attivi per il mapping (globali + del tenant)."""
    def names(Model):
        rows = db.query(Model.name).filter(
            (Model.tenant_id == tenant_id) | (Model.tenant_id.is_(None)),
            Model.is_active == True,  # noqa: E712
        ).all()
        return sorted({r[0] for r in rows})
    return {
        "channel_config": names(AudioChannelConfig),
        "mix_type": names(AudioMixType),
        "mix_standard": names(MixStandard),
        "codec": names(AudioCodec),
    }


def _parse_head_json(raw: str) -> dict:
    """Parsing tollerante (riusa safe_json_parse del progetto)."""
    from app.services.ai_provider import safe_json_parse
    try:
        out = safe_json_parse(raw)
        # safe_json_parse ritorna None su fallimento (non {})
        return out if isinstance(out, dict) else {}
    except Exception:
        return {}


def _user_prompt(broadcaster: str, vocab: dict, text: Optional[str] = None) -> str:
    schema = (
        '{"default_tc_start":"HH:MM:SS:FF|null","default_program_start":"HH:MM:SS:FF|null",'
        '"timeline_segments":[{"order":1,"kind":"bars_tone|slate|countdown|counter|black|program|textless|logo|main_titles|tail|other","label":"","tc_in":"","tc_out":"","duration":"","reel":null,"source":null,"notes":""}],'
        '"audio_config_codes":[{"code":"","name":"","description":"","tracks":[{"track_label":"","channel_config":"","mix_type":"","mix_standard":"","codec":"","sample_rate":48000,"bit_depth":24}]}],'
        '"suggested_taxonomy":[{"kind":"mix_type|channel_config|mix_standard|codec","name":"","seen_as":""}],'
        '"confidence":0.0,"source_notes":""}'
    )
    parts = [
        f"Capitolato: {broadcaster}.",
        "NOMI CANONICI taxonomy (mappa a questi quando possibile):",
        f"  channel_config: {vocab['channel_config']}",
        f"  mix_type: {vocab['mix_type']}",
        f"  mix_standard: {vocab['mix_standard']}",
        f"  codec: {vocab['codec']}",
        "Estrai ESATTAMENTE questo JSON (leggi tabelle audio riga-per-riga + legenda):",
        schema,
    ]
    if text is not None:
        parts.append("\nTESTO DOCUMENTO:\n" + text)
    return "\n".join(parts)


def extract_head_specs(provider, rendered: dict, broadcaster: str,
                       db: Session, tenant_id: int, max_tokens: int = 12000) -> dict:
    """Chiama l'LLM (vision o testo) e ritorna il dict del contratto. No write."""
    vocab = _taxonomy_vocab(db, tenant_id)
    if rendered.get("mode") == "vision":
        content = [{"type": "text", "text": _user_prompt(broadcaster, vocab)}]
        for png in rendered.get("images", []):
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",           # richiesto da ClaudeProvider._translate_blocks_to_openai
                    "media_type": "image/png",
                    "data": base64.b64encode(png).decode("ascii"),
                },
            })
        raw = provider.chat([{"role": "user", "content": content}],
                            system=_SYS_PROMPT, max_tokens=max_tokens, temperature=0.1)
    else:
        user = _user_prompt(broadcaster, vocab, text=(rendered.get("text") or "")[:120000])
        raw = provider.complete(_SYS_PROMPT, user, max_tokens=max_tokens, temperature=0.1)
    return _parse_head_json(raw)
