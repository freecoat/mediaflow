"""F4 (spec 2026-06-11) — Catalogo LTO: backfill AssetMembership da MHL/CSV.

Match al registry: 1) checksum xxhash case-insensitive, 2) fallback
filename+size SOLO se univoco. Niente match → membership ORFANA
(asset_id NULL): il file vive sul tape, il collegamento arriva dopo.
Il backfill NON tocca Asset.content_state (lo fanno i ticket, esplicito).
"""
from __future__ import annotations

import csv
import io
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.models import Asset, AssetMembership, PhysicalAsset

# Mappa canonica: chiave=nome campo normalizzato, valore=set di alias header CSV
_FIELD_ALIASES: dict[str, set[str]] = {
    "filename":   {"filename", "file", "name", "file name", "file_name"},
    "size_bytes": {"size", "size_bytes", "bytes", "length", "file size"},
    "checksum":   {"checksum", "hash", "xxhash", "xxhash64", "md5", "c4id"},
    "path":       {"path", "directory", "folder", "dir"},
}


def parse_catalog_csv(data: bytes, mapping: Optional[dict] = None) -> list[dict]:
    """Parsa CSV di catalogo LTO e ritorna lista di entries normalizzate.

    Ogni entry: {filename, size_bytes (int|None), checksum (str|None), path (str|None)}.

    Risoluzione header (priorità):
      1. mapping esplicito {header_col: campo_canonico}
      2. alias case-insensitive via _FIELD_ALIASES

    Raises ValueError se il campo 'filename' non è risolvibile.

    Args:
        data: contenuto CSV in bytes.
        mapping: mapping opzionale {nome_colonna_csv: nome_campo_canonico}.
    """
    # Decodifica con BOM tolerance
    text = data.decode("utf-8-sig", errors="replace")

    # Rilevamento delimitatore su primo KB
    sample = text[:1024]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)

    if reader.fieldnames is None:
        raise ValueError("CSV vuoto o senza header: campo 'filename' non risolvibile")

    # Costruisce mappa colonna_header → campo_canonico
    col_map: dict[str, str] = {}
    for header in reader.fieldnames:
        h_norm = header.lower().strip()
        # 1. mapping esplicito ha precedenza
        if mapping and header in mapping:
            col_map[header] = mapping[header]
            continue
        # 2. alias automatici
        for campo, aliases in _FIELD_ALIASES.items():
            if h_norm in aliases:
                col_map[header] = campo
                break

    # Verifica che 'filename' sia risolvibile
    resolved_fields = set(col_map.values())
    if "filename" not in resolved_fields:
        raise ValueError(
            "Campo 'filename' non risolvibile nell'header CSV. "
            f"Colonne trovate: {list(reader.fieldnames)}. "
            "Usa il parametro 'mapping' per specificare la colonna."
        )

    entries: list[dict] = []
    for row in reader:
        # Costruisce entry con i campi risolti
        resolved: dict[str, str | None] = {}
        for header, campo in col_map.items():
            val = (row.get(header) or "").strip() or None
            resolved[campo] = val

        # Normalizza size_bytes: tollerante, non-numerico → None
        size_raw = resolved.get("size_bytes")
        size_int: int | None = None
        if size_raw is not None:
            try:
                size_int = int(size_raw.replace(",", "").replace(" ", ""))
            except (ValueError, AttributeError):
                size_int = None

        # Path: fallback su filename se assente
        path_val = resolved.get("path") or resolved.get("filename")

        entries.append({
            "filename": resolved.get("filename"),
            "size_bytes": size_int,
            "checksum": resolved.get("checksum"),
            "path": path_val,
        })

    return entries


