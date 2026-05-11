"""v3.5.0-alpha.72 — QR code + etichetta stampabile per PhysicalAsset.

Genera:
  - PNG QR di un URL `scan/<token>` (mobile-friendly lookup)
  - Etichetta PDF/PNG stampabile con QR + label + serial + kind +
    owner info + barcode CODE128 numerico (id) per scanner laser.

Dipendenze: qrcode (già α.70.4), Pillow (già), reportlab (già).
"""
from __future__ import annotations
import io
import uuid
from typing import Optional

import qrcode
from PIL import Image, ImageDraw, ImageFont


def new_token() -> str:
    """UUID4 hex, 32 char. Univoco-quasi-sicuro (collision negligible)."""
    return uuid.uuid4().hex


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
        "/Library/Fonts/Arial.ttf",
    ]
    for p in candidates:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def generate_qr_png(scan_url: str, size_px: int = 240) -> bytes:
    """Solo QR (no testo). Per inline su pagina mobile o stampa standalone."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=2,
    )
    qr.add_data(scan_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img = img.resize((size_px, size_px))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def generate_label_png(
    *,
    scan_url: str,
    asset_label: str,
    asset_kind: str = "",
    serial_number: Optional[str] = None,
    owner_label: Optional[str] = None,
    barcode_value: Optional[str] = None,
    width_mm: float = 60,
    height_mm: float = 40,
    dpi: int = 300,
) -> bytes:
    """Etichetta stampabile: QR a sinistra, testo a destra.
    Dimensioni default 60×40mm (tipico Brother QL/Dymo). Output PNG.
    """
    # Convert mm to px @ dpi
    w_px = int(width_mm * dpi / 25.4)
    h_px = int(height_mm * dpi / 25.4)
    img = Image.new("RGB", (w_px, h_px), "white")
    draw = ImageDraw.Draw(img)
    # QR (square = height)
    qr_size = h_px - 20
    qr_bytes = generate_qr_png(scan_url, size_px=qr_size)
    qr_img = Image.open(io.BytesIO(qr_bytes))
    img.paste(qr_img, (10, 10))
    # Text area (right of QR)
    text_x = qr_size + 20
    text_y = 15
    font_big = _load_font(int(h_px / 8))
    font_med = _load_font(int(h_px / 11))
    font_small = _load_font(int(h_px / 14))
    # Label asset (big)
    draw.text((text_x, text_y), asset_label[:30], fill="black", font=font_big)
    text_y += int(h_px / 7)
    if asset_kind:
        draw.text((text_x, text_y), asset_kind.upper(), fill="#555", font=font_med)
        text_y += int(h_px / 9)
    if serial_number:
        draw.text((text_x, text_y), f"S/N: {serial_number}", fill="#555", font=font_small)
        text_y += int(h_px / 11)
    if owner_label:
        draw.text((text_x, text_y), owner_label[:30], fill="#0a64f5", font=font_small)
        text_y += int(h_px / 11)
    if barcode_value:
        # Footer testo (no barcode visivo per ora, scope futuro)
        draw.text(
            (text_x, h_px - int(h_px / 11) - 5),
            f"ID {barcode_value}",
            fill="black",
            font=font_small,
        )
    buf = io.BytesIO()
    img.save(buf, format="PNG", dpi=(dpi, dpi))
    return buf.getvalue()


def generate_delivery_note_pdf(
    *,
    title: str,
    movement_type: str,
    delivery_note_number: Optional[str],
    movement_date: str,
    from_party: Optional[str],
    from_address: Optional[str],
    to_party: Optional[str],
    to_address: Optional[str],
    asset_label: str,
    asset_kind: str,
    serial_number: Optional[str],
    package_count: int,
    total_weight_kg: Optional[float],
    dimensions_lwh_cm: Optional[str],
    contents_description: Optional[str],
    carrier: Optional[str],
    tracking_number: Optional[str],
    notes: Optional[str],
    scan_url: Optional[str] = None,
) -> bytes:
    """PDF bolla di consegna A5 (carta tipica DDT)."""
    from reportlab.lib.pagesizes import A5
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import mm

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A5)
    w, h = A5
    # Header
    c.setFont("Helvetica-Bold", 14)
    c.drawString(15 * mm, h - 18 * mm, title)
    c.setFont("Helvetica", 9)
    c.drawString(15 * mm, h - 24 * mm, f"DDT n. {delivery_note_number or '—'}  ·  Data: {movement_date}")
    # QR top-right
    if scan_url:
        try:
            qr_bytes = generate_qr_png(scan_url, size_px=200)
            from reportlab.lib.utils import ImageReader
            c.drawImage(
                ImageReader(io.BytesIO(qr_bytes)),
                w - 35 * mm, h - 35 * mm, 25 * mm, 25 * mm,
                preserveAspectRatio=True,
            )
        except Exception:
            pass
    # Mittente / Destinatario
    y = h - 45 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(15 * mm, y, "MITTENTE")
    c.drawString(85 * mm, y, "DESTINATARIO")
    c.setFont("Helvetica", 8)
    def _multiline(lines, x, y0, line_h=4):
        for line in lines:
            c.drawString(x, y0, str(line)[:55])
            y0 -= line_h * mm
        return y0
    _multiline([from_party or "—", from_address or ""], 15 * mm, y - 5 * mm)
    _multiline([to_party or "—", to_address or ""], 85 * mm, y - 5 * mm)
    # Dettaglio asset
    y = h - 75 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(15 * mm, y, "DETTAGLIO MATERIALE")
    c.setFont("Helvetica", 9)
    y -= 6 * mm
    c.drawString(15 * mm, y, f"Articolo: {asset_label}")
    y -= 5 * mm
    c.drawString(15 * mm, y, f"Tipo: {asset_kind.upper()}")
    y -= 5 * mm
    if serial_number:
        c.drawString(15 * mm, y, f"S/N: {serial_number}")
        y -= 5 * mm
    c.drawString(15 * mm, y, f"Colli: {package_count}")
    y -= 5 * mm
    if total_weight_kg:
        c.drawString(15 * mm, y, f"Peso: {total_weight_kg} kg")
        y -= 5 * mm
    if dimensions_lwh_cm:
        c.drawString(15 * mm, y, f"Dimensioni: {dimensions_lwh_cm} cm")
        y -= 5 * mm
    if contents_description:
        c.drawString(15 * mm, y, "Contenuto:")
        y -= 5 * mm
        for line in str(contents_description)[:200].split("\n"):
            c.drawString(20 * mm, y, line[:80])
            y -= 4 * mm
    # Corriere
    y -= 3 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(15 * mm, y, "SPEDIZIONE")
    c.setFont("Helvetica", 9)
    y -= 5 * mm
    c.drawString(15 * mm, y, f"Corriere: {carrier or '—'}")
    y -= 5 * mm
    if tracking_number:
        c.drawString(15 * mm, y, f"Tracking: {tracking_number}")
        y -= 5 * mm
    if notes:
        y -= 3 * mm
        c.setFont("Helvetica-Oblique", 8)
        for line in str(notes)[:200].split("\n"):
            c.drawString(15 * mm, y, line[:90])
            y -= 4 * mm
    # Firme
    c.setFont("Helvetica", 8)
    c.line(15 * mm, 25 * mm, 70 * mm, 25 * mm)
    c.drawString(15 * mm, 22 * mm, "Firma mittente")
    c.line(85 * mm, 25 * mm, 140 * mm, 25 * mm)
    c.drawString(85 * mm, 22 * mm, "Firma destinatario / data")
    c.showPage()
    c.save()
    return buf.getvalue()
