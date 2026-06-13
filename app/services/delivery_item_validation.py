"""v3.5.0-alpha.172.121 (Tier 3 Bundle B) — Validazione cross-tier
DeliveryItem.

Verifica combinazioni FK compatibili (package <-> container, container
<-> codec, codec <-> bit_depth, HDR <-> color_space, ecc).

Output: lista di dict ``{severity, code, message, fields}`` con
``severity`` in {``error``, ``warning``, ``info``}.

Le regole sono dichiarative qui dentro per restare leggibili. Quando
l'AI estrae item da capitolato (delivery_items_parser pass2), questa
validazione può essere richiamata per produrre un report di consistenza
post-parse senza re-call all'LLM.

Niente raise: il caller decide se bloccare o solo notificare.
"""
from __future__ import annotations
from typing import Optional
from sqlalchemy.orm import Session
from app.models.models import (
    DeliveryItem, Package, Container, VideoCodec, AudioCodec,
    Resolution, FrameRate, AudioTrackSpec,
)


def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()


def validate_delivery_item(db: Session, item: DeliveryItem) -> list[dict]:
    """Restituisce lista di issue. Vuoto = item compliant."""
    issues: list[dict] = []

    pkg = db.get(Package, item.package_id) if item.package_id else None
    cont = db.get(Container, item.container_id) if item.container_id else None
    vc = db.get(VideoCodec, item.video_codec_id) if item.video_codec_id else None
    res = db.get(Resolution, item.resolution_id) if item.resolution_id else None
    fr = db.get(FrameRate, item.frame_rate_id) if item.frame_rate_id else None

    pkg_name = _norm(pkg.name if pkg else "")
    cont_name = _norm(cont.name if cont else "")
    cont_kind = _norm(cont.media_kind if cont else "")
    cont_op = _norm(cont.op_pattern if cont else "")
    cont_is_imgseq = bool(cont.is_image_sequence if cont else False)
    vc_family = _norm(vc.family if vc else "")
    res_family = _norm(res.family if res else "")

    # R1 — Package DCP richiede Container MXF + Codec J2K
    if "dcp" in pkg_name:
        if cont and "mxf" not in cont_name:
            issues.append({
                "severity": "error",
                "code": "DCP_REQUIRES_MXF",
                "message": f"Package '{pkg.name}' richiede container MXF, non '{cont.name}'.",
                "fields": ["package_id", "container_id"],
            })
        if vc and "jpeg" not in vc_family and "j2k" not in vc_family:
            issues.append({
                "severity": "error",
                "code": "DCP_REQUIRES_J2K",
                "message": f"Package '{pkg.name}' richiede VideoCodec JPEG2000, non '{vc.family or vc.name}'.",
                "fields": ["package_id", "video_codec_id"],
            })

    # R2 — Package IMF richiede MXF OP1a
    if "imf" in pkg_name:
        if cont and "mxf" not in cont_name:
            issues.append({
                "severity": "error",
                "code": "IMF_REQUIRES_MXF",
                "message": f"Package '{pkg.name}' richiede container MXF, non '{cont.name}'.",
                "fields": ["package_id", "container_id"],
            })
        elif cont and cont_op and cont_op != "op1a":
            issues.append({
                "severity": "warning",
                "code": "IMF_PREFERS_OP1A",
                "message": f"Package IMF preferisce MXF OP1a, trovato '{cont.op_pattern}'.",
                "fields": ["container_id"],
            })

    # R3 — VideoCodec ProRes richiede QuickTime
    if "prores" in vc_family:
        if cont and "quicktime" not in cont_name and "mov" not in cont_name:
            issues.append({
                "severity": "warning",
                "code": "PRORES_PREFERS_QUICKTIME",
                "message": f"VideoCodec ProRes tipicamente in QuickTime/.mov, trovato '{cont.name}'.",
                "fields": ["video_codec_id", "container_id"],
            })

    # R4 — VideoCodec J2K richiede MXF (DCP/IMF)
    if "jpeg" in vc_family or "j2k" in vc_family:
        if cont and "mxf" not in cont_name:
            issues.append({
                "severity": "error",
                "code": "J2K_REQUIRES_MXF",
                "message": f"VideoCodec JPEG2000 richiede container MXF, non '{cont.name}'.",
                "fields": ["video_codec_id", "container_id"],
            })

    # R5 — Container image_sequence non ammette audio_tracks
    if cont_is_imgseq:
        n_tracks = db.query(AudioTrackSpec).filter(
            AudioTrackSpec.delivery_item_id == item.id,
        ).count() if item.id else 0
        if n_tracks > 0:
            issues.append({
                "severity": "warning",
                "code": "IMGSEQ_NO_AUDIO",
                "message": f"Container '{cont.name}' è image sequence (muta), ma ha {n_tracks} audio_track collegate.",
                "fields": ["container_id"],
            })

    # R6 — HDR format richiede bit_depth >= 10 + color_space coerente
    hdr = _norm(item.hdr_format)
    if hdr and hdr not in ("sdr", "none", ""):
        if item.video_bit_depth is not None and item.video_bit_depth < 10:
            issues.append({
                "severity": "error",
                "code": "HDR_REQUIRES_10BIT",
                "message": f"HDR '{item.hdr_format}' richiede video_bit_depth >= 10, trovato {item.video_bit_depth}.",
                "fields": ["hdr_format", "video_bit_depth"],
            })
        cs = _norm(item.color_space)
        if cs and "rec.2020" not in cs and "rec2020" not in cs and "bt.2020" not in cs and "p3" not in cs:
            issues.append({
                "severity": "warning",
                "code": "HDR_PREFERS_BT2020_OR_P3",
                "message": f"HDR '{item.hdr_format}' tipicamente in Rec.2020 o DCI-P3, color_space attuale '{item.color_space}'.",
                "fields": ["hdr_format", "color_space"],
            })

    # R7 — UHD/4K @ frame rate molto alto (raro)
    if res and fr and ("uhd" in res_family or "4k" in res_family or "8k" in res_family):
        fps_name = _norm(fr.name)
        # estrai numero
        try:
            fps_num = float(''.join(ch for ch in fps_name if ch.isdigit() or ch == '.'))
        except ValueError:
            fps_num = 0.0
        if fps_num >= 100:
            issues.append({
                "severity": "info",
                "code": "UHD_HIGH_FRAMERATE",
                "message": f"Combinazione UHD/4K @ {fr.name} è rara — verifica capitolato.",
                "fields": ["resolution_id", "frame_rate_id"],
            })

    # R8 — Container kind = audio non ammette video_codec
    if cont_kind == "audio" and item.video_codec_id is not None:
        issues.append({
            "severity": "warning",
            "code": "AUDIO_CONTAINER_NO_VCODEC",
            "message": f"Container '{cont.name}' è audio-only, video_codec non dovrebbe essere settato.",
            "fields": ["container_id", "video_codec_id"],
        })

    # R9 — Item senza container è invalido (container è il minimo strutturale)
    if not item.container_id:
        issues.append({
            "severity": "error",
            "code": "MISSING_CONTAINER",
            "message": "Container obbligatorio: definisce il wrapper di file.",
            "fields": ["container_id"],
        })

    return issues