def ingest_catalog_entries(
    db: Session,
    physical_asset: PhysicalAsset,
    entries: list[dict],
    *,
    user_id: Optional[int] = None,
) -> dict:
    """Crea AssetMembership per ogni entry del catalogo LTO/CSV.

    Strategia di match (nell'ordine):
      1. Checksum xxhash case-insensitive → match preciso.
      2. Fallback filename + file_size: se risultato univoco → match,
         altrimenti orfana.
      3. Nessun match → membership orfana (asset_id=None).

    Dedup: entries già presenti (per checksum o per path_on_media quando
    checksum è assente) vengono skippate senza creare duplicati.

    Il service NON fa commit: responsabilità del chiamante.

    Returns:
        dict {"matched": int, "orphan": int, "skipped": int}
    """
    tape_id = physical_asset.id
    tenant_id = physical_asset.tenant_id

    # Carica membership attive del tape per dedup
    existing_memberships = (
        db.execute(
            select(AssetMembership).where(
                AssetMembership.physical_asset_id == tape_id,
                AssetMembership.removed_at.is_(None),
            )
        )
        .scalars()
        .all()
    )

    # Set di checksum già presenti (lowercase) per dedup rapido
    existing_checksums: set[str] = set()
    # Set di path_on_media (lowercase) per dedup quando checksum assente
    # NOTA: il dedup per path si applica SOLO su path reali (non sintetici da filename)
    existing_paths: set[str] = set()

    for m in existing_memberships:
        if m.checksum:
            existing_checksums.add(m.checksum.lower())
        if m.path_on_media:
            existing_paths.add(m.path_on_media.lower())

    matched = 0
    orphan = 0
    skipped = 0

    for entry in entries:
        checksum = entry.get("checksum")
        filename = entry.get("filename")
        size_bytes = entry.get("size_bytes")
        real_path = entry.get("path")           # path reale dall'entry (può essere None)
        path = real_path or filename            # path_on_media da salvare

        checksum_lower = checksum.lower() if checksum else None

        # ── Dedup ────────────────────────────────────────────────────────────
        # 1. Dedup per checksum (case-insensitive)
        if checksum_lower and checksum_lower in existing_checksums:
            skipped += 1
            continue
        # 2. Dedup per path SOLO se l'entry ha un path reale (non sintetico da filename)
        #    Se non c'è né checksum né path reale → nessun dedup (meglio duplicato che perdita)
        if not checksum_lower and real_path and real_path.lower() in existing_paths:
            skipped += 1
            continue

        # ── Ricerca Asset nel registry ────────────────────────────────────────
        asset_id: int | None = None

        if checksum_lower:
            # Match 1: checksum xxhash case-insensitive
            asset = db.execute(
                select(Asset).where(
                    Asset.tenant_id == tenant_id,
                    func.lower(Asset.checksum_xxhash) == checksum_lower,
                )
            ).scalars().first()
            if asset:
                asset_id = asset.id

        if asset_id is None and filename and size_bytes is not None:
            # Match 2: fallback filename + file_size (solo se univoco)
            candidates = (
                db.execute(
                    select(Asset).where(
                        Asset.tenant_id == tenant_id,
                        Asset.original_name == filename,
                        Asset.file_size == size_bytes,
                    )
                )
                .scalars()
                .all()
            )
            if len(candidates) == 1:
                asset_id = candidates[0].id
            # len > 1 → ambiguo → rimane orfana

        # ── Crea membership ───────────────────────────────────────────────────
        membership = AssetMembership(
            tenant_id=tenant_id,
            physical_asset_id=tape_id,
            asset_id=asset_id,
            path_on_media=path,
            checksum=checksum,
            file_size=size_bytes,
            added_by_user_id=user_id,
        )
        db.add(membership)

        # Aggiorna set dedup per entries successive nello stesso batch
        if checksum_lower:
            existing_checksums.add(checksum_lower)
        # Aggiorna paths solo se path reale (coerente con la logica di dedup sopra)
        if real_path:
            existing_paths.add(real_path.lower())

        if asset_id is not None:
            matched += 1
        else:
            orphan += 1

    db.flush()
    return {"matched": matched, "orphan": orphan, "skipped": skipped}
