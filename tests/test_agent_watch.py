"""F2 — watch agent: stabilità size + package DCP/IMF + scan dir."""
from agent.watch import WatchState, is_dcp_package, scan_volume


def test_size_stable_only_after_quiet(tmp_path):
    f = tmp_path / "OUT" / "a.mov"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"x" * 10)
    st = WatchState()
    new1 = scan_volume(str(tmp_path), ["OUT"], st)
    assert new1 == []
    new2 = scan_volume(str(tmp_path), ["OUT"], st)
    assert "OUT/a.mov" in [n["rel_path"] for n in new2]
    new3 = scan_volume(str(tmp_path), ["OUT"], st)
    assert new3 == []


def test_growing_file_not_proposed(tmp_path):
    f = tmp_path / "OUT" / "b.mov"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"x" * 10)
    st = WatchState()
    scan_volume(str(tmp_path), ["OUT"], st)
    f.write_bytes(b"x" * 20)
    new = scan_volume(str(tmp_path), ["OUT"], st)
    assert new == []


def test_dcp_package_detected(tmp_path):
    pkg = tmp_path / "OUT" / "DCP_FILM"
    pkg.mkdir(parents=True)
    (pkg / "ASSETMAP").write_bytes(b"<AssetMap/>")
    (pkg / "video.mxf").write_bytes(b"x" * 100)
    assert is_dcp_package(str(pkg)) is True
    st = WatchState()
    scan_volume(str(tmp_path), ["OUT"], st)
    new = scan_volume(str(tmp_path), ["OUT"], st)
    rels = [n["rel_path"] for n in new]
    assert "OUT/DCP_FILM" in rels


def test_missing_dir_no_crash(tmp_path):
    st = WatchState()
    assert scan_volume(str(tmp_path), ["NONEXISTENT"], st) == []
