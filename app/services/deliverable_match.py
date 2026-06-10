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
