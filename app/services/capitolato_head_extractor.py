"""Estrazione head-specs (TC/timeline/audio-config) dai capitolati.

v3.5.0-alpha.172.133 — pipeline a CASCATA testo-prima:
  PDF con text-layer → PyMuPDF4LLM markdown (tabelle incluse), modalità TESTO,
    0 token-immagine, qualsiasi provider (anche DeepSeek);
  PDF scansione (text-layer assente) → fallback VISION (page images, solo Claude);
  docx/xlsx/txt → testo (deliverables_parser).
PoC RAI Spec 1.4: PyMuPDF4LLM = 28/28 audio config con tracce, ~100-300x più
economico della vision. Vision resta l'eccezione (es. BETA FILM scansione).
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
    PDF testo → {mode:'text', text:markdown, page_count, source:'pymupdf4llm'}.
    PDF scansione → {mode:'vision', images:[png bytes], page_count}.
    Altro (docx/xlsx/txt) → {mode:'text', text}.
    """
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    if ext == "pdf":
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        page_count = doc.page_count
        # α.172.133 — CASCATA testo-prima. La maggioranza dei capitolati PDF ha un
        # text-layer completo (RAI, MUBI, Sky, NBCU, IRDA): PyMuPDF4LLM ne estrae
        # markdown con tabelle (incl. le tabelle audio multi-canale) in modo
        # deterministico, 0 token-immagine, e usabile con QUALSIASI provider
        # (anche DeepSeek text-only). La vision (cara, solo Claude) resta il
        # fallback SOLO per i PDF scansione (text-layer assente, es. BETA FILM).
        # Detector scansione = raw text fitz (robusto: una scansione dà ~0 char,
        # mentre il markdown pymupdf4llm aggiunge placeholder immagine fuorvianti).
        raw_text_len = 0
        try:
            raw_text_len = sum(len(p.get_text().strip()) for p in doc)
        except Exception as e:
            logger.warning("[head-extractor] raw text probe KO %s: %s", filename, e)
        if raw_text_len >= max(300, 25 * page_count):
            try:
                import pymupdf4llm
                text_md = pymupdf4llm.to_markdown(doc) or ""
                doc.close()
                logger.info("[head-extractor] %s: text-layer ok (%d char) → modalità TESTO (pymupdf4llm)",
                            filename, raw_text_len)
                return {"mode": "text", "text": text_md, "page_count": page_count,
                        "source": "pymupdf4llm"}
            except Exception as e:
                logger.warning("[head-extractor] pymupdf4llm KO %s: %s → fallback vision", filename, e)
        else:
            logger.info("[head-extractor] %s: text-layer scarso (%d char, %d pagine) → fallback VISION (scansione?)",
                        filename, raw_text_len, page_count)
        # Fallback VISION: PDF scansione o estrazione testo fallita.
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
                       db: Session, tenant_id: int, max_tokens: int = 32000) -> dict:
    """Chiama l'LLM (vision o testo) e ritorna il dict del contratto. No write."""
    vocab = _taxonomy_vocab(db, tenant_id)
    if rendered.get("mode") == "vision":
        # Guard: un provider non-vision droppererebbe le immagini in silenzio.
        supports = getattr(provider, "supports_vision", None)
        if callable(supports) and not supports():
            raise ValueError(
                f"Il provider AI '{getattr(provider, 'name', '?')}' non supporta vision; "
                "serve un provider con vision (es. Claude) per i PDF."
            )
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
    parsed = _parse_head_json(raw)
    # v3.5.0-alpha.172.128 — pass di riconciliazione alias (M&E=IT mix=IT, ecc.)
    try:
        reconcile_taxonomy_aliases(provider, parsed, db, tenant_id)
    except Exception:
        pass
    return parsed


# ── apply_head_specs (Task 3) ─────────────────────────────────────────────────

import re as _re

_TC_RE = _re.compile(r"\b(\d{1,2}:\d{2}:\d{2}[:;.]\d{2})\b")


def _clean_tc(raw):
    """Estrae un TC ben formato HH:MM:SS:FF dalla stringa grezza. Prosa/None → None.

    α.172.164 — valida anche i RANGE (HH 00-23, MM/SS 00-59, FF 00-29) e normalizza
    lo zero-padding: un candidato fuori range (es. l'AI emette '59:59:00:00') viene
    scartato invece di essere salvato come spec corrotta."""
    if not raw:
        return None
    m = _TC_RE.search(str(raw))
    if not m:
        return None
    from app.services.timecode import normalize_tc
    try:
        return normalize_tc(m.group(1))  # fps ignoto → range strutturali
    except ValueError:
        return None