def validate_summary(db: Session, item: DeliveryItem) -> dict:
    """Wrapper convenience: aggrega per severity."""
    issues = validate_delivery_item(db, item)
    counts = {"error": 0, "warning": 0, "info": 0}
    for it in issues:
        s = it.get("severity", "info")
        counts[s] = counts.get(s, 0) + 1
    return {
        "ok": counts["error"] == 0,
        "counts": counts,
        "issues": issues,
    }


# v3.5.0-alpha.172.183 — Pertinenza dei campi spec per tipo file. Pura, niente DB.
# Gruppi: video, audio, subtitle, package, color, timecode -> "show"|"hide".
_RELEVANCE_GROUPS = ("video", "audio", "subtitle", "package", "color", "timecode")


def field_relevance(*, media_kind, has_package, video_codec_family=None, has_audio=False) -> dict:
    """Quali gruppi di campi sono pertinenti per il tipo file.

    media_kind: "video"|"audio"|"image_seq"|"mixed"|None (da Container.media_kind).
    has_package/has_audio: bool. video_codec_family: stringa o None.
    Default difensivo: media_kind sconosciuto/None -> tutto "show" (non nascondere
    se non sappiamo). subtitle/timecode sempre "show".
    """
    mk = (media_kind or "").strip().lower()
    g = {k: "show" for k in _RELEVANCE_GROUPS}
    if mk == "audio":
        g["video"] = "hide"
        g["color"] = "hide"
        g["audio"] = "show"
    elif mk == "image_seq":
        g["audio"] = "hide"
        g["video"] = "show"
        g["color"] = "show"
    elif mk in ("video", "mixed"):
        g["video"] = "show"
        g["color"] = "show"
        g["audio"] = "show" if has_audio else "hide"
    # mk sconosciuto/None -> tutto show (default difensivo)
    g["package"] = "show" if has_package else "hide"
    return g


def valid_video_codec_ids(*, media_kind, container_name, codecs) -> list:
    """Id dei video codec ammessi nel container, derivati dalle regole ERROR.

    PURA: nessun DB. `codecs` = iterabile di oggetti con `.id`/`.family` o dict
    con chiavi 'id'/'family'. Il chiamante risolve container/codecs e passa qui.

    - media_kind == 'audio' → []  (nessun video codec; coerente con R8).
    - container NON-MXF (name senza 'mxf') → esclude family JPEG2000/J2K (R4: J2K solo MXF).
    - altrimenti → tutti gli id.
    (ProRes→QuickTime è WARNING, NON filtrato: resta selezionabile.)
    """
    mk = (media_kind or "").strip().lower()
    if mk == "audio":
        return []
    is_mxf = "mxf" in (container_name or "").strip().lower()
    out = []
    for c in codecs:
        cid = c["id"] if isinstance(c, dict) else c.id
        fam = (c["family"] if isinstance(c, dict) else getattr(c, "family", "")) or ""
        fam = fam.strip().lower()
        if ("jpeg" in fam or "j2k" in fam) and not is_mxf:
            continue
        out.append(cid)
    return out


def preferred_container_for_codec(*, codec_family, containers) -> Optional[int]:
    """Id del container preferito per la famiglia codec. PURA: nessun DB.

    `containers` = iterabile di oggetti con `.id`/`.name`/`.extension` o dict con
    chiavi 'id'/'name'/'extension'. Il chiamante risolve e ordina i container.

    - family contiene 'prores' → id del primo container QuickTime/.mov nell'ordine
      ricevuto; None se nessun QuickTime disponibile.
    - altre family / family vuota/None → None (nessuna preferenza forzata).

    Deriva dalla regola R3 (ProRes tipicamente in QuickTime/.mov). Estendibile in
    futuro con altre coppie codec→container.
    """
    fam = (codec_family or "").strip().lower()
    if "prores" not in fam:
        return None
    for c in containers:
        if isinstance(c, dict):
            cid = c.get("id")
            name = (c.get("name") or "")
            ext = (c.get("extension") or "")
        else:
            cid = getattr(c, "id", None)
            name = getattr(c, "name", "") or ""
            ext = getattr(c, "extension", "") or ""
        nm = name.strip().lower()
        ex = ext.strip().lower()
        if "quicktime" in nm or "mov" in nm or ex in (".mov", "mov"):
            return cid
    return None
