"""v3.5.0-alpha.172.113 — Parser AI 2-pass per estrarre DeliveryItem da capitolato.

Architettura:

PASS 1 (vocabulary extraction):
  - Estrai dal capitolato la LISTA dei delivery item distinti che il cliente
    richiede (es. "DCP 2K IT", "ProRes Master HD", "IMF Netflix App 2E").
  - Estrai termini tecnici menzionati (codec, container, package, audio configs,
    color spaces, frame rates, resolutions).
  - Output JSON minimo: {items: [{name, category, hints}], terms: {codec: [...], ...}}

PASS 2 (taxonomy mapping):
  - Per OGNI item del pass 1, fornisci vocabolario taxonomy esistente come
    "dropdown options" e chiedi all'AI di mappare a FK numerici.
  - Output JSON: {items: [{name, package_id, container_id, video_codec_id,
    audio_codec_id, channel_config_id, mix_type_id, mix_standard_id,
    resolution_id, frame_rate_id, audio_tracks: [{...}], extra_specs: {...}}]}

Termini sconosciuti → flag `pending_review=True` su DeliveryItem + extra_specs
contiene la stringa originale per review manuale.

Mantenere coerente con `deliverables_parser.parse_delivery_template` (output
legacy 8 blocchi JSON): le due strategie convivono. parse_delivery_template
resta per il visualizer 8 blocchi; questo è il nuovo path strutturato.
"""
from __future__ import annotations
import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.services.ai_provider import get_provider, safe_json_parse
from app.services.naming_resolver import normalize_naming_convention
from app.models.models import (
    Package, Container, VideoCodec, AudioCodec, AudioChannelConfig,
    AudioMixType, MixStandard, Resolution, FrameRate,
)

logger = logging.getLogger(__name__)


PASS1_SYSTEM_PROMPT = """Sei un assistente esperto in postproduzione audiovisiva (cinema, TV, streaming, broadcast).

Compito: analizzare un capitolato di consegna e identificare:
1. LISTA distinta dei delivery items che il cliente richiede (es. "DCP 2K IT", "ProRes 4444 XQ Master HD WW", "IMF App 2E", "Trailer ProRes 422 HQ").
2. TERMINI TECNICI menzionati raggruppati per categoria.

Output JSON (NIENTE testo prima/dopo, NIENTE markdown, NIENTE backtick):
{
  "items": [
    {
      "name": "string breve",
      "category": "feature_master|trailer|dcp|imf|prores_master|broadcast_master|audio_only|other",
      "hints": "stringa con info aggiuntive utili (territori/lingue/HDR/etc)"
    }
  ],
  "terms": {
    "packages": ["DCP", "IMF App 2E"],
    "containers": ["QuickTime", "MXF OP1a"],
    "video_codecs": ["ProRes 4444 XQ", "JPEG 2000"],
    "audio_codecs": ["PCM 24-bit", "Dolby Atmos Master"],
    "channel_configs": ["5.1 SMPTE", "Atmos 7.1.4", "Stereo"],
    "mix_types": ["Full Mix", "M&E"],
    "mix_standards": ["EBU R128", "Theatrical Farfield"],
    "resolutions": ["2K DCI Flat", "UHD 3840"],
    "frame_rates": ["24 fps", "23.976 fps"],
    "color_spaces": ["Rec.709", "DCI XYZ", "Rec.2020 PQ"],
    "hdr_formats": ["HDR10", "Dolby Vision"]
  }
}

Includi SOLO quello che il capitolato menziona esplicitamente.
"""


def _taxonomy_dict_for_pass2(db: Session, tenant_id: int) -> dict:
    """Carica vocabulary taxonomy compatto (solo id+name) per minimizzare token
    pass 2. Output: {entity: [[id, "name"], ...]}."""
    def _q(Model):
        return db.query(Model).filter(
            (Model.tenant_id == tenant_id) | (Model.tenant_id.is_(None)),
            Model.is_active == True,  # noqa: E712
        ).order_by(Model.sort_order, Model.id).all()
    out = {
        "packages":         [[r.id, r.name] for r in _q(Package)],
        "containers":       [[r.id, r.name] for r in _q(Container)],
        "video_codecs":     [[r.id, r.name] for r in _q(VideoCodec)],
        "audio_codecs":     [[r.id, r.name] for r in _q(AudioCodec)],
        "channel_configs":  [[r.id, r.name] for r in _q(AudioChannelConfig)],
        "mix_types":        [[r.id, r.name] for r in _q(AudioMixType)],
        "mix_standards":    [[r.id, r.name] for r in _q(MixStandard)],
        "resolutions":      [[r.id, r.name] for r in _q(Resolution)],
        "frame_rates":      [[r.id, r.name] for r in _q(FrameRate)],
    }
    return out


