"""Guardia classificazione famiglie deliveries (scripts/migrate_deliveries_pricing).

La classify() mappa nome voce-bucket -> (is_audio, price_key). Se i nomi dei
bucket cambiano o si aggiungono famiglie, questi casi limite proteggono dal
mis-routing reparto/prezzo.
"""
import importlib.util
import pathlib

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "migrate_deliveries_pricing",
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "migrate_deliveries_pricing.py",
)
mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mod)
classify = mod.classify
P = mod.P


@pytest.mark.parametrize("name,is_audio,key", [
    # Audio → Suono
    ("Full Mix (Final Mix) / 5.1 SMPTE", True, "full_mix"),
    ("DM&E (Dialogue + M&E) / 5.1 SMPTE", True, "dme_min"),
    ("M&E (Music + Effects) / Stereo 2.0", True, "me"),
    ("Stems (DME bundle) / 5.1 SMPTE", True, "stems_bundle"),
    ("Optional Audio (AD/VI) / Mono 1.0", True, "opt_audio"),
    ("Dialogue Stem / 5.1 SMPTE", True, "stem_single"),
    ("Music Stem", True, "stem_single"),
    # Sottotitoli / altro → DI
    ("Subtitle Sidecar (EBU-STL)", False, "subtitle"),
    ("KDM / DKDM", False, "kdm"),
    ("Optical Disc Image (ISO)", False, "iso"),
    ("Document (PDF/XLS/DOC)", False, "document"),
    # Video → DI
    ("DCP SMPTE / JPEG 2000 (DCP)", False, "dcp_2k"),
    ("DCP Interop / JPEG 2000 (DCP) / 4K DCI Full", False, "dcp_4k"),
    ("IMF App 2 / JPEG 2000 P-HT (IMF) / UHD 3840 / HLG", False, "imf"),
    ("MXF OP1a", False, "mxf_hd"),
    ("MXF OP1a / XAVC Intra Class 300 / UHD 3840 / HLG", False, "mxf_uhd"),
    ("MXF OP1a / MPEG-2 (XDCam IMX) / SD PAL 576i/p", False, "sd_master"),
    ("MP4 / H.265 Main / HD 1080p", False, "mp4_web"),
    ("MP4 / MPEG-2 (XDCam IMX) / SD PAL 576i/p", False, "sd_master"),
    ("QuickTime / Apple ProRes 422 HQ", False, "pr422_hd"),
    ("QuickTime / Apple ProRes 422 HQ / UHD 3840 / HDR10", False, "pr422_uhd"),
    ("QuickTime / Apple ProRes 4444 / UHD 3840 / Dolby Vision", False, "pr4444"),
    ("QuickTime / Apple ProRes 4444 XQ / HD 1080p", False, "pr4444_xq"),
    ("QuickTime / H.264 High Profile / 2K DCI Scope", False, "mp4_web"),
    ("QuickTime / Apple ProRes 422 / SD NTSC 480i/p", False, "sd_master"),
    ("Image Sequence DPX / 4K DCI Full", False, "imgseq"),
])
def test_classify(name, is_audio, key):
    assert classify(name) == (is_audio, key)


def test_audio_keys_are_audio_families():
    # tutte le chiavi audio devono esistere in P e i video no-clash
    for k in ("full_mix", "dme_min", "me", "stems_bundle", "opt_audio", "stem_single"):
        assert k in P


def test_document_is_zero_priced():
    assert P["document"] == (0, 0, 0)


def test_dcp_4k_dearer_than_2k():
    assert P["dcp_4k"][0] > P["dcp_2k"][0]
    assert P["pr4444_xq"][0] > P["pr4444"][0] > P["pr422_hd"][0]
