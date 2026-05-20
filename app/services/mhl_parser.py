"""
MediaFlow — MHL (Media Hash List) parser per ingest deliverable LTO.

Supporta v1.x (XML root <hashlist>) e v2.x (XML root <hash_list>). Parsing
tollerante: estrae name + size + checksum + path quando presenti, ignora
tag sconosciuti.

Output: lista di dict {filename, size_bytes, checksum, path, hash_date}.

Use case (v3.5.0-alpha.172.3 Restructure):
- Operator scrive LTO con Yoyotta -> exports .mhl
- POST /ingest/yoyotta-mhl con file MHL + job_id + deliverable_id (opzionale)
- Parser elenca file + crea PhysicalAsset (kind=LTO) + auto-link
  deliverable (quantity_delivered++)

NOTA: nessuna dipendenza esterna. Usa xml.etree.ElementTree stdlib.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Optional

log = logging.getLogger(__name__)


def _text(el, *names: str) -> Optional[str]:
    """Cerca il primo tag con uno dei nomi (case-insensitive), ritorna text
    o None se non trovato."""
    for n in names:
        for child in el:
            tag = child.tag.split("}")[-1].lower()  # strip namespace
            if tag == n.lower():
                return (child.text or "").strip() or None
    return None


def parse_mhl_bytes(data: bytes) -> dict:
    """Parsa contenuto MHL e ritorna dict con metadata e lista entries.

    Output:
        {
          "version": "1.0" | "2.0" | "unknown",
          "creator": "Yoyotta" | None,
          "entries": [
            {"filename": str, "size_bytes": int | None,
             "checksum": str | None, "checksum_type": "xxhash64|md5|sha1",
             "path": str | None, "hash_date": str | None},
            ...
          ]
        }
    """
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise ValueError(f"MHL XML parse error: {e}")

    root_tag = root.tag.split("}")[-1].lower()
    if root_tag not in ("hashlist", "hash_list"):
        raise ValueError(
            f"MHL root tag '{root_tag}' non riconosciuto. Attesi 'hashlist' o 'hash_list'."
        )

    version = "1.0" if root_tag == "hashlist" else "2.0"
    # Creator (Yoyotta lo mette in <creatorinfo><tool>Yoyotta</tool></creatorinfo>)
    creator = None
    for child in root.iter():
        tag = child.tag.split("}")[-1].lower()
        if tag in ("tool", "creator", "creator_name"):
            if (child.text or "").strip():
                creator = child.text.strip()
                break

    entries = []
    # MHL v1 ha <hash> diretti; v2 ha <hashes><hash>
    hash_elements = []
    for child in root.iter():
        tag = child.tag.split("}")[-1].lower()
        if tag == "hash":
            hash_elements.append(child)

    for h in hash_elements:
        filename = _text(h, "file", "filename", "name", "path")
        size_raw = _text(h, "size", "filesize", "size_bytes")
        size_bytes = None
        if size_raw:
            try:
                size_bytes = int(size_raw)
            except (ValueError, TypeError):
                size_bytes = None
        checksum = None
        checksum_type = None
        for ct in ("xxhash64", "xxhash", "md5", "sha1", "sha256", "checksum"):
            val = _text(h, ct)
            if val:
                checksum = val
                checksum_type = ct if ct != "checksum" else "unknown"
                break
        hash_date = _text(h, "hashdate", "lastmodificationdate", "creationdate")
        path = filename  # alias
        entries.append({
            "filename": filename,
            "path": path,
            "size_bytes": size_bytes,
            "checksum": checksum,
            "checksum_type": checksum_type,
            "hash_date": hash_date,
        })

    return {
        "version": version,
        "creator": creator,
        "entries": entries,
        "n_files": len(entries),
        "total_size_bytes": sum(e["size_bytes"] or 0 for e in entries),
    }


def parse_csv_lto_bytes(data: bytes) -> dict:
    """Parser semplificato per CSV LTO report (formato custom MediaFlow).

    Atteso header: filename,size_bytes,checksum[,checksum_type][,tape_label]
    Tollera quotedfields e space dopo virgole.

    Output schema uguale a parse_mhl_bytes.
    """
    import csv
    import io
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    entries = []
    for row in reader:
        size_raw = (row.get("size_bytes") or row.get("size") or "").strip()
        size_bytes = None
        if size_raw:
            try:
                size_bytes = int(size_raw)
            except ValueError:
                size_bytes = None
        entries.append({
            "filename": (row.get("filename") or row.get("file") or row.get("name") or "").strip() or None,
            "path": (row.get("path") or row.get("filename") or "").strip() or None,
            "size_bytes": size_bytes,
            "checksum": (row.get("checksum") or row.get("md5") or row.get("xxhash") or "").strip() or None,
            "checksum_type": (row.get("checksum_type") or "unknown").strip(),
            "hash_date": (row.get("hash_date") or row.get("date") or "").strip() or None,
        })
    return {
        "version": "csv",
        "creator": "csv_lto",
        "entries": entries,
        "n_files": len(entries),
        "total_size_bytes": sum(e["size_bytes"] or 0 for e in entries),
    }