PASS2_SYSTEM_PROMPT = """Sei un assistente esperto in postproduzione audiovisiva. Devi MAPPARE le voci di delivery che il capitolato richiede ai record di vocabolario taxonomy disponibili nel sistema.

Riceverai:
1. La LISTA degli item da mappare (output pass 1).
2. Il TESTO RILEVANTE del capitolato per quei item.
3. Il VOCABOLARIO TAXONOMY corrente (record con id+name+attributi).

Per OGNI item, restituisci:
- package_id (int o null se single-file format senza package)
- container_id (int)
- video_codec_id (int o null se audio-only)
- video_bit_depth (int: 8/10/12/16 o null)
- chroma_subsampling (string: "4:4:4" "4:2:2" "4:2:0" o null)
- resolution_id (int o null)
- aspect_ratio (string: "1.85" "2.39" "16:9" o null)
- frame_rate_id (int o null)
- scan_type (string: "progressive" "interlaced" "psf" o null)
- color_space (string: "Rec.709" "DCI XYZ" "Rec.2020 PQ" o null)
- hdr_format (string: "SDR" "HDR10" "HDR10+" "Dolby Vision" "HLG" o null)
- subtitle_format (string: "TTML IMSC 1.1" "PNG+XML" "Burn-in" "PGS" "EBU-STL" o null)
- subtitle_languages (lista codici ISO: ["it","en"] o null)
- suggested_unit (string: "pc" "TB" "min")
- suggested_qty (number)
- audio_tracks: lista [{track_label, channel_config_id, mix_type_id, mix_standard_id, audio_codec_id, sample_rate_hz, bit_depth, is_optional, notes}]
- tc_start: timecode di inizio file se indicato (es. "00:59:59:00"), altrimenti null
- program_start: timecode di inizio programma se indicato (es. "01:00:00:00"), altrimenti null
- timeline_segments: lista ordinata della testa/coda se descritta nel capitolato.
  Ogni elemento: {order, kind, label, tc_in, tc_out, duration, reel, source, notes}.
  kind ∈ bars_tone|slate|countdown|counter|black|program|textless|logo|main_titles|tail|other.
  reel = numero rullo DCP (es. Vision "1 logo = 1 rullo"); source = materiale sorgente.
  Se non descritta, lista vuota.
- audio_config_code: codice di configurazione audio d'emittente se citato (es. RAI "8T07", "16T09"), altrimenti null
- naming_convention: oggetto OPZIONALE — compila SOLO se il capitolato specifica la convenzione di nomenclatura file per QUESTA voce; altrimenti ometti o metti null. Stesso schema del blocco template:
  - "pattern": stringa con token tra graffe scelti TRA QUESTI: {project_code, project_title, film_name, content_type, aspect, resolution, framerate, audio_config, lang_audio, lang_subs, territory, version, revision, standard, package_type, deliverable_kind, date_iso, date_compact, studio_code, facility_code}. Esempio: "{film_name}_{content_type}_{resolution}_{lang_audio}".
  - "separator": separatore (es. "_").
  - "case": "upper" | "lower" | "asis".
  - "extension": estensione file se indicata (es. ".mxf").
  - "max_length": numero massimo caratteri o null.
  - "allowed_chars": classe caratteri ammessi se indicata (es. "A-Za-z0-9_-").
  - "examples": lista di nomi-file di esempio citati nel capitolato.
  - "raw_note": se la convenzione è descritta a parole ma NON mappabile a un pattern pulito, riporta qui il testo verbatim.
Quello che non riesci a strutturare, mettilo in `notes` (non perdere informazioni).
- extra_specs: dict JSON freeform per cose NON in taxonomy (teste/code, naming convention, archive notes, metadata extras)
- pending_review: true SE non sei sicuro al 80%+ del mapping di package/container/video_codec
- confidence: float 0.0-1.0

Output JSON puro (NIENTE markdown, backtick, preambolo):
{
  "items": [
    {
      "name": "string",
      "package_id": 2,
      "container_id": 2,
      "video_codec_id": 25,
      ...
      "audio_tracks": [...],
      "naming_convention": {"pattern": "{film_name}_{content_type}_{resolution}_{lang_audio}", "separator": "_", "case": "upper", "extension": ".mxf", "examples": [...], "raw_note": ""},
      "extra_specs": {...},
      "pending_review": false,
      "confidence": 0.85
    }
  ]
}

REGOLE FONDAMENTALI:
- USA SOLO ID dal vocabolario fornito. Se un termine del capitolato non matcha NESSUN id → metti l'id più vicino (best-effort) + pending_review=true + nel notes/extra_specs metti la stringa originale.
- Un DeliveryItem può avere MOLTE audio_tracks (Mix Theatrical + Mix HE + M&E + Stems insieme).
- subtitle_languages SOLO se esplicito.
- Conservatore con HDR: se il capitolato dice solo "HDR" senza specificare formato → metadata HDR10 baseline.
- DCP item: package_id=DCP SMPTE (o Interop se esplicito), container_id=MXF OP1a, video_codec=JPEG 2000 (DCP).
- IMF item: package_id=IMF App 2/2E/etc, container=MXF OP1a, video_codec=JPEG 2000 P-HT o ProRes IMF (App 2E) o JPEG XS (App 5).
- ProRes file: package_id=null (no package), container=QuickTime.
"""


