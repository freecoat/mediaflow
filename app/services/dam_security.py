"""v3.5.0-alpha.70.2 — Watermark + secure delete per asset DAM (TPN).

Strumenti security-side per la consegna asset:
  - `apply_watermark_image(path, user_email, ts) -> bytes`: overlay
    semitrasparente con user+ts su un'immagine PIL. Usato per
    download di tipo image/preview-friendly.
  - `secure_delete_file(path, passes=3)`: sovrascrittura DOD-style
    (random 3 pass) prima di unlink, scrubba metadata residui.

Watermark video / PDF / DCP: scope futuro (richiede ffmpeg / PDF libs).
Per ora solo immagini con PIL già usato per thumbnail.
"""
from __future__ import annotations
import io
import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    """Cerca un font sistema; fallback al default PIL."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/Library/Fonts/Arial.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def apply_watermark_image(
    file_path: str,
    user_email: Optional[str] = None,
    ts: Optional[datetime] = None,
    *,
    extra: Optional[str] = None,
) -> Optional[bytes]:
    """Apre l'immagine, applica un overlay watermark testuale
    (user+timestamp+extra) in basso a destra + diagonale semi-trasparente
    al centro per scoraggiare screenshot. Ritorna bytes JPEG.

    None se file non leggibile o non immagine.
    """
    try:
        img = Image.open(file_path).convert("RGBA")
    except Exception:
        return None
    w, h = img.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    ts = ts or datetime.utcnow()
    label = f"{user_email or 'anonymous'} · {ts.strftime('%Y-%m-%d %H:%M:%S')} UTC"
    if extra:
        label += f" · {extra}"
    label += " · MediaFlow TPN watermark"
    # Bottom-right footer banner
    font_small = _load_font(max(12, int(min(w, h) / 60)))
    pad = max(8, int(min(w, h) / 80))
    try:
        bbox = draw.textbbox((0, 0), label, font=font_small)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        tw, th = font_small.getsize(label) if hasattr(font_small, "getsize") else (200, 14)
    rect = [(w - tw - pad * 2, h - th - pad * 2), (w, h)]
    draw.rectangle(rect, fill=(0, 0, 0, 160))
    draw.text((w - tw - pad, h - th - pad), label, fill=(255, 255, 255, 255), font=font_small)
    # Diagonal big-watermark center
    font_big = _load_font(max(24, int(min(w, h) / 18)))
    big_label = (user_email or "TPN").upper()
    try:
        bb = draw.textbbox((0, 0), big_label, font=font_big)
        bw, bh = bb[2] - bb[0], bb[3] - bb[1]
    except Exception:
        bw, bh = (200, 30)
    # Rotated text: write to a separate layer
    text_layer = Image.new("RGBA", (bw + 20, bh + 20), (0, 0, 0, 0))
    td = ImageDraw.Draw(text_layer)
    td.text((10, 10), big_label, fill=(255, 255, 255, 80), font=font_big)
    rotated = text_layer.rotate(-30, expand=True)
    rw, rh = rotated.size
    overlay.paste(rotated, ((w - rw) // 2, (h - rh) // 2), rotated)
    out = Image.alpha_composite(img, overlay).convert("RGB")
    buf = io.BytesIO()
    out.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def secure_delete_file(file_path: str, passes: int = 3) -> bool:
    """Sovrascrittura DOD-style del file prima del rimuoverlo.
    `passes` round: random bytes ad ogni round. Idempotente: skip
    se path non esiste."""
    if not file_path or not os.path.exists(file_path):
        return True
    try:
        size = os.path.getsize(file_path)
    except OSError:
        return False
    try:
        with open(file_path, "r+b", buffering=0) as f:
            for _ in range(passes):
                f.seek(0)
                # Write random bytes in chunks (no full memory load for huge files)
                CHUNK = 1024 * 1024
                remaining = size
                while remaining > 0:
                    n = min(CHUNK, remaining)
                    f.write(secrets.token_bytes(n))
                    remaining -= n
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            # Zero pass finale per rendere il file zero-byte
            f.seek(0)
            f.truncate(0)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
    except (OSError, PermissionError):
        # Fallback: best-effort unlink
        try:
            os.remove(file_path)
        except OSError:
            return False
        return True
    try:
        os.remove(file_path)
    except OSError:
        return False
    return True


def is_image_mime(mime_type: Optional[str]) -> bool:
    return bool(mime_type and mime_type.startswith("image"))


def is_pdf_mime(mime_type: Optional[str]) -> bool:
    return bool(mime_type and "pdf" in mime_type.lower())


def apply_watermark_pdf(
    file_path: str,
    user_email: Optional[str] = None,
    ts: Optional[datetime] = None,
    *,
    extra: Optional[str] = None,
) -> Optional[bytes]:
    """v3.5.0-alpha.172.147 (audit TPN gap #4) — Stampa un watermark
    semitrasparente (user+ts+extra) su OGNI pagina di un PDF e ritorna i
    bytes del PDF watermarkato. None se non leggibile / non PDF.

    Usa PyMuPDF (fitz), già dipendenza del progetto (tech_specs_extractor).
    """
    try:
        import fitz  # PyMuPDF
    except Exception:
        return None
    ts = ts or datetime.utcnow()
    label = f"{user_email or 'anonymous'} · {ts.strftime('%Y-%m-%d %H:%M:%S')} UTC"
    if extra:
        label += f" · {extra}"
    label += " · MediaFlow TPN"
    try:
        doc = fitz.open(file_path)
    except Exception:
        return None
    try:
        for page in doc:
            rect = page.rect
            # Footer banner (basso, leggibile)
            fs = max(7.0, min(rect.width, rect.height) / 55.0)
            page.insert_text(
                fitz.Point(12, rect.height - 12),
                label,
                fontsize=fs,
                color=(0.45, 0.45, 0.45),
                fill_opacity=0.55,
                overlay=True,
            )
            # Diagonale grande al centro (scoraggia screenshot/redistribuzione)
            big = (user_email or "TPN").upper()
            page.insert_text(
                fitz.Point(rect.width * 0.18, rect.height * 0.62),
                big,
                fontsize=max(28.0, min(rect.width, rect.height) / 9.0),
                color=(0.5, 0.5, 0.5),
                fill_opacity=0.12,
                rotate=0,
                overlay=True,
            )
        out = doc.tobytes()
        return out
    except Exception:
        return None
    finally:
        doc.close()
