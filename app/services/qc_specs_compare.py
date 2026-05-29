"""F3.3 pipeline deliverables (v3.5.0-alpha.172.138) — confronto QC specs.

Lazy bridge (decisione 5 rivista): nessun Asset placeholder "atteso". Le specs
attese sono derivate LIVE dal DeliveryItem collegato al deliverable (come
`qc_expected_for_deliverable`); le reali dallo `asset.tech_specs_json` prodotto
dall'extractor (shape ffprobe). Il confronto è tollerante alle differenze di
vocabolario (codec "Apple ProRes 422 HQ" ~ ffprobe "prores").

API:
- `build_expected(db, delivery_item)` → dict comparabile (numerico/normalizzato).
- `compare_to_actual(expected, actual_tech_specs)` → report per-campo.
- `run_deliverable_qc_compare(db, deliverable)` → trova l'asset digitale linkato,
  confronta, salva in `deliverable.qc_report_json`. None se manca item o asset.
"""
from __future__ import annotations

from collections import Counter
from typing import Optional

from sqlalchemy.orm import Session

from app.models.models import (
    DeliveryItem, Resolution, VideoCodec, AudioChannelConfig, Asset,
)


def build_expected(db: Session, item: DeliveryItem) -> dict:
    """Specs attese comparabili, derivate live dalla taxonomy del DeliveryItem."""
    res = db.get(Resolution, item.resolution_id) if item.resolution_id else None
    codec = db.get(VideoCodec, item.video_codec_id) if item.video_codec_id else None
    audio_channels: list[int] = []
    for t in (item.audio_tracks or []):
        if t.channel_config_id:
            cc = db.get(AudioChannelConfig, t.channel_config_id)
            if cc and cc.channel_count:
                audio_channels.append(int(cc.channel_count))
    video = None
    if res or codec or item.hdr_format:
        video = {
            "width": res.width if res else None,
            "height": res.height if res else None,
            # family se presente, altrimenti nome (per match fuzzy sul codec)
            "codec_family": (codec.family or codec.name) if codec else None,
            "hdr_format": item.hdr_format,
        }
    return {"video": video, "audio_channels": audio_channels}


def _norm(s) -> str:
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())


def _codec_match(expected_family: str, actual_codec: str) -> bool:
    """Match fuzzy: token normalizzato di uno contenuto nell'altro.
    "ProRes" ~ "prores", "JPEG 2000" ~ "jpeg2000", "H.264" ~ "h264"."""
    e, a = _norm(expected_family), _norm(actual_codec)
    if not e or not a:
        return False
    return e in a or a in e


def compare_to_actual(expected: dict, actual: dict) -> dict:
    """Confronta attese vs reali → report per-campo + summary.

    verdict ∈ match | mismatch | unknown (reale assente). unknown NON rende
    il report failed (ok=True se zero mismatch)."""
    fields: list[dict] = []
    exp_v = expected.get("video") or {}
    act_v = actual.get("video") or {}

    # Risoluzione (width×height)
    if exp_v.get("width") and exp_v.get("height"):
        exp_res = f"{exp_v['width']}x{exp_v['height']}"
        if act_v.get("width") and act_v.get("height"):
            act_res = f"{act_v['width']}x{act_v['height']}"
            fields.append(_field("resolution", exp_res, act_res, exp_res == act_res))
        else:
            fields.append(_field("resolution", exp_res, None, None))

    # Codec video (fuzzy)
    if exp_v.get("codec_family"):
        act_codec = act_v.get("codec")
        if act_codec:
            fields.append(_field("video_codec", exp_v["codec_family"], act_codec,
                                  _codec_match(exp_v["codec_family"], act_codec)))
        else:
            fields.append(_field("video_codec", exp_v["codec_family"], None, None))

    # HDR (confronto solo se atteso non-SDR; reale spesso non disponibile da ffprobe)
    hdr = (exp_v.get("hdr_format") or "").strip()
    if hdr and hdr.upper() != "SDR":
        act_hdr = act_v.get("hdr_format") or act_v.get("color_transfer")
        if act_hdr:
            fields.append(_field("hdr", hdr, act_hdr, _norm(hdr) in _norm(act_hdr)))
        else:
            fields.append(_field("hdr", hdr, None, None))

    # Canali audio: confronto multiset dei channel-count attesi vs reali
    exp_ch = expected.get("audio_channels") or []
    if exp_ch:
        act_ch = [a.get("channels") for a in (actual.get("audio") or []) if a.get("channels")]
        if act_ch:
            ok = Counter(exp_ch) == Counter(act_ch)
            fields.append(_field("audio_channels", _fmt_ch(exp_ch), _fmt_ch(act_ch), ok))
        else:
            fields.append(_field("audio_channels", _fmt_ch(exp_ch), None, None))

    summary = Counter(f["verdict"] for f in fields)
    return {
        "fields": fields,
        "summary": {
            "match": summary.get("match", 0),
            "mismatch": summary.get("mismatch", 0),
            "unknown": summary.get("unknown", 0),
        },
        "ok": summary.get("mismatch", 0) == 0,
    }


def _field(name: str, expected, actual, match: Optional[bool]) -> dict:
    if match is None:
        verdict = "unknown"
    elif match:
        verdict = "match"
    else:
        verdict = "mismatch"
    return {"field": name, "expected": expected, "actual": actual, "verdict": verdict}


def _fmt_ch(chs: list) -> str:
    return ", ".join(str(c) for c in chs)


def run_deliverable_qc_compare(db: Session, deliverable) -> "dict | None":
    """Esegue il confronto per un JobDeliverable: attese (delivery_item) vs reali
    (tech_specs_json dell'asset digitale linkato). Salva in qc_report_json.
    None se manca il DeliveryItem o l'asset/tech_specs."""
    if not getattr(deliverable, "delivery_item_id", None):
        return None
    item = db.get(DeliveryItem, deliverable.delivery_item_id)
    if not item:
        return None
    asset = db.get(Asset, deliverable.digital_asset_id) if deliverable.digital_asset_id else None
    if not asset or not asset.tech_specs_json:
        return None
    expected = build_expected(db, item)
    report = compare_to_actual(expected, asset.tech_specs_json)
    report["asset_id"] = asset.id
    report["delivery_item_id"] = item.id
    deliverable.qc_report_json = report
    return report