def parse_delivery_items_v2(text: str, db: Session, tenant_id: int = 1,
                            provider=None) -> Optional[dict]:
    """Esegue il flow 2-pass e ritorna il dict structured pronto per insert.

    Ritorna: {items: [...], pass1_terms: {...}, pass1_categories: [...]}
    """
    if provider is None:
        provider = get_provider()
    if not provider:
        logger.error("parse_delivery_items_v2: nessun provider AI disponibile")
        return None

    MAX_CHARS = 30000
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n\n[... testo troncato ...]"
    if len(text.strip()) < 20:
        return None

    # PASS 1 — extract items + terms
    pass1_user = f"""Capitolato da analizzare:

---
{text}
---

Estrai gli item richiesti e i termini tecnici."""
    try:
        pass1_result = provider.extract_json(PASS1_SYSTEM_PROMPT, pass1_user, max_tokens=4000)
    except Exception as e:
        logger.error(f"pass1 failed: {e}")
        return None
    if not pass1_result or "items" not in pass1_result:
        return None
    items = pass1_result.get("items") or []
    terms = pass1_result.get("terms") or {}

    if not items:
        logger.warning("pass1 returned 0 items")
        return {"items": [], "pass1_terms": terms, "pass1_categories": []}

    # PASS 2 — map to FK ids
    taxonomy = _taxonomy_dict_for_pass2(db, tenant_id)
    taxonomy_json = json.dumps(taxonomy, ensure_ascii=False, indent=None)
    items_json = json.dumps(items, ensure_ascii=False, indent=None)
    pass2_user = f"""Item da mappare (estratti da pass 1):
{items_json}

Vocabolario taxonomy disponibile:
{taxonomy_json}

Testo capitolato (per riferimento):
---
{text}
---

Mappa ciascun item agli id taxonomy."""
    try:
        # v3.5.0-alpha.172.118 — bump 16K → 32K: PIPERFILM-DELIVERY troncava
        # output (DCP + 16 audio channels + multi-edizioni = items con extra_specs
        # molto verbosi). Sonnet 4.6 supporta fino a 64K output.
        pass2_result = provider.extract_json(PASS2_SYSTEM_PROMPT, pass2_user, max_tokens=32000)
    except Exception as e:
        logger.error(f"pass2 failed: {e}")
        return None
    if not pass2_result or "items" not in pass2_result:
        diag = getattr(provider, "last_extract_diag", {}) or {}
        logger.error(f"pass2 returned no items. diag={diag}")
        return None

    return {
        "items": pass2_result.get("items") or [],
        "pass1_terms": terms,
        "pass1_categories": [it.get("category") for it in items],
    }


