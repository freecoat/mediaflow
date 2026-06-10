"""F2 (spec 2026-06-10) — Matching proposta asset ↔ JobDeliverable atteso.

Parte pura: normalizzazione + scoring. Il candidate-set DB sta in
`match_proposal` (Task 3). Score per-dimensione, somma pesata 0..1:
naming (peso 0.45) + container + codec + risoluzione + frame_rate.
Soglie: forte = naming concorde E >=2 specs tecniche concordi (o score
>=0.75); debole = 0.40..0.75; zero = <0.40.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import (
    Asset, Project, Job, JobDeliverable, DeliverableStatus, DeliveryItem,
    Container, VideoCodec, Resolution, FrameRate,
)

_CODEC_ALIASES = {
    "prores": "prores", "apch": "prores", "apcn": "prores", "ap4h": "prores",
    "h264": "h264", "avc": "h264", "avc1": "h264", "x264": "h264",
    "hevc": "h265", "h265": "h265", "x265": "h265",
    "mpeg2video": "mpeg2", "mpeg2": "mpeg2",
    "dnxhd": "dnxhd", "dnxhr": "dnxhr",
    "jpeg2000": "jpeg2000", "j2k": "jpeg2000",
}

STRONG_THRESHOLD = 0.75
WEAK_THRESHOLD = 0.40
W_NAMING = 0.45
W_SPEC = 0.55


@dataclass
class MatchExpectation:
    deliverable_id: int
    file_naming: Optional[str]
    container_name: Optional[str]
    container_ext: Optional[str]
    video_codec_name: Optional[str]
    width: Optional[int]
    height: Optional[int]
    fps: Optional[float]


@dataclass
class MatchResult:
    deliverable_id: int
    score: float
    strength: str
    specs_agree: int
    naming_ok: bool


def normalize_codec(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    key = re.sub(r"[^a-z0-9]", "", s.lower())
    for alias, canon in _CODEC_ALIASES.items():
        if key.startswith(alias):
            return canon
    return key or None


def _tokens(s: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", s.lower()) if t]


def score_naming(filename: str, expected: Optional[str]) -> float:
    if not expected:
        return 0.0
    fn = filename.lower()
    exp = expected.lower().strip()
    if not exp:
        return 0.0
    exp_core = re.sub(r"[^a-z0-9]+", "", exp)
    fn_core = re.sub(r"[^a-z0-9]+", "", fn)
    if exp_core and exp_core in fn_core:
        return 1.0
    exp_tok = set(_tokens(expected))
    fn_tok = set(_tokens(filename))
    if not exp_tok:
        return 0.0
    overlap = len(exp_tok & fn_tok) / len(exp_tok)
    return round(overlap, 3)


def _fps_from_rate(rate) -> Optional[float]:
    if rate is None:
        return None
    if isinstance(rate, (int, float)):
        return float(rate)
    s = str(rate)
    if "/" in s:
        num, den = s.split("/", 1)
        try:
            d = float(den)
            return float(num) / d if d else None
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def score_match(filename: str, probe: dict, exp: MatchExpectation) -> MatchResult:
    naming = score_naming(filename, exp.file_naming)
    naming_ok = naming >= 0.6

    video = (probe or {}).get("video") or {}
    p_container = (probe.get("container") or "").lower()
    p_codec = normalize_codec(video.get("codec"))
    p_w, p_h = video.get("width"), video.get("height")
    p_fps = _fps_from_rate(video.get("frame_rate"))

    spec_checks = []
    if exp.container_ext or exp.container_name:
        ok = False
        if exp.container_ext and exp.container_ext.lower() in p_container:
            ok = True
        if exp.container_name and exp.container_name.lower() in p_container:
            ok = True
        spec_checks.append(ok)
    if exp.video_codec_name:
        spec_checks.append(normalize_codec(exp.video_codec_name) == p_codec
                           and p_codec is not None)
    if exp.width and exp.height:
        spec_checks.append(p_w == exp.width and p_h == exp.height)
    if exp.fps:
        spec_checks.append(p_fps is not None and abs(p_fps - exp.fps) < 0.05)

    specs_agree = sum(1 for c in spec_checks if c)
    spec_score = (specs_agree / len(spec_checks)) if spec_checks else 0.0
    score = round(W_NAMING * naming + W_SPEC * spec_score, 3)

    if naming_ok and specs_agree >= 2:
        strength = "strong"
    elif score >= STRONG_THRESHOLD:
        strength = "strong"
    elif score >= WEAK_THRESHOLD:
        strength = "weak"
    else:
        strength = "none"

    return MatchResult(deliverable_id=exp.deliverable_id, score=score,
                       strength=strength, specs_agree=specs_agree,
                       naming_ok=naming_ok)


# ── orchestrazione DB ────────────────────────────────────────────────────────

_OPEN_STATUSES = (
    DeliverableStatus.planned,
    DeliverableStatus.in_progress,
    DeliverableStatus.qc,
)


def _project_code_from_relpath(rel_path: Optional[str]) -> Optional[str]:
    """Convenzione /OUT/{project_code}/... → project_code. Tollerante:
    prende il primo segmento dopo una watch-dir tipo OUT/EXPORT."""
    if not rel_path:
        return None
    parts = [p for p in rel_path.replace("\\", "/").split("/") if p]
    if len(parts) >= 2:
        return parts[1] if parts[0].isupper() and len(parts[0]) <= 8 else parts[0]
    return parts[0] if parts else None


def build_expectation(db: Session, deliv: JobDeliverable) -> MatchExpectation:
    item = db.get(DeliveryItem, deliv.delivery_item_id) if deliv.delivery_item_id else None
    cont = db.get(Container, item.container_id) if item and item.container_id else None
    cod = db.get(VideoCodec, item.video_codec_id) if item and item.video_codec_id else None
    res = db.get(Resolution, item.resolution_id) if item and item.resolution_id else None
    fr = db.get(FrameRate, item.frame_rate_id) if item and item.frame_rate_id else None
    naming = deliv.file_naming
    if not naming and item is not None:
        nc = getattr(item, "naming_convention", None)
        if isinstance(nc, str):
            naming = nc
    return MatchExpectation(
        deliverable_id=deliv.id, file_naming=naming,
        container_name=cont.name if cont else None,
        container_ext=cont.extension if cont else None,
        video_codec_name=cod.name if cod else None,
        width=res.width if res else None, height=res.height if res else None,
        fps=fr.fps if fr else None)


def candidate_deliverables(db: Session, asset: Asset) -> list[JobDeliverable]:
    code = _project_code_from_relpath(asset.rel_path)
    if not code:
        return []
    proj = db.execute(
        select(Project).where(Project.tenant_id == asset.tenant_id,
                              Project.code == code)
    ).scalar_one_or_none()
    if proj is None:
        return []
    rows = db.execute(
        select(JobDeliverable)
        .join(Job, Job.id == JobDeliverable.job_id)
        .where(Job.project_id == proj.id,
               JobDeliverable.tenant_id == asset.tenant_id,
               JobDeliverable.digital_asset_id.is_(None),
               JobDeliverable.deleted_at.is_(None),
               JobDeliverable.status.in_(_OPEN_STATUSES))
    ).scalars().all()
    return list(rows)


def rank_candidates(db: Session, asset: Asset) -> list[dict]:
    probe = asset.tech_specs_json or {}
    out = []
    for d in candidate_deliverables(db, asset):
        exp = build_expectation(db, d)
        r = score_match(asset.filename or "", probe, exp)
        if r.strength != "none":
            out.append({"deliverable_id": d.id, "name": d.name,
                        "score": r.score, "strength": r.strength,
                        "specs_agree": r.specs_agree, "naming_ok": r.naming_ok})
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


def match_proposal(db: Session, asset: Asset) -> Optional[int]:
    ranked = rank_candidates(db, asset)
    strong = [r for r in ranked if r["strength"] == "strong"]
    if len(strong) == 1:
        asset.matched_deliverable_id = strong[0]["deliverable_id"]
        db.flush()
        return asset.matched_deliverable_id
    asset.matched_deliverable_id = None
    db.flush()
    return None
