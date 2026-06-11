"""test_f4_lto_catalog.py — RED/GREEN per F4: LTO catalog ingest (checksum/nome+size, orfane, CSV).

Pattern DB: in-memory SQLite, Tenant id=1.
Helper asset: original_name, asset_type, uploaded_by, checksum_xxhash, file_size.
Helper tape: PhysicalAsset minimo (tenant_id, kind, label).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.models import (
    Base, Asset, AssetType, AssetMembership,
    PhysicalAsset, PhysicalAssetKind, Tenant,
)


# ── fixture DB ────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add(Tenant(id=1, name="Test", slug="test"))
        session.flush()
        yield session


# ── helper costruttori ─────────────────────────────────────────────────────────

def _asset(db: Session, *,
           original_name: str,
           checksum_xxhash: str | None = None,
           file_size: int = 1024,
           filename: str | None = None) -> Asset:
    a = Asset(
        tenant_id=1,
        filename=filename or original_name,
        original_name=original_name,
        file_path="",
        file_size=file_size,
        mime_type="application/octet-stream",
        asset_type=AssetType.video,
        uploaded_by=1,
        checksum_xxhash=checksum_xxhash,
    )
    db.add(a)
    db.flush()
    return a


def _tape(db: Session, *, label: str = "LTO-001") -> PhysicalAsset:
    t = PhysicalAsset(
        tenant_id=1,
        kind=PhysicalAssetKind.lto,
        label=label,
    )
    db.add(t)
    db.flush()
    return t


# ── test 1: match per checksum case-insensitive ────────────────────────────────

def test_match_checksum_case_insensitive(db):
    """Entry con checksum 'abc123' matcha Asset con 'ABC123' (case-insensitive)."""
    from app.services.lto_catalog import ingest_catalog_entries

    _asset(db, original_name="movie.mxf", checksum_xxhash="ABC123", file_size=500)
    tape = _tape(db)

    entries = [{"filename": "movie.mxf", "size_bytes": 500,
                "checksum": "abc123", "path": "/TAPE/movie.mxf"}]
    stats = ingest_catalog_entries(db, tape, entries)

    assert stats["matched"] == 1
    assert stats["orphan"] == 0
    assert stats["skipped"] == 0

    m = db.query(AssetMembership).filter_by(physical_asset_id=tape.id).one()
    assert m.asset_id is not None
    assert m.checksum == "abc123"


# ── test 2: fallback filename+size univoco ─────────────────────────────────────

def test_fallback_filename_size_unique(db):
    """Checksum mancante nell'entry ma filename+size unici → match fallback."""
    from app.services.lto_catalog import ingest_catalog_entries

    a = _asset(db, original_name="audio.wav", checksum_xxhash=None, file_size=2048)
    tape = _tape(db)

    entries = [{"filename": "audio.wav", "size_bytes": 2048,
                "checksum": None, "path": "/AUDIO/audio.wav"}]
    stats = ingest_catalog_entries(db, tape, entries)

    assert stats["matched"] == 1
    assert stats["orphan"] == 0
    m = db.query(AssetMembership).filter_by(physical_asset_id=tape.id).one()
    assert m.asset_id == a.id


# ── test 3: fallback ambiguo → orfana ─────────────────────────────────────────

def test_fallback_ambiguous_becomes_orphan(db):
    """2 asset con stesso filename+size e checksum assente → membership orfana."""
    from app.services.lto_catalog import ingest_catalog_entries

    _asset(db, original_name="sub.srt", checksum_xxhash=None, file_size=100)
    _asset(db, original_name="sub.srt", checksum_xxhash=None, file_size=100)
    tape = _tape(db)

    entries = [{"filename": "sub.srt", "size_bytes": 100,
                "checksum": None, "path": "/SUB/sub.srt"}]
    stats = ingest_catalog_entries(db, tape, entries)

    assert stats["orphan"] == 1
    assert stats["matched"] == 0
    m = db.query(AssetMembership).filter_by(physical_asset_id=tape.id).one()
    assert m.asset_id is None


# ── test 4: nessun match → membership orfana ──────────────────────────────────

def test_no_match_orphan_entry(db):
    """Nessun asset corrispondente → membership orfana con dati salvati."""
    from app.services.lto_catalog import ingest_catalog_entries

    tape = _tape(db)
    entries = [{"filename": "unknown.mxf", "size_bytes": 9999,
                "checksum": "deadbeef", "path": "/MISC/unknown.mxf"}]
    stats = ingest_catalog_entries(db, tape, entries)

    assert stats["orphan"] == 1
    assert stats["matched"] == 0
    m = db.query(AssetMembership).filter_by(physical_asset_id=tape.id).one()
    assert m.asset_id is None
    assert m.checksum == "deadbeef"
    assert m.file_size == 9999
    assert m.path_on_media == "/MISC/unknown.mxf"


# ── test 5: dedup re-ingest stesso checksum ────────────────────────────────────