def materialize_items(db: Session, delivery_template_id: int, parsed: dict,
                      tenant_id: int = 1) -> tuple[int, int]:
    """Inserisce in DB i DeliveryItem + AudioTrackSpec dal risultato parser.

    Idempotente per name+template (skip se esiste). Ritorna (saved, skipped)."""
    from app.models.models import DeliveryItem, AudioTrackSpec
    existing_names = {
        i.name for i in db.query(DeliveryItem.name).filter(
            DeliveryItem.delivery_template_id == delivery_template_id,
            DeliveryItem.tenant_id == tenant_id,
        ).all()
    }
    saved = 0
    skipped = 0
    for idx, it in enumerate(parsed.get("items") or []):
        name = (it.get("name") or "").strip()
        if not name:
            continue
        if name in existing_names:
            skipped += 1
            continue
        item = DeliveryItem(
            tenant_id=tenant_id,
            delivery_template_id=delivery_template_id,
            name=name,
            sort_order=idx * 10,
            package_id=it.get("package_id"),
            container_id=it.get("container_id"),
            package_variant_notes=it.get("package_variant_notes"),
            video_codec_id=it.get("video_codec_id"),
            video_bit_depth=it.get("video_bit_depth"),
            chroma_subsampling=it.get("chroma_subsampling"),
            resolution_id=it.get("resolution_id"),
            aspect_ratio=it.get("aspect_ratio"),
            frame_rate_id=it.get("frame_rate_id"),
            scan_type=it.get("scan_type"),
            color_space=it.get("color_space"),
            hdr_format=it.get("hdr_format"),
            subtitle_format=it.get("subtitle_format"),
            subtitle_languages=it.get("subtitle_languages"),
            suggested_unit=it.get("suggested_unit"),
            suggested_qty=it.get("suggested_qty"),
            suggested_price_item_id=None,  # mapping listino al passo successivo
            extra_specs=it.get("extra_specs"),
            notes=it.get("notes"),
            tc_start=it.get("tc_start"),
            program_start=it.get("program_start"),
            timeline_segments=it.get("timeline_segments") or None,
            audio_config_code=it.get("audio_config_code"),
            naming_convention=normalize_naming_convention(it.get("naming_convention")),
            ai_extracted=True,
            ai_confidence=float(it.get("confidence") or 0.0),
            pending_review=bool(it.get("pending_review", False)),
            # catena capitolato→fisico (derivati da archive_specs nel parser)
            requires_physical=bool(it.get("requires_physical", False)),
            physical_media_kind=it.get("physical_media_kind") or None,
        )
        db.add(item)
        db.flush()  # popola item.id per audio_tracks
        # v3.5.0-alpha.172.127 — se il parser ha trovato un audio_config_code,
        # crea/collega un AudioConfigPreset sul template (idempotente per code).
        acode = (it.get("audio_config_code") or "").strip()
        if acode:
            from app.models.models import AudioConfigPreset
            preset = (db.query(AudioConfigPreset)
                      .filter(AudioConfigPreset.delivery_template_id == delivery_template_id,
                              AudioConfigPreset.code == acode).first())
            if not preset:
                preset = AudioConfigPreset(
                    tenant_id=tenant_id, delivery_template_id=delivery_template_id,
                    code=acode, name=acode,
                    track_layout=it.get("audio_tracks") or [],
                )
                db.add(preset); db.flush()
            item.audio_config_preset_id = preset.id
        for t_idx, t in enumerate(it.get("audio_tracks") or []):
            tr = AudioTrackSpec(
                delivery_item_id=item.id,
                sort_order=t_idx * 10,
                track_label=t.get("track_label") or f"Track {t_idx + 1}",
                channel_config_id=t.get("channel_config_id"),
                mix_type_id=t.get("mix_type_id"),
                mix_standard_id=t.get("mix_standard_id"),
                audio_codec_id=t.get("audio_codec_id"),
                sample_rate_hz=t.get("sample_rate_hz"),
                bit_depth=t.get("bit_depth"),
                is_optional=bool(t.get("is_optional", False)),
                notes=t.get("notes"),
            )
            db.add(tr)
        saved += 1
    db.commit()
    return saved, skipped
