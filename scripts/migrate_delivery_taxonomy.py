"""v3.5.0-alpha.172.113 — Migrazione taxonomy delivery + seed Davinci/SMPTE.

Crea tabelle nuove (Package/Container/VideoCodec/AudioCodec/AudioChannelConfig/
AudioMixType/MixStandard/Resolution/FrameRate/DeliveryItem/AudioTrackSpec) e
popola ~110 record sistema (is_preset_global=True, tenant_id=NULL) basati su
Wikipedia (DCP/IMF/MXF/EBU R128/Atmos), DaVinci Resolve 20 Reference e
SMPTE/AMWA Application Specifications.

Idempotente: skip se tabella esiste (Base.metadata.create_all gestisce). Skip
se record name già presente.

Uso:
    .venv/Scripts/python.exe scripts/migrate_delivery_taxonomy.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import SessionLocal, engine
from app.models.models import (
    Base, Package, Container, VideoCodec, AudioCodec, AudioChannelConfig,
    AudioMixType, MixStandard, Resolution, FrameRate, DeliveryItem,
)


def _seed_unique(db, Model, records):
    """Inserisce records se name non esiste già (preset globali → tenant_id=NULL)."""
    existing = {r.name for r in db.query(Model.name).filter(Model.tenant_id.is_(None)).all()}
    added = 0
    for rec in records:
        if rec["name"] in existing:
            continue
        obj = Model(**rec, tenant_id=None, is_preset_global=True)
        db.add(obj)
        added += 1
    db.commit()
    return added


# ── PACKAGE (DCP/IMF) ──
PACKAGES = [
    {"name": "DCP Interop",   "typical_use": "cinema theatrical (legacy)", "structure_desc": "CPL+PKL+AssetMap+MXF J2K 12-bit XYZ + PCM 24bit", "sort_order": 10, "description": "Original DCI spec (deprecated). Constraints meno stringenti. Frame rates 24/48 fps @ 2K, 24 fps @ 4K."},
    {"name": "DCP SMPTE",     "typical_use": "cinema theatrical (current)", "structure_desc": "CPL+PKL+AssetMap+MXF J2K 12-bit XYZ + PCM 24bit", "sort_order": 20, "description": "Current DCI 1.4.2 spec. 2K@24/25/30/48/50/60, 4K@24/25/30. SMPTE ST 428/429."},
    {"name": "IMF App 2",     "typical_use": "studio masters (J2K)",       "structure_desc": "CPL+PKL+AssetMap+MXF OP1a J2K + MXF PCM BWF + TTML", "sort_order": 30, "description": "SMPTE ST 2067-20. J2K-based broadcast/OTT master."},
    {"name": "IMF App 2E",    "typical_use": "studio masters (J2K extended)", "structure_desc": "CPL+PKL+AssetMap+MXF OP1a J2K-P-HT/ProRes IMF + IAB Atmos + TTML IMSC", "sort_order": 40, "description": "SMPTE ST 2067-21. Estende App 2 con ProRes IMF + IAB Atmos. Netflix/Disney/BBC."},
    {"name": "IMF App 3",     "typical_use": "direct-to-consumer",         "structure_desc": "subset App2 ottimizzato D2C streaming", "sort_order": 50, "description": "Spec D2C streaming OTT."},
    {"name": "IMF App 4",     "typical_use": "cinema mezzanine",           "structure_desc": "intermediate per cinema distribution", "sort_order": 60, "description": "Cinema mezzanine fra master e DCP."},
    {"name": "IMF App 5",     "typical_use": "ACES color workflow",        "structure_desc": "ACES OCES wide-gamut HDR pipeline", "sort_order": 70, "description": "ACES OCES color workflow per HDR/wide-gamut."},
]


# ── CONTAINER ──
CONTAINERS = [
    {"name": "QuickTime",       "extension": ".mov", "op_pattern": None,     "media_kind": "mixed",     "sort_order": 10, "description": "Apple QuickTime single-file container. Supporta ProRes/H.264/HEVC/AAC/ALAC."},
    {"name": "MXF OP1a",        "extension": ".mxf", "op_pattern": "OP1a",   "media_kind": "mixed",     "sort_order": 20, "description": "SMPTE MXF Operational Pattern 1a. Complex timelines, VFR. Standard per IMF Track Files."},
    {"name": "MXF OP-Atom",     "extension": ".mxf", "op_pattern": "OP-Atom","media_kind": "mixed",     "sort_order": 30, "description": "MXF single-essence streams, edit-friendly. Usato in Avid workflows."},
    {"name": "MXF AS-11",       "extension": ".mxf", "op_pattern": "AS-11",  "media_kind": "mixed",     "sort_order": 40, "description": "AMWA MXF AS-11 broadcast delivery spec (UK DPP standard)."},
    {"name": "MP4",             "extension": ".mp4", "op_pattern": None,     "media_kind": "mixed",     "sort_order": 50, "description": "MPEG-4 Part 14. H.264/HEVC/AAC. Web/streaming/consumer."},
    {"name": "Matroska MKV",    "extension": ".mkv", "op_pattern": None,     "media_kind": "mixed",     "sort_order": 60, "description": "Open container, VBR/VFR, attachments. H.264/HEVC/VP9."},
    {"name": "WAV",             "extension": ".wav", "op_pattern": None,     "media_kind": "audio",     "sort_order": 70, "description": "RIFF WAVE PCM standard. BWF extension per metadata broadcast."},
    {"name": "AIFF",            "extension": ".aif", "op_pattern": None,     "media_kind": "audio",     "sort_order": 80, "description": "Apple Interchange File Format PCM."},
    {"name": "AC-3",            "extension": ".ac3", "op_pattern": None,     "media_kind": "audio",     "sort_order": 85, "description": "Dolby Digital container (standalone)."},
    {"name": "MP3",             "extension": ".mp3", "op_pattern": None,     "media_kind": "audio",     "sort_order": 90, "description": "MPEG-1/2 Audio Layer 3 standalone."},
    {"name": "Image Sequence DPX", "extension": ".dpx", "op_pattern": None,  "media_kind": "image_seq", "sort_order": 100, "description": "SMPTE DPX 10/16-bit log/linear. Master VFX/grading uncompressed.", "is_image_sequence": True},
    {"name": "Image Sequence EXR", "extension": ".exr", "op_pattern": None,  "media_kind": "image_seq", "sort_order": 110, "description": "OpenEXR float HDR multilayer. VFX/grading scene-linear.", "is_image_sequence": True},
    {"name": "Image Sequence TIFF","extension": ".tif", "op_pattern": None,  "media_kind": "image_seq", "sort_order": 120, "description": "TIFF 8/16-bit. Archival/post.", "is_image_sequence": True},
    {"name": "Image Sequence J2C", "extension": ".j2c", "op_pattern": None,  "media_kind": "image_seq", "sort_order": 130, "description": "JPEG 2000 codestream sequence (DCP source).", "is_image_sequence": True},
    # v3.5.0-alpha.172.126 — Container NON-AV. Non ogni deliverable è un wrapper
    # audio/video: sottotitoli, chiavi DCP, immagini disco e documenti hanno il
    # proprio "container". Risolve i falsi positivi MISSING_CONTAINER su subtitle/
    # KDM/ISO/document senza allentare R9 (ogni item ha comunque un container).
    {"name": "Subtitle Sidecar (EBU-STL)",  "extension": ".stl", "op_pattern": None, "media_kind": "subtitle", "sort_order": 200, "description": "EBU STL (Tech 3264) subtitle file. Broadcast europeo."},
    {"name": "Subtitle Sidecar (SRT)",      "extension": ".srt", "op_pattern": None, "media_kind": "subtitle", "sort_order": 210, "description": "SubRip plain-text timed text. Diffuso, semplice."},
    {"name": "Subtitle Sidecar (TTML/IMSC)","extension": ".xml", "op_pattern": None, "media_kind": "subtitle", "sort_order": 220, "description": "W3C TTML / IMSC 1.1 timed text XML. Netflix/IMF/SMPTE."},
    {"name": "Subtitle Sidecar (SCC)",      "extension": ".scc", "op_pattern": None, "media_kind": "subtitle", "sort_order": 230, "description": "Scenarist Closed Caption (CEA-608) US broadcast."},
    {"name": "Subtitle Sidecar (WebVTT)",   "extension": ".vtt", "op_pattern": None, "media_kind": "subtitle", "sort_order": 240, "description": "W3C WebVTT timed text. Web/HTML5/OTT."},
    {"name": "KDM / DKDM",                   "extension": ".xml", "op_pattern": None, "media_kind": "key",      "sort_order": 250, "description": "(D)KDM Key Delivery Message XML (SMPTE ST 430-1/-3). Sblocca DCP cifrato."},
    {"name": "Optical Disc Image (ISO)",     "extension": ".iso", "op_pattern": None, "media_kind": "disc",     "sort_order": 260, "description": "Immagine disco ISO 9660/UDF. DVD-Video / Blu-ray BDMV."},
    {"name": "Document (PDF/XLS/DOC)",       "extension": None,   "op_pattern": None, "media_kind": "document", "sort_order": 270, "description": "Documento allegato non-AV: QC report, cue sheet, metadata sheet, as-run log."},
]


# ── VIDEO CODECS ──
VIDEO_CODECS = [
    # ProRes family
    {"name": "Apple ProRes 4444 XQ",   "family": "ProRes", "profile_flavor": "4444 XQ", "typical_use": "master archival HDR", "typical_bitrate": "~500 Mbit/s HD", "is_intermediate": True, "sort_order": 10, "description": "ProRes top tier. 12-bit 4:4:4:4 con alpha. Master HDR."},
    {"name": "Apple ProRes 4444",      "family": "ProRes", "profile_flavor": "4444",    "typical_use": "master VFX",        "typical_bitrate": "~330 Mbit/s HD", "is_intermediate": True, "sort_order": 20, "description": "12-bit 4:4:4:4 con alpha. VFX compositing."},
    {"name": "Apple ProRes 422 HQ",    "family": "ProRes", "profile_flavor": "422 HQ",  "typical_use": "broadcast master",  "typical_bitrate": "~220 Mbit/s HD", "is_intermediate": True, "sort_order": 30, "description": "10-bit 4:2:2 high quality. Standard broadcast/streaming master."},
    {"name": "Apple ProRes 422",       "family": "ProRes", "profile_flavor": "422",     "typical_use": "edit/intermediate", "typical_bitrate": "~145 Mbit/s HD", "is_intermediate": True, "sort_order": 40, "description": "10-bit 4:2:2 standard. Editorial mezzanine."},
    {"name": "Apple ProRes 422 LT",    "family": "ProRes", "profile_flavor": "422 LT",  "typical_use": "lightweight intermediate", "typical_bitrate": "~100 Mbit/s HD", "is_intermediate": True, "sort_order": 50, "description": "10-bit 4:2:2 lightweight."},
    {"name": "Apple ProRes 422 Proxy", "family": "ProRes", "profile_flavor": "422 Proxy","typical_use": "offline proxy",    "typical_bitrate": "~45 Mbit/s HD",  "is_intermediate": True, "sort_order": 60, "description": "10-bit 4:2:2 proxy. Editorial offline."},
    {"name": "Apple ProRes IMF",       "family": "ProRes", "profile_flavor": "IMF",     "typical_use": "IMF App 2E master", "typical_bitrate": None, "is_intermediate": True, "sort_order": 70, "description": "ProRes variant per IMF Application 2E."},
    # DNxHR (resolution-independent)
    {"name": "Avid DNxHR LB",          "family": "DNxHR", "profile_flavor": "LB",       "typical_use": "low bandwidth proxy", "typical_bitrate": "0.9× ProRes 422 Proxy", "is_intermediate": True, "sort_order": 100, "description": "DNxHR Low Bandwidth 8-bit 4:2:2."},
    {"name": "Avid DNxHR SQ",          "family": "DNxHR", "profile_flavor": "SQ",       "typical_use": "standard quality",    "typical_bitrate": "≈ProRes 422",         "is_intermediate": True, "sort_order": 110, "description": "DNxHR Standard Quality 8-bit 4:2:2."},
    {"name": "Avid DNxHR HQ",          "family": "DNxHR", "profile_flavor": "HQ",       "typical_use": "high quality master", "typical_bitrate": "≈ProRes 422 HQ",      "is_intermediate": True, "sort_order": 120, "description": "DNxHR High Quality 8-bit 4:2:2."},
    {"name": "Avid DNxHR HQX",         "family": "DNxHR", "profile_flavor": "HQX",      "typical_use": "HDR master",          "typical_bitrate": "≈ProRes 422 HQ",      "is_intermediate": True, "sort_order": 130, "description": "DNxHR HQX 10/12-bit 4:2:2. HDR-ready."},
    {"name": "Avid DNxHR 444",         "family": "DNxHR", "profile_flavor": "444",      "typical_use": "VFX RGB master",      "typical_bitrate": "≈ProRes 4444",        "is_intermediate": True, "sort_order": 140, "description": "DNxHR 444 12-bit 4:4:4. VFX/grading."},
    # DNxHD (HD-only, legacy)
    {"name": "Avid DNxHD 145",         "family": "DNxHD", "profile_flavor": "145",      "typical_use": "HD broadcast",        "typical_bitrate": "145 Mbit/s",          "is_intermediate": True, "sort_order": 150, "description": "DNxHD 145 8-bit 4:2:2 HD."},
    {"name": "Avid DNxHD 220",         "family": "DNxHD", "profile_flavor": "220",      "typical_use": "HD broadcast HQ",     "typical_bitrate": "220 Mbit/s",          "is_intermediate": True, "sort_order": 160, "description": "DNxHD 220 8-bit 4:2:2 HD."},
    {"name": "Avid DNxHD 220x",        "family": "DNxHD", "profile_flavor": "220x",     "typical_use": "HD 10-bit master",    "typical_bitrate": "220 Mbit/s",          "is_intermediate": True, "sort_order": 170, "description": "DNxHD 220x 10-bit 4:2:2 HD."},
    {"name": "Avid DNxHD 440x",        "family": "DNxHD", "profile_flavor": "440x",     "typical_use": "HD 10-bit premium",   "typical_bitrate": "440 Mbit/s",          "is_intermediate": True, "sort_order": 180, "description": "DNxHD 440x 10-bit 4:2:2 HD high bitrate."},
    # H.264 / AVC
    {"name": "H.264 High Profile",     "family": "H.264", "profile_flavor": "High",     "typical_use": "broadcast/streaming", "typical_bitrate": "varies",              "is_intermediate": False, "sort_order": 200, "description": "AVC High Profile 8-bit 4:2:0."},
    {"name": "H.264 High 10",          "family": "H.264", "profile_flavor": "High 10",  "typical_use": "HD 10-bit broadcast", "typical_bitrate": "varies",              "is_intermediate": False, "sort_order": 210, "description": "AVC High 10 10-bit 4:2:0."},
    {"name": "H.264 High 4:2:2",       "family": "H.264", "profile_flavor": "High 4:2:2","typical_use": "broadcast contribution", "typical_bitrate": "varies",          "is_intermediate": False, "sort_order": 220, "description": "AVC High 4:2:2 Profile 10-bit 4:2:2."},
    {"name": "H.264 High 4:4:4",       "family": "H.264", "profile_flavor": "High 4:4:4","typical_use": "RGB intermediate",   "typical_bitrate": "varies",              "is_intermediate": False, "sort_order": 230, "description": "AVC High 4:4:4 Predictive 12-bit 4:4:4."},
    # HEVC / H.265
    {"name": "H.265 Main",             "family": "HEVC", "profile_flavor": "Main",      "typical_use": "streaming SDR",       "typical_bitrate": "varies",              "is_intermediate": False, "sort_order": 250, "description": "HEVC Main 8-bit 4:2:0."},
    {"name": "H.265 Main 10",          "family": "HEVC", "profile_flavor": "Main 10",   "typical_use": "streaming HDR",       "typical_bitrate": "varies",              "is_intermediate": False, "sort_order": 260, "description": "HEVC Main 10 10-bit 4:2:0. HDR10/Dolby Vision base."},
    {"name": "H.265 Main 4:2:2 10",    "family": "HEVC", "profile_flavor": "Main 4:2:2 10","typical_use": "broadcast contribution UHD", "typical_bitrate": "varies",       "is_intermediate": False, "sort_order": 270, "description": "HEVC Main 4:2:2 10 10-bit 4:2:2."},
    {"name": "H.265 Main 4:4:4 10",    "family": "HEVC", "profile_flavor": "Main 4:4:4 10","typical_use": "RGB intermediate UHD", "typical_bitrate": "varies",             "is_intermediate": False, "sort_order": 280, "description": "HEVC Main 4:4:4 10 10-bit 4:4:4."},
    # JPEG 2000 variants
    {"name": "JPEG 2000 (DCP)",        "family": "JPEG2000", "profile_flavor": "DCI",   "typical_use": "DCP video essence",  "typical_bitrate": "max 250 Mbit/s",      "is_intermediate": False, "sort_order": 300, "description": "DCI-spec JPEG 2000 12-bit XYZ 4:4:4. Required per DCP."},
    {"name": "JPEG 2000 P-HT (IMF)",   "family": "JPEG2000", "profile_flavor": "P-HT",  "typical_use": "IMF video essence",  "typical_bitrate": "varies",              "is_intermediate": False, "sort_order": 310, "description": "JPEG 2000 Part 15 High-Throughput. IMF Application 2/2E."},
    {"name": "JPEG XS",                "family": "JPEG XS",  "profile_flavor": None,    "typical_use": "low-latency mezzanine", "typical_bitrate": "varies",            "is_intermediate": True,  "sort_order": 320, "description": "ISO/IEC 21122 ultra-low-latency intra-frame. IMF App 5."},
    # XAVC
    {"name": "XAVC Intra Class 100",   "family": "XAVC",  "profile_flavor": "Intra 100","typical_use": "broadcast acquisition",   "typical_bitrate": "100 Mbit/s",     "is_intermediate": False, "sort_order": 350, "description": "Sony XAVC Intra-frame Class 100. 4K UHD broadcast."},
    {"name": "XAVC Intra Class 300",   "family": "XAVC",  "profile_flavor": "Intra 300","typical_use": "premium acquisition",     "typical_bitrate": "300 Mbit/s",     "is_intermediate": False, "sort_order": 360, "description": "Sony XAVC Intra-frame Class 300. Cinema/HDR."},
    {"name": "XAVC Long-GOP",          "family": "XAVC",  "profile_flavor": "Long-GOP", "typical_use": "broadcast distribution",  "typical_bitrate": "≤50 Mbit/s",     "is_intermediate": False, "sort_order": 370, "description": "Sony XAVC inter-frame compression."},
    {"name": "XDCam HD422 50",         "family": "XDCam", "profile_flavor": "HD422 50", "typical_use": "broadcast acquisition",   "typical_bitrate": "50 Mbit/s",      "is_intermediate": False, "sort_order": 380, "description": "Sony XDCam HD MPEG-2 Long-GOP 4:2:2 50 Mbit/s."},
    # Other
    {"name": "GoPro CineForm",         "family": "CineForm","profile_flavor": None,     "typical_use": "intermediate VFX",        "typical_bitrate": "varies",         "is_intermediate": True,  "sort_order": 400, "description": "GoPro CineForm wavelet 10/12-bit 4:2:2/4:4:4."},
    {"name": "Avid Uncompressed",      "family": "Uncompressed", "profile_flavor": None,"typical_use": "uncompressed master",     "typical_bitrate": "very high",      "is_intermediate": True,  "sort_order": 410, "description": "Avid uncompressed video 8/10/16-bit."},
    {"name": "VP9",                    "family": "VP9",   "profile_flavor": None,       "typical_use": "web streaming",           "typical_bitrate": "varies",         "is_intermediate": False, "sort_order": 420, "description": "Google VP9 open codec. YouTube primary."},
    {"name": "AV1",                    "family": "AV1",   "profile_flavor": None,       "typical_use": "streaming next-gen",      "typical_bitrate": "varies",         "is_intermediate": False, "sort_order": 430, "description": "AOMedia AV1 open codec. Netflix/YouTube/Vimeo."},
    {"name": "MPEG-2 (XDCam IMX)",     "family": "MPEG-2","profile_flavor": "IMX 50",   "typical_use": "legacy broadcast",        "typical_bitrate": "50 Mbit/s",      "is_intermediate": False, "sort_order": 440, "description": "Sony IMX MPEG-2 I-frame 50 Mbit/s. Legacy broadcast."},
    {"name": "AVC-Intra 100",          "family": "AVC-Intra", "profile_flavor": "100",  "typical_use": "broadcast acquisition",   "typical_bitrate": "100 Mbit/s",     "is_intermediate": False, "sort_order": 450, "description": "Panasonic AVC-Intra 10-bit 4:2:2 100 Mbit/s."},
]


# ── AUDIO CODECS ──
AUDIO_CODECS = [
    {"name": "PCM 16-bit Linear",       "family": "PCM",   "is_lossless": True,  "sort_order": 10, "description": "Linear PCM 16-bit uncompressed."},
    {"name": "PCM 24-bit Linear",       "family": "PCM",   "is_lossless": True,  "sort_order": 20, "description": "Linear PCM 24-bit uncompressed. Standard mastering/DCP/IMF."},
    {"name": "PCM 32-bit Float Linear", "family": "PCM",   "is_lossless": True,  "sort_order": 30, "description": "Linear PCM 32-bit float. Some intermediate workflows."},
    {"name": "Dolby Digital AC-3",      "family": "Dolby", "is_lossless": False, "sort_order": 40, "description": "Dolby AC-3 lossy compression. Broadcast/Blu-ray."},
    {"name": "Dolby E",                 "family": "Dolby", "is_lossless": False, "sort_order": 50, "description": "Dolby E broadcast distribution multichannel."},
    {"name": "Dolby Atmos Master (IAB)","family": "Dolby", "is_lossless": True,  "sort_order": 60, "description": "Immersive Audio Bitstream Atmos master. ADM BWF up to 128 ch."},
    {"name": "Dolby TrueHD",            "family": "Dolby", "is_lossless": True,  "sort_order": 70, "description": "Lossless Dolby for home Blu-ray Atmos."},
    {"name": "AAC LC",                  "family": "AAC",   "is_lossless": False, "sort_order": 80, "description": "Advanced Audio Coding Low Complexity. iTunes/streaming."},
    {"name": "AAC HE",                  "family": "AAC",   "is_lossless": False, "sort_order": 90, "description": "AAC High Efficiency (HE-AAC/aacPlus)."},
    {"name": "MP3",                     "family": "MP3",   "is_lossless": False, "sort_order": 100, "description": "MPEG-1/2 Audio Layer 3 lossy."},
    {"name": "ALAC",                    "family": "ALAC",  "is_lossless": True,  "sort_order": 110, "description": "Apple Lossless Audio Codec."},
    {"name": "FLAC",                    "family": "FLAC",  "is_lossless": True,  "sort_order": 120, "description": "Free Lossless Audio Codec."},
]


# ── AUDIO CHANNEL CONFIGURATIONS ──
AUDIO_CHANNEL_CONFIGS = [
    {"name": "Mono 1.0",              "channel_count": 1,  "spec_string": "M",                                   "is_immersive": False, "sort_order": 10,  "description": "Single channel."},
    {"name": "Stereo 2.0",            "channel_count": 2,  "spec_string": "L R",                                 "is_immersive": False, "sort_order": 20,  "description": "Standard stereo."},
    {"name": "LCR 3.0",               "channel_count": 3,  "spec_string": "L C R",                               "is_immersive": False, "sort_order": 30,  "description": "Three-channel front-stage."},
    {"name": "Quadraphonic 4.0",      "channel_count": 4,  "spec_string": "L R Ls Rs",                           "is_immersive": False, "sort_order": 40,  "description": "Legacy quadraphonic 4.0."},
    {"name": "5.0 Surround",          "channel_count": 5,  "spec_string": "L R C Ls Rs",                         "is_immersive": False, "sort_order": 50,  "description": "5-channel surround senza LFE."},
    {"name": "5.1 SMPTE",             "channel_count": 6,  "spec_string": "L R C LFE Ls Rs",                     "is_immersive": False, "sort_order": 60,  "description": "5.1 SMPTE channel order (ITU/film)."},
    {"name": "5.1 Film (Dolby)",      "channel_count": 6,  "spec_string": "L C R Ls Rs LFE",                     "is_immersive": False, "sort_order": 70,  "description": "5.1 Dolby Film channel order (alternativa)."},
    {"name": "5.1 DTS",               "channel_count": 6,  "spec_string": "L R Ls Rs C LFE",                     "is_immersive": False, "sort_order": 80,  "description": "5.1 DTS channel order."},
    {"name": "6.1 Surround",          "channel_count": 7,  "spec_string": "L R C LFE Ls Rs Cs",                  "is_immersive": False, "sort_order": 90,  "description": "5.1 + center surround."},
    {"name": "7.1 SMPTE",             "channel_count": 8,  "spec_string": "L R C LFE Lss Rss Lsr Rsr",           "is_immersive": False, "sort_order": 100, "description": "7.1 ITU-R/SMPTE side+rear surround."},
    {"name": "7.1 SDDS",              "channel_count": 8,  "spec_string": "L Lc C Rc R LFE Ls Rs",               "is_immersive": False, "sort_order": 110, "description": "Sony SDDS 7.1 cinema (5 front + LFE + 2 surround)."},
    {"name": "Atmos 5.1.4",           "channel_count": 10, "spec_string": "5.1 bed + 4 height objects",          "is_immersive": True,  "sort_order": 120, "description": "Atmos home 5.1.4 (5.1 bed + 4 overhead)."},
    {"name": "Atmos 7.1.4",           "channel_count": 12, "spec_string": "7.1 bed + 4 height objects",          "is_immersive": True,  "sort_order": 130, "description": "Atmos home 7.1.4 / cinema bed reference."},
    {"name": "Atmos 9.1.6",           "channel_count": 16, "spec_string": "9.1 bed + 6 height objects",          "is_immersive": True,  "sort_order": 140, "description": "Atmos premium home 9.1.6 (3 front height)."},
    {"name": "Atmos 7.1.2",           "channel_count": 10, "spec_string": "7.1 bed + 2 height",                  "is_immersive": True,  "sort_order": 145, "description": "Atmos soundbar/entry-level 7.1.2."},
    {"name": "22.2 (NHK)",            "channel_count": 24, "spec_string": "9 top + 10 middle + 3 bottom + 2 LFE","is_immersive": True,  "sort_order": 150, "description": "NHK 22.2 ultra-immersive (UHD-2 broadcast)."},
]


# ── AUDIO MIX TYPES ──
AUDIO_MIX_TYPES = [
    {"name": "Full Mix (Final Mix)",   "short_label": "FM",    "sort_order": 10,  "description": "Mix completo con dialogo + musica + effetti."},
    {"name": "M&E (Music + Effects)",  "short_label": "M&E",   "sort_order": 20,  "description": "Music + Effects senza dialogo. Permette dubbing internazionale."},
    {"name": "DM&E (Dialogue + M&E)",  "short_label": "DM&E",  "sort_order": 30,  "description": "Tre stem separati: Dialogue + Music + Effects."},
    {"name": "Dialogue Stem",          "short_label": "DX",    "sort_order": 40,  "description": "Solo dialogo, separato."},
    {"name": "Music Stem",             "short_label": "MX",    "sort_order": 50,  "description": "Solo musica, separato."},
    {"name": "Effects Stem",           "short_label": "FX",    "sort_order": 60,  "description": "Solo effetti sonori, separato."},
    {"name": "Foley Stem",             "short_label": "FOL",   "sort_order": 70,  "description": "Solo Foley separato."},
    {"name": "ADR Stem",               "short_label": "ADR",   "sort_order": 80,  "description": "Automated Dialogue Replacement separato."},
    {"name": "Optional Audio (HI)",    "short_label": "HI",    "sort_order": 90,  "description": "Hearing Impaired track aggiuntivo (DCP track 7)."},
    {"name": "Optional Audio (AD/VI)", "short_label": "AD",    "sort_order": 100, "description": "Audio Description / Visually Impaired Native (DCP track 8)."},
    {"name": "Optional Audio (SDH)",   "short_label": "SDH",   "sort_order": 110, "description": "Subtitles Deaf-Hard of hearing (testo, qui per ref audio)."},
    {"name": "Stems (DME bundle)",     "short_label": "DME",   "sort_order": 120, "description": "Bundle stems separati per remix/dubbing."},
]


# ── MIX STANDARDS (loudness/SPL) ──
MIX_STANDARDS = [
    {"name": "Theatrical Farfield",    "family": "theatrical", "loudness_target_lufs": None,  "true_peak_max_dbtp": None,  "spl_reference_dbc": 85.0, "standard_ref": "SMPTE/ANSI cinema", "sort_order": 10, "description": "Cinema reference mix. 85 dBC SPL Leq(m) at reference fader. Wide dynamic range."},
    {"name": "Nearfield (Home Entertainment)", "family": "home", "loudness_target_lufs": -27.0, "true_peak_max_dbtp": -2.0, "spl_reference_dbc": None, "standard_ref": None, "sort_order": 20, "description": "Home Atmos / Blu-ray. Ridotta dynamic range vs theatrical."},
    {"name": "Broadcast EBU R128",     "family": "broadcast", "loudness_target_lufs": -23.0, "true_peak_max_dbtp": -1.0, "spl_reference_dbc": None, "standard_ref": "EBU R128", "sort_order": 30, "description": "EU broadcast standard. -23 LUFS ±0.5 LU, -1 dBTP, LRA libera. ITU-R BS.1770."},
    {"name": "Broadcast ATSC A/85",    "family": "broadcast", "loudness_target_lufs": -24.0, "true_peak_max_dbtp": -2.0, "spl_reference_dbc": None, "standard_ref": "ATSC A/85 / CALM Act", "sort_order": 40, "description": "US broadcast standard. -24 LKFS, dialnorm-based. CALM Act US."},
    {"name": "Streaming OTT AES TD1004", "family": "streaming", "loudness_target_lufs": -16.0, "true_peak_max_dbtp": -2.0, "spl_reference_dbc": None, "standard_ref": "AES TD1004", "sort_order": 50, "description": "AES Technical Document 1004 streaming OTT. -16 LUFS, -2 dBTP."},
    {"name": "Netflix Atmos",          "family": "streaming", "loudness_target_lufs": -27.0, "true_peak_max_dbtp": -2.0, "spl_reference_dbc": None, "standard_ref": "Netflix Atmos spec", "sort_order": 60, "description": "Netflix Dolby Atmos delivery. -27 LKFS dialog-gated."},
    {"name": "Netflix Stereo/5.1",     "family": "streaming", "loudness_target_lufs": -27.0, "true_peak_max_dbtp": -2.0, "spl_reference_dbc": None, "standard_ref": "Netflix spec", "sort_order": 70, "description": "Netflix 5.1/Stereo deliverable. -27 LKFS dialog-gated."},
    {"name": "YouTube",                "family": "streaming", "loudness_target_lufs": -14.0, "true_peak_max_dbtp": -1.0, "spl_reference_dbc": None, "standard_ref": "YouTube normalization", "sort_order": 80, "description": "YouTube playback target -14 LUFS."},
    {"name": "Spotify",                "family": "streaming", "loudness_target_lufs": -14.0, "true_peak_max_dbtp": -1.0, "spl_reference_dbc": None, "standard_ref": "Spotify normalization", "sort_order": 90, "description": "Spotify default normal target -14 LUFS (Loud -11 / Quiet -19)."},
    {"name": "Apple Music",            "family": "streaming", "loudness_target_lufs": -16.0, "true_peak_max_dbtp": -1.0, "spl_reference_dbc": None, "standard_ref": "Apple Sound Check", "sort_order": 100, "description": "Apple Music Sound Check target -16 LUFS."},
]


# ── RESOLUTION ──
RESOLUTIONS = [
    {"name": "SD NTSC 480i/p",       "width": 720,  "height": 480,  "framing_aspect": "4:3 / 16:9",      "family": "SD",     "sort_order": 10,  "description": "Standard Definition NTSC."},
    {"name": "SD PAL 576i/p",        "width": 720,  "height": 576,  "framing_aspect": "4:3 / 16:9",      "family": "SD",     "sort_order": 20,  "description": "Standard Definition PAL."},
    {"name": "HD 720p",              "width": 1280, "height": 720,  "framing_aspect": "16:9",            "family": "HD",     "sort_order": 30,  "description": "HD 720p broadcasting."},
    {"name": "HD 1080p",             "width": 1920, "height": 1080, "framing_aspect": "16:9",            "family": "HD",     "sort_order": 40,  "description": "HD 1080p Full HD."},
    {"name": "2K DCI Flat",          "width": 1998, "height": 1080, "framing_aspect": "1.85",            "family": "2K DCI", "sort_order": 50,  "description": "DCP 2K Flat 1.85:1 active picture."},
    {"name": "2K DCI Scope",         "width": 2048, "height": 858,  "framing_aspect": "2.39",            "family": "2K DCI", "sort_order": 60,  "description": "DCP 2K Scope 2.39:1 active picture."},
    {"name": "2K DCI Full",          "width": 2048, "height": 1080, "framing_aspect": "1.90",            "family": "2K DCI", "sort_order": 70,  "description": "DCP 2K container Full 1.9:1 (frame container)."},
    {"name": "UHD 3840",             "width": 3840, "height": 2160, "framing_aspect": "16:9",            "family": "UHD",    "sort_order": 80,  "description": "UHD-1 (4K consumer / streaming / broadcast)."},
    {"name": "4K DCI Flat",          "width": 3996, "height": 2160, "framing_aspect": "1.85",            "family": "4K DCI", "sort_order": 90,  "description": "DCP 4K Flat 1.85:1 active picture."},
    {"name": "4K DCI Scope",         "width": 4096, "height": 1716, "framing_aspect": "2.39",            "family": "4K DCI", "sort_order": 100, "description": "DCP 4K Scope 2.39:1 active picture."},
    {"name": "4K DCI Full",          "width": 4096, "height": 2160, "framing_aspect": "1.90",            "family": "4K DCI", "sort_order": 110, "description": "DCP 4K container Full 1.9:1 (frame container)."},
    {"name": "8K UHD-2",             "width": 7680, "height": 4320, "framing_aspect": "16:9",            "family": "8K",     "sort_order": 120, "description": "UHD-2 (8K NHK Super Hi-Vision)."},
]


# ── FRAME RATES ──
FRAME_RATES = [
    {"name": "23.976 fps (24/1.001 NTSC film)", "fps": 23.976,  "is_drop_frame": False, "is_ntsc_family": True,  "sort_order": 10,  "description": "Film transfer to NTSC video. Standard streaming/HD master."},
    {"name": "24 fps (cinema)",                 "fps": 24.0,    "is_drop_frame": False, "is_ntsc_family": False, "sort_order": 20,  "description": "Standard cinema theatrical."},
    {"name": "25 fps (PAL)",                    "fps": 25.0,    "is_drop_frame": False, "is_ntsc_family": False, "sort_order": 30,  "description": "PAL broadcast and EU cinema."},
    {"name": "29.97 fps NDF (NTSC HD)",         "fps": 29.97,   "is_drop_frame": False, "is_ntsc_family": True,  "sort_order": 40,  "description": "NTSC video Non-Drop-Frame TC."},
    {"name": "29.97 fps DF (NTSC HD)",          "fps": 29.97,   "is_drop_frame": True,  "is_ntsc_family": True,  "sort_order": 50,  "description": "NTSC video Drop-Frame TC (broadcast standard US)."},
    {"name": "30 fps",                          "fps": 30.0,    "is_drop_frame": False, "is_ntsc_family": False, "sort_order": 60,  "description": "True 30 fps (rare; web/gaming)."},
    {"name": "48 fps HFR",                      "fps": 48.0,    "is_drop_frame": False, "is_ntsc_family": False, "sort_order": 70,  "description": "High Frame Rate cinema (Hobbit/Gemini Man)."},
    {"name": "50 fps (PAL HD)",                 "fps": 50.0,    "is_drop_frame": False, "is_ntsc_family": False, "sort_order": 80,  "description": "PAL HD broadcast / EU live sport UHD."},
    {"name": "59.94 fps NDF (NTSC HD)",         "fps": 59.94,   "is_drop_frame": False, "is_ntsc_family": True,  "sort_order": 90,  "description": "NTSC HD/UHD broadcast Non-Drop-Frame."},
    {"name": "59.94 fps DF (NTSC HD)",          "fps": 59.94,   "is_drop_frame": True,  "is_ntsc_family": True,  "sort_order": 100, "description": "NTSC HD/UHD broadcast Drop-Frame TC US."},
    {"name": "60 fps",                          "fps": 60.0,    "is_drop_frame": False, "is_ntsc_family": False, "sort_order": 110, "description": "True 60 fps web/gaming."},
    {"name": "96 fps HFR",                      "fps": 96.0,    "is_drop_frame": False, "is_ntsc_family": False, "sort_order": 120, "description": "4x cinema 24 fps. Some HFR releases."},
    {"name": "100 fps",                         "fps": 100.0,   "is_drop_frame": False, "is_ntsc_family": False, "sort_order": 130, "description": "4x PAL 25 fps."},
    {"name": "119.88 fps NDF",                  "fps": 119.88,  "is_drop_frame": False, "is_ntsc_family": True,  "sort_order": 140, "description": "4x 29.97 fps slow-motion."},
    {"name": "120 fps HFR",                     "fps": 120.0,   "is_drop_frame": False, "is_ntsc_family": False, "sort_order": 150, "description": "5x cinema HFR (Gemini Man, Avatar Way of Water 48 displayed)."},
]


def _backfill_containerless_items(db):
    """v3.5.0-alpha.172.126 — Assegna un container ai DeliveryItem non-AV che
    erano rimasti senza (subtitle/KDM/ISO/document), eliminando i falsi positivi
    MISSING_CONTAINER. Signal-driven: usa subtitle_format + euristiche sul nome.
    Idempotente: opera solo su item con container_id NULL.
    """
    def cid(name):
        c = db.query(Container).filter(Container.name == name).first()
        return c.id if c else None

    C_STL  = cid("Subtitle Sidecar (EBU-STL)")
    C_SRT  = cid("Subtitle Sidecar (SRT)")
    C_TTML = cid("Subtitle Sidecar (TTML/IMSC)")
    C_SCC  = cid("Subtitle Sidecar (SCC)")
    C_VTT  = cid("Subtitle Sidecar (WebVTT)")
    C_KDM  = cid("KDM / DKDM")
    C_ISO  = cid("Optical Disc Image (ISO)")
    C_DOC  = cid("Document (PDF/XLS/DOC)")

    items = db.query(DeliveryItem).filter(DeliveryItem.container_id.is_(None)).all()
    assigned = 0
    skipped = []
    for it in items:
        sf = (it.subtitle_format or "").upper()
        nm = (it.name or "").upper()
        nt = (it.notes or "").upper()
        target = None
        is_subtitle = bool(sf) or any(k in nm for k in ("SOTTOTITOL", "SUBTITLE", "CLOSED CAPTION", "CAPTION"))
        if is_subtitle:
            if "TTML" in sf or "IMSC" in sf or "XML" in sf:
                target = C_TTML
            elif "SRT" in sf:
                target = C_SRT
            elif "VTT" in sf or "WEBVTT" in (sf + nm):
                target = C_VTT
            elif "SCC" in sf:
                target = C_SCC
            elif "STL" in sf or "EBU" in sf:
                target = C_STL
            else:
                target = C_TTML  # default moderno se formato non riconosciuto
        elif "KDM" in nm or "KDM" in nt:
            target = C_KDM
        elif "ISO" in nm or "DISC" in nm:
            target = C_ISO
        elif any(k in nm for k in ("QC REPORT", "CUE SHEET", "REPORT", "METADATA",
                                    "AS-RUN", "AS RUN", "CHAPTER", "DOCUMENT", "SHEET")):
            target = C_DOC
        if target:
            it.container_id = target
            assigned += 1
        else:
            skipped.append((it.id, it.name))
    db.commit()
    if skipped:
        print(f"  ! {len(skipped)} item senza container e non classificabili:")
        for iid, inm in skipped[:20]:
            print(f"      id={iid} {inm!r}")
    return assigned


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("-> Creazione tabelle nuove (idempotente)...")
    Base.metadata.create_all(bind=engine)
    print("[OK] create_all OK\n")

    db = SessionLocal()
    try:
        counts = {}
        counts["Package"]            = _seed_unique(db, Package, PACKAGES)
        counts["Container"]          = _seed_unique(db, Container, CONTAINERS)
        counts["VideoCodec"]         = _seed_unique(db, VideoCodec, VIDEO_CODECS)
        counts["AudioCodec"]         = _seed_unique(db, AudioCodec, AUDIO_CODECS)
        counts["AudioChannelConfig"] = _seed_unique(db, AudioChannelConfig, AUDIO_CHANNEL_CONFIGS)
        counts["AudioMixType"]       = _seed_unique(db, AudioMixType, AUDIO_MIX_TYPES)
        counts["MixStandard"]        = _seed_unique(db, MixStandard, MIX_STANDARDS)
        counts["Resolution"]         = _seed_unique(db, Resolution, RESOLUTIONS)
        counts["FrameRate"]          = _seed_unique(db, FrameRate, FRAME_RATES)
        print("-> Seed records inseriti (skipped esistenti):")
        for k, v in counts.items():
            print(f"  + {k:22} {v} record")
        total = sum(counts.values())
        print(f"\n[OK] Totale {total} record nuovi.")

        print("\n-> Backfill container su DeliveryItem non-AV (subtitle/KDM/ISO/doc)...")
        n_bf = _backfill_containerless_items(db)
        print(f"[OK] {n_bf} item riassegnati a un container appropriato.")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