def test_dedup_reingest_all_skipped(db):
    """Stessa lista ingerita due volte: seconda chiamata = tutto skipped."""
    from app.services.lto_catalog import ingest_catalog_entries

    _asset(db, original_name="dcp.mxf", checksum_xxhash="CAFE42", file_size=700)
    tape = _tape(db)
    entries = [{"filename": "dcp.mxf", "size_bytes": 700,
                "checksum": "cafe42", "path": "/DCP/dcp.mxf"}]

    stats1 = ingest_catalog_entries(db, tape, entries)
    assert stats1["matched"] == 1

    count_before = db.query(AssetMembership).filter_by(physical_asset_id=tape.id).count()
    stats2 = ingest_catalog_entries(db, tape, entries)

    assert stats2["skipped"] == 1
    assert stats2["matched"] == 0
    count_after = db.query(AssetMembership).filter_by(physical_asset_id=tape.id).count()
    assert count_after == count_before


# ── test 6: dedup per path quando checksum assente ────────────────────────────

def test_dedup_by_path_no_checksum(db):
    """Dedup per path_on_media quando checksum è assente nell'entry."""
    from app.services.lto_catalog import ingest_catalog_entries

    tape = _tape(db)
    entries = [{"filename": "render.exr", "size_bytes": 200,
                "checksum": None, "path": "/VFX/render.exr"}]

    stats1 = ingest_catalog_entries(db, tape, entries)
    assert stats1["orphan"] == 1

    stats2 = ingest_catalog_entries(db, tape, entries)
    assert stats2["skipped"] == 1
    assert db.query(AssetMembership).filter_by(physical_asset_id=tape.id).count() == 1


# ── test 7: parse_catalog_csv header standard ─────────────────────────────────

def test_parse_catalog_csv_standard_header():
    """Header 'File Name,Size,xxHash64,Path' → entries normalizzate."""
    from app.services.lto_catalog import parse_catalog_csv

    csv_data = (
        "File Name,Size,xxHash64,Path\n"
        "movie.mxf,1024,AABBCC,/TAPE/movie.mxf\n"
        "audio.wav,2048,,/TAPE/audio.wav\n"
    ).encode()

    entries = parse_catalog_csv(csv_data)
    assert len(entries) == 2

    e0 = entries[0]
    assert e0["filename"] == "movie.mxf"
    assert e0["size_bytes"] == 1024
    assert e0["checksum"] == "AABBCC"
    assert e0["path"] == "/TAPE/movie.mxf"

    e1 = entries[1]
    assert e1["filename"] == "audio.wav"
    assert e1["size_bytes"] == 2048
    assert e1["checksum"] is None


# ── test 8: CSV delimitatore ; ────────────────────────────────────────────────

def test_parse_catalog_csv_semicolon_delimiter():
    """CSV con delimitatore ';' viene rilevato automaticamente via Sniffer."""
    from app.services.lto_catalog import parse_catalog_csv

    csv_data = (
        "filename;size_bytes;checksum;path\n"
        "file.mxf;512;FF00AA;/ROOT/file.mxf\n"
    ).encode()

    entries = parse_catalog_csv(csv_data)
    assert len(entries) == 1
    assert entries[0]["filename"] == "file.mxf"
    assert entries[0]["size_bytes"] == 512


# ── test 9: header ignoto + mapping esplicito ─────────────────────────────────

def test_parse_catalog_csv_unknown_header_raises():
    """Header ignoto senza mapping esplicito → ValueError."""
    from app.services.lto_catalog import parse_catalog_csv

    csv_data = b"colX,colY\nfoo,bar\n"
    with pytest.raises(ValueError, match="filename"):
        parse_catalog_csv(csv_data)


def test_parse_catalog_csv_explicit_mapping():
    """Header ignoto + mapping esplicito {'colX':'filename','colY':'size_bytes'} → ok."""
    from app.services.lto_catalog import parse_catalog_csv

    csv_data = b"colX,colY\nfoo.mxf,999\n"
    entries = parse_catalog_csv(csv_data, mapping={"colX": "filename", "colY": "size_bytes"})
    assert len(entries) == 1
    assert entries[0]["filename"] == "foo.mxf"
    assert entries[0]["size_bytes"] == 999


# ── test 10: CSV senza colonna filename risolvibile → ValueError ───────────────

def test_parse_catalog_csv_no_filename_raises():
    """CSV con sole colonne non riconducibili a filename → ValueError."""
    from app.services.lto_catalog import parse_catalog_csv

    csv_data = b"size_bytes,checksum\n1024,ABC\n"
    with pytest.raises(ValueError, match="filename"):
        parse_catalog_csv(csv_data)


# ── test 11: size non numerica → size_bytes None, entry valida ────────────────

def test_parse_catalog_csv_non_numeric_size():
    """Size '1,5 GB' non numerica → size_bytes None, entry ritornata valida."""
    from app.services.lto_catalog import parse_catalog_csv

    csv_data = b"filename,size_bytes,checksum\nfile.mxf,1.5 GB,ABCD\n"
    entries = parse_catalog_csv(csv_data)
    assert len(entries) == 1
    assert entries[0]["size_bytes"] is None
    assert entries[0]["filename"] == "file.mxf"
    assert entries[0]["checksum"] == "ABCD"