def apply_head_specs(db: Session, template_id: int, parsed: dict, tenant_id: int) -> dict:
    """Idempotente. Setta i default_* del template SOLO se presenti nella preview
    (preview vuota non azzera) e fa upsert degli AudioConfigPreset per (template, code).
    NON crea voci taxonomy. Ritorna riepilogo. NON committa (il caller decide)."""
    from app.models.models import DeliveryTemplate, AudioConfigPreset
    tpl = db.query(DeliveryTemplate).filter(
        DeliveryTemplate.id == template_id,
        DeliveryTemplate.tenant_id == tenant_id).first()
    if not tpl:
        raise ValueError("template non trovato")

    tc = _clean_tc(parsed.get("default_tc_start"))
    pg = _clean_tc(parsed.get("default_program_start"))
    segs = parsed.get("timeline_segments") or []
    tc_set = pg_set = False
    if tc:
        tpl.default_tc_start = tc
        tc_set = True
    if pg:
        tpl.default_program_start = pg
        pg_set = True
    if segs:
        # α.172.164 — scarta TC segmento fuori range invece di salvarli corrotti.
        from app.services.timecode import normalize_tc
        def _seg_tc(x):
            if not x:
                return None
            try:
                return normalize_tc(str(x))
            except ValueError:
                return None
        for s in segs:
            if isinstance(s, dict):
                s["tc_in"] = _seg_tc(s.get("tc_in"))
                s["tc_out"] = _seg_tc(s.get("tc_out"))
        tpl.default_timeline_segments = segs

    created = updated = 0
    for code_def in parsed.get("audio_config_codes") or []:
        code = (code_def.get("code") or "").strip()
        if not code:
            continue
        preset = db.query(AudioConfigPreset).filter(
            AudioConfigPreset.delivery_template_id == template_id,
            AudioConfigPreset.code == code).first()
        if preset:
            preset.name = code_def.get("name") or preset.name
            preset.description = code_def.get("description") or preset.description
            preset.track_layout = code_def.get("tracks") or preset.track_layout
            updated += 1
        else:
            db.add(AudioConfigPreset(
                tenant_id=tenant_id,
                delivery_template_id=template_id,
                code=code,
                name=code_def.get("name") or code,
                description=code_def.get("description"),
                track_layout=code_def.get("tracks") or [],
            ))
            created += 1
    return {
        "tc_set": tc_set,
        "program_set": pg_set,
        "segments_n": len(segs),
        "presets_created": created,
        "presets_updated": updated,
        "suggested_taxonomy": parsed.get("suggested_taxonomy") or [],
    }


# ── Alias reconciliation (LLM cross-reference) ────────────────────────────────

_ALIAS_FIELDS = ("channel_config", "mix_type", "mix_standard", "codec")


def _apply_alias_mapping(parsed: dict, mapping: dict) -> dict:
    """Applica un mapping {(kind, raw_name) -> canonical_name} al parsed:
    - riscrive i campi traccia (channel_config/mix_type/mix_standard/codec) il cui
      valore == raw_name al nome canonico;
    - rimuove da suggested_taxonomy le voci (kind,name) che risultano alias (mappate),
      tenendo solo le genuinamente nuove.
    Ritorna {"mapped":[{kind,name,canonical}], "new":[<suggested rimasti>]}.
    """
    # rewrite track fields
    for code in parsed.get("audio_config_codes") or []:
        for tr in code.get("tracks") or []:
            for kind in _ALIAS_FIELDS:
                val = tr.get(kind)
                if val is not None and (kind, val) in mapping:
                    tr[kind] = mapping[(kind, val)]
    # prune suggested_taxonomy
    mapped, new = [], []
    for s in parsed.get("suggested_taxonomy") or []:
        key = (s.get("kind"), s.get("name"))
        if key in mapping:
            mapped.append({"kind": s.get("kind"), "name": s.get("name"),
                           "canonical": mapping[key]})
        else:
            new.append(s)
    parsed["suggested_taxonomy"] = new
    return {"mapped": mapped, "new": new}


def reconcile_taxonomy_aliases(provider, parsed: dict, db, tenant_id: int) -> dict:
    """Cross-reference LLM: per ogni voce suggested_taxonomy decide se è sinonimo
    di una canonica esistente (es. 'IT mix' -> 'M&E') o genuinamente nuova. Applica
    il mapping (rewrite tracce + prune suggested). Best-effort: errori non rompono.
    Ritorna il report di _apply_alias_mapping (o {"mapped":[],"new":[...]} se no-op)."""
    suggested = parsed.get("suggested_taxonomy") or []
    if not suggested:
        return {"mapped": [], "new": []}
    vocab = _taxonomy_vocab(db, tenant_id)
    try:
        sys_p = (
            "Sei un esperto di terminologia audio di post-produzione. Per ogni TERMINE "
            "dato, decidi se è solo un NOME DIVERSO di una delle voci CANONICHE della "
            "stessa categoria (sinonimo/alias, es. 'IT mix'='IT'='M&E'; 'Music & Effects'='M&E'). "
            "Rispondi SOLO JSON: una lista di {\"kind\":\"\",\"name\":\"\",\"canonical\":\"<nome canonico esatto OPPURE NEW>\"}. "
            "Usa il nome canonico ESATTO dalla lista fornita se è un alias; 'NEW' se è "
            "davvero un concetto nuovo non presente."
        )
        lines = ["CANONICHE per categoria:"]
        for k in _ALIAS_FIELDS:
            lines.append(f"  {k}: {vocab.get(k, [])}")
        lines.append("TERMINI da classificare:")
        for s in suggested:
            lines.append(f"  - kind={s.get('kind')} name={s.get('name')!r} (visto come {s.get('seen_as')!r})")
        raw = provider.complete(sys_p, "\n".join(lines), max_tokens=2000, temperature=0.0)
        # La risposta è una LISTA JSON di decisioni; safe_json_parse la ritorna
        # come list (NON usare _parse_head_json che forza dict → scarterebbe la lista).
        from app.services.ai_provider import safe_json_parse
        decisions = safe_json_parse(raw)
        if isinstance(decisions, dict):
            decisions = decisions.get("items") or decisions.get("decisions") or []
        if not isinstance(decisions, list):
            decisions = []
        mapping = {}
        for d in (decisions or []):
            kind = d.get("kind"); name = d.get("name"); canon = d.get("canonical")
            if kind and name and canon and canon != "NEW" and canon in vocab.get(kind, []):
                mapping[(kind, name)] = canon
        return _apply_alias_mapping(parsed, mapping)
    except Exception as e:
        logger.warning("[head-extractor] reconcile_taxonomy_aliases failed: %s", e)
        return {"mapped": [], "new": suggested}
