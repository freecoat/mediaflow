"""
MediaFlow — servizio DAM
Upload, validazione MIME, generazione thumbnail per immagini.
"""
import os
import uuid
import mimetypes
from pathlib import Path
from typing import Optional
from PIL import Image
from app.config import settings
from app.models import AssetType

MIME_TO_TYPE: dict[str, AssetType] = {
    "video": AssetType.video,
    "audio": AssetType.audio,
    "image": AssetType.image,
    "application/pdf": AssetType.document,
}

THUMBNAIL_SIZE = (320, 180)


def resolve_asset_type(mime_type: str) -> AssetType:
    for prefix, asset_type in MIME_TO_TYPE.items():
        if mime_type.startswith(prefix):
            return asset_type
    if mime_type == "application/pdf":
        return AssetType.document
    return AssetType.other


def save_upload(file_bytes: bytes, original_name: str) -> tuple[str, str, str]:
    """
    Salva il file su disco e restituisce (filename, file_path, mime_type).
    """
    ext = Path(original_name).suffix.lower()
    unique_name = f"{uuid.uuid4().hex}{ext}"
    dest_dir: Path = settings.upload_dir / "assets"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / unique_name

    with open(dest_path, "wb") as f:
        f.write(file_bytes)

    mime_type, _ = mimetypes.guess_type(original_name)
    return unique_name, str(dest_path), mime_type or "application/octet-stream"


def generate_thumbnail(file_path: str, mime_type: str) -> Optional[str]:
    """
    Genera una thumbnail per le immagini. Restituisce il path o None.
    """
    if not mime_type.startswith("image"):
        return None
    try:
        thumb_dir: Path = settings.upload_dir / "thumbnails"
        thumb_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(file_path).stem
        thumb_path = thumb_dir / f"{stem}_thumb.jpg"
        with Image.open(file_path) as img:
            img.thumbnail(THUMBNAIL_SIZE)
            img.convert("RGB").save(thumb_path, "JPEG", quality=80)
        return str(thumb_path)
    except Exception:
        return None


def delete_asset_files(file_path: str, thumbnail_path: Optional[str] = None) -> None:
    for p in [file_path, thumbnail_path]:
        if p and os.path.exists(p):
            os.remove(p)
