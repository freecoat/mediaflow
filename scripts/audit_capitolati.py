"""v3.5.0-alpha.172.165 — Audit di validità READ-ONLY di tutti i dati dei capitolati.

Scansiona DeliveryTemplate + DeliveryItem (+ segmenti timeline, AudioConfigPreset,
AudioTrackSpec) e segnala anomalie raggruppate per severità. NON modifica nulla.

Severità:
  ERROR  dato rotto/incoerente (FK dangling, TC fuori range, campo obbligatorio vuoto)
  WARN   incoerenza probabile (color_space vs HDR, enum fuori set, primaries vs gamut)
  INFO   da rivedere (segmenti senza TC, valori inusuali)

Uso:
    python scripts/audit_capitolati.py            # report completo
    python scripts/audit_capitolati.py --errors   # solo ERROR
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from app.database import SessionLocal
from app.models import models as M
from app.services.timecode import is_valid_tc

_CHROMA = {"4:4:4", "4:2:2", "4:2:0", "4:1:1", "4:4:4:4"}
_SCAN = {"progressive", "interlaced", "psf"}
_BITDEPTH = {8, 10, 12, 16}
_TL_KINDS = {"bars_tone", "slate", "countdown", "counter", "black", "program",
             "textless", "logo", "main_titles", "tail", "other"}
_SUBFMT = {"TTML IMSC 1.1", "PNG+XML", "Burn-in", "PGS", "EBU-STL", "SRT"}
_PRIMARIES = {"BT.709", "BT.2020", "DCI-P3", "P3-D65", "BT.601 525", "BT.601 625",
              "ACES AP0", "ACES AP1", "XYZ"}

findings = []  # (severity, scope, msg)


def add(sev, scope, msg):
    findings.append((sev, scope, msg))


def _ids(db, cls):
    return {r.id: r for r in db.execute(select(cls)).scalars().all()}


def audit(db):
    tpls = _ids(db, M.DeliveryTemplate)
    items = list(db.execute(select(M.DeliveryItem)).scalars().all())
    presets = list(db.execute(select(M.AudioConfigPreset)).scalars().all())
    tracks = list(db.execute(select(M.AudioTrackSpec)).scalars().all())
    pkg = _ids(db, M.Package); cont = _ids(db, M.Container)
    vcod = _ids(db, M.VideoCodec); res = _ids(db, M.Resolution)
    frate = _ids(db, M.FrameRate); mix = _ids(db, M.AudioMixType)
    chcfg = _ids(db, M.AudioChannelConfig)
    price = _ids(db, M.PriceItem)

    # ── Templates ──
    seen_codes = {}
    for t in tpls.values():
        sc = f"tpl#{t.id} {t.code}"
        if not (t.code or "").strip():
            add("ERROR", sc, "code vuoto")
        else:
            seen_codes.setdefault(t.code, []).append(t.id)
        if not (t.broadcaster or "").strip():
            add("INFO", sc, "broadcaster vuoto")
        # TC template-level (fps ignoto → structural)
        for f in ("default_tc_start", "default_program_start"):
            val = getattr(t, f)
            if val and not is_valid_tc(val):
                add("ERROR", sc, f"{f} TC invalido: {val!r}")
        # segmenti default
        _audit_segments(getattr(t, "default_timeline_segments", None), sc, None)
        # suggested_items FK
        for si in (t.suggested_items or []):
            pid = si.get("price_item_id") if isinstance(si, dict) else None
            if pid and pid not in price:
                add("WARN", sc, f"suggested_items price_item_id {pid} inesistente")
    for code, idl in seen_codes.items():
        active = [i for i in idl if tpls[i].is_active]
        if len(active) > 1:
            add("ERROR", f"code={code}", f"code duplicato fra template attivi: {active}")

    tpl_item_count = {}
    for it in items:
        if it.is_active and it.delivery_template_id:
            tpl_item_count[it.delivery_template_id] = tpl_item_count.get(it.delivery_template_id, 0) + 1
    for t in tpls.values():
        if t.is_active and tpl_item_count.get(t.id, 0) == 0:
            add("WARN", f"tpl#{t.id} {t.code}", "nessun DeliveryItem attivo")

    # ── DeliveryItems ──
    fk_checks = [
        ("package_id", pkg), ("container_id", cont), ("video_codec_id", vcod),
        ("resolution_id", res), ("frame_rate_id", frate),
        ("suggested_price_item_id", price),
    ]
    preset_ids = {p.id for p in presets}
    for it in items:
        sc = f"item#{it.id} {it.name}"
        if not (it.name or "").strip():
            add("ERROR", sc, "name vuoto")
        if it.delivery_template_id not in tpls:
            add("ERROR", sc, f"delivery_template_id {it.delivery_template_id} dangling")
        for field, pool in fk_checks:
            v = getattr(it, field)
            if v and v not in pool:
                add("ERROR", sc, f"{field}={v} dangling (riga inesistente)")
            elif v and hasattr(pool.get(v), "is_active") and pool[v].is_active is False:
                add("WARN", sc, f"{field}={v} punta a riga DISATTIVATA")
        if it.audio_config_preset_id and it.audio_config_preset_id not in preset_ids:
            add("ERROR", sc, f"audio_config_preset_id={it.audio_config_preset_id} dangling")
        # enum sanity
        if it.video_bit_depth not in (None,) and it.video_bit_depth not in _BITDEPTH:
            add("WARN", sc, f"video_bit_depth inusuale: {it.video_bit_depth}")
        if it.chroma_subsampling and it.chroma_subsampling not in _CHROMA:
            add("WARN", sc, f"chroma fuori set: {it.chroma_subsampling!r}")
        if it.scan_type and it.scan_type not in _SCAN:
            add("WARN", sc, f"scan_type fuori set: {it.scan_type!r}")
        if it.subtitle_format and it.subtitle_format not in _SUBFMT:
            add("INFO", sc, f"subtitle_format fuori set: {it.subtitle_format!r}")
        if it.color_primaries and it.color_primaries not in _PRIMARIES:
            add("WARN", sc, f"color_primaries fuori set: {it.color_primaries!r}")
        # subtitle_languages shape
        sl = it.subtitle_languages
        if sl is not None and not isinstance(sl, list):
            add("WARN", sc, f"subtitle_languages non lista: {type(sl).__name__}")
        elif isinstance(sl, list):
            for code in sl:
                if not isinstance(code, str) or not (2 <= len(code) <= 8):
                    add("INFO", sc, f"subtitle lang sospetto: {code!r}")
        # TC fps-aware
        fr = frate.get(it.frame_rate_id) if it.frame_rate_id else None
        fps = fr.fps if fr else None
        drop = bool(fr.is_drop_frame) if fr else None
        for f in ("tc_start", "program_start"):
            v = getattr(it, f)
            if v and not is_valid_tc(v, fps=fps, drop=drop):
                add("ERROR", sc, f"{f} TC invalido per fps={fps}: {v!r}")
        _audit_segments(it.timeline_segments, sc, fps, drop)
        # color coerenza
        _audit_color(it, sc)
        # audio_config_code orfano (nessun preset con quel code nel template)
        if it.audio_config_code:
            codes = {p.code for p in presets if p.delivery_template_id == it.delivery_template_id}
            if it.audio_config_code not in codes:
                add("WARN", sc, f"audio_config_code {it.audio_config_code!r} senza preset nel template")

    # ── AudioConfigPreset ──
    by_tpl_code = {}
    for p in presets:
        sc = f"preset#{p.id} {p.code}"
        if not (p.code or "").strip():
            add("WARN", sc, "code vuoto")
        else:
            by_tpl_code.setdefault((p.delivery_template_id, p.code), []).append(p.id)
        if p.delivery_template_id not in tpls:
            add("ERROR", sc, f"delivery_template_id {p.delivery_template_id} dangling")
    for (tid, code), idl in by_tpl_code.items():
        if len(idl) > 1:
            add("WARN", f"tpl#{tid} code={code}", f"AudioConfigPreset code duplicato: {idl}")

    # ── AudioTrackSpec ──
    item_ids = {it.id for it in items}
    for tr in tracks:
        sc = f"track#{tr.id}"
        if tr.delivery_item_id not in item_ids:
            add("ERROR", sc, f"delivery_item_id {tr.delivery_item_id} dangling")
        if tr.channel_config_id and tr.channel_config_id not in chcfg:
            add("ERROR", sc, f"channel_config_id {tr.channel_config_id} dangling")
        if tr.mix_type_id and tr.mix_type_id not in mix:
            add("ERROR", sc, f"mix_type_id {tr.mix_type_id} dangling")
        if tr.sample_rate_hz and tr.sample_rate_hz not in (44100, 48000, 96000, 192000):
            add("INFO", sc, f"sample_rate_hz inusuale: {tr.sample_rate_hz}")
        if tr.bit_depth and tr.bit_depth not in (16, 24, 32):
            add("INFO", sc, f"audio bit_depth inusuale: {tr.bit_depth}")


def _audit_segments(segs, sc, fps, drop=None):
    if not segs:
        return
    if not isinstance(segs, list):
        add("ERROR", sc, f"timeline_segments non lista: {type(segs).__name__}")
        return
    from app.services.timecode import tc_to_frames
    for i, s in enumerate(segs):
        if not isinstance(s, dict):
            add("ERROR", sc, f"segmento[{i}] non dict")
            continue
        k = s.get("kind")
        if k and k not in _TL_KINDS:
            add("WARN", sc, f"segmento[{i}] kind fuori set: {k!r}")
        ti, to = s.get("tc_in"), s.get("tc_out")
        if ti and not is_valid_tc(ti, fps=fps, drop=drop):
            add("ERROR", sc, f"segmento[{i}] tc_in invalido: {ti!r}")
        if to and not is_valid_tc(to, fps=fps, drop=drop):
            add("ERROR", sc, f"segmento[{i}] tc_out invalido: {to!r}")
        # in < out (solo se entrambi validi e fps noto)
        if ti and to and fps and is_valid_tc(ti, fps=fps, drop=drop) and is_valid_tc(to, fps=fps, drop=drop):
            try:
                if tc_to_frames(ti, fps, drop) >= tc_to_frames(to, fps, drop):
                    add("WARN", sc, f"segmento[{i}] tc_in >= tc_out ({ti} ≥ {to})")
            except ValueError:
                pass


def _audit_color(it, sc):
    cs = (it.color_space or "").lower()
    hdr = (it.hdr_format or "").upper()
    is_hdr = hdr in ("HDR10", "HDR10+", "DOLBY VISION", "DV", "HLG")
    # Rec.2020/PQ/HLG ma SDR → contraddizione
    if ("2020" in cs or "pq" in cs or "hlg" in cs) and hdr == "SDR":
        add("WARN", sc, f"color_space {it.color_space!r} (wide/HDR) ma hdr_format=SDR")
    # HDR dichiarato ma gamut 709
    if is_hdr and "709" in cs:
        add("WARN", sc, f"hdr_format={hdr} ma color_space Rec.709 (gamut stretto)")
    # primaries vs color_space
    p = (it.color_primaries or "")
    if p and cs:
        if "2020" in p and ("709" in cs):
            add("WARN", sc, f"primaries {p} ma color_space {it.color_space!r}")
        if "709" in p and ("2020" in cs):
            add("WARN", sc, f"primaries {p} ma color_space {it.color_space!r}")
        if "XYZ" in p and "xyz" not in cs:
            add("WARN", sc, f"primaries XYZ ma color_space {it.color_space!r}")


if __name__ == "__main__":
    only_err = "--errors" in sys.argv
    db = SessionLocal()
    try:
        audit(db)
    finally:
        db.close()
    order = {"ERROR": 0, "WARN": 1, "INFO": 2}
    findings.sort(key=lambda f: (order[f[0]], f[1]))
    counts = {"ERROR": 0, "WARN": 0, "INFO": 0}
    for sev, scope, msg in findings:
        counts[sev] += 1
    print("=" * 70)
    print("AUDIT CAPITOLATI — validità dati")
    print("=" * 70)
    for sev, scope, msg in findings:
        if only_err and sev != "ERROR":
            continue
        print(f"[{sev:5s}] {scope}: {msg}")
    print("-" * 70)
    print(f"ERROR={counts['ERROR']}  WARN={counts['WARN']}  INFO={counts['INFO']}  "
          f"(totale {sum(counts.values())})")
