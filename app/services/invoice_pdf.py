"""
MediaFlow — invoice_pdf.py (v3.5.0-alpha.52)

Genera fatture PDF in formato italiano leggibile (NON XML SDI).
Layout: Cedente in alto, box destinatario, righe con IVA per riga e
sconto, riepilogo IVA per aliquota, box totale + box pagamento + IBAN
+ footer custom + bollo virtuale 2€ se applicabile (esente >77.47€).

Input: oggetto Invoice SQLAlchemy con relazione lines + snapshot popolati
da `billing.emit_invoice`. Se gli snapshot sono assenti (fatture
pre-α.52), legge dal Client/Tenant correnti come fallback.
"""
from io import BytesIO
from collections import defaultdict
from pathlib import Path
from typing import Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, HRFlowable, Image as RLImage,
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_LEFT, TA_CENTER

# Palette MediaFlow
INDIGO = colors.HexColor("#6272f5")
INDIGO_DK = colors.HexColor("#4853c8")
DARK = colors.HexColor("#1a1a2e")
GRAY = colors.HexColor("#7a8198")
GRAY_LT = colors.HexColor("#c5cad8")
LIGHT = colors.HexColor("#f5f6fa")
BAND = colors.HexColor("#eef1ff")
WHITE = colors.white

# Codici tipo documento più comuni (per visualizzazione human-readable)
DOC_TYPE_LABELS = {
    "TD01": "Fattura",
    "TD02": "Acconto / Anticipo",
    "TD04": "Nota di credito",
    "TD05": "Nota di debito",
    "TD06": "Parcella",
    "TD24": "Fattura differita",
}

FISCAL_REGIME_LABELS = {
    "RF01": "Ordinario",
    "RF02": "Contribuenti minimi",
    "RF04": "Agricoltura e attività connesse",
    "RF05": "Vendita sali e tabacchi",
    "RF11": "Agenzie viaggi e turismo",
    "RF12": "Agriturismo",
    "RF14": "Rivendita beni usati",
    "RF15": "Agenzie vendite all'asta",
    "RF16": "IVA per cassa P.A.",
    "RF17": "IVA per cassa",
    "RF19": "Forfettario",
}

# Soglia bollo virtuale 2€ su operazioni esenti / non imponibili
BOLLO_THRESHOLD = 77.47
BOLLO_AMOUNT = 2.00


def _money(v: float) -> str:
    if v is None:
        return "—"
    return f"€ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_date(d) -> str:
    if d is None:
        return "—"
    try:
        return d.strftime("%d/%m/%Y")
    except AttributeError:
        return str(d)


def _p(text, size=9, color=DARK, bold=False, align=TA_LEFT, leading=None):
    if text in (None, ""):
        text = "—"
    return Paragraph(str(text), ParagraphStyle(
        "x", fontSize=size, textColor=color,
        fontName="Helvetica-Bold" if bold else "Helvetica",
        alignment=align, leading=leading or (size + 3),
    ))


def _resolve_field(invoice, snapshot_attr: str, fallback_obj, fallback_attr: str):
    """Prefer snapshot. Se vuoto, fallback al campo corrente sull'oggetto vivo."""
    snap = getattr(invoice, snapshot_attr, None)
    if snap:
        return snap
    if fallback_obj is None:
        return None
    return getattr(fallback_obj, fallback_attr, None)


def _build_address_line(street, zip_code, city, province, country):
    """Compone una riga indirizzo elegante: 'Via X, 1 — 00100 Roma (RM), Italia'."""
    parts = []
    if street:
        parts.append(str(street).strip())
    geo_bits = []
    if zip_code:
        geo_bits.append(str(zip_code).strip())
    if city:
        c = str(city).strip()
        if province:
            c = f"{c} ({str(province).strip()})"
        geo_bits.append(c)
    if geo_bits:
        parts.append(" ".join(geo_bits))
    if country and str(country).strip().lower() not in ("italia", "italy", "it"):
        parts.append(str(country).strip())
    return ", ".join(parts) if parts else None


def generate_invoice_pdf(
    invoice,
    tenant=None,
    client=None,
    bollo_virtuale: bool = False,
) -> bytes:
    """Genera il PDF della fattura `invoice` (SQLAlchemy Invoice).

    Args:
        invoice: oggetto Invoice con relazione `lines` caricata.
        tenant: opzionale, Tenant corrente (fallback se snapshot missing).
        client: opzionale, Client corrente (fallback se snapshot missing).
        bollo_virtuale: se True, aggiunge la voce "Bollo virtuale 2€".
            Default False — il bollo è obbligatorio solo per fatture esenti
            con imponibile > 77.47€ (es. forfettari).

    Returns:
        bytes del PDF.
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=14 * mm, bottomMargin=14 * mm,
    )
    story = []

    # ── 1) Header: Cedente + Tipo doc/N°/Data ─────────────────
    cedente_name = _resolve_field(invoice, "tenant_legal_name_snap", tenant, "legal_name") \
        or (tenant.name if tenant else "MediaFlow")
    cedente_vat = _resolve_field(invoice, "tenant_vat_snap", tenant, "vat_number")
    cedente_cf = _resolve_field(invoice, "tenant_tax_code_snap", tenant, "tax_code")
    cedente_addr = _resolve_field(invoice, "tenant_address_snap", tenant, "address")
    cedente_email = _resolve_field(invoice, "tenant_email_snap", tenant, "email")
    cedente_phone = _resolve_field(invoice, "tenant_phone_snap", tenant, "phone")
    cedente_rea = _resolve_field(invoice, "tenant_rea_snap", tenant, "rea_number")
    cedente_capital = _resolve_field(invoice, "tenant_fiscal_capital_snap", tenant, "fiscal_capital")
    cedente_regime = _resolve_field(invoice, "tenant_fiscal_regime_snap", tenant, "fiscal_regime")
    cedente_sdi = _resolve_field(invoice, "tenant_sdi_snap", tenant, "sdi_code")

    # Logo opzionale
    logo_path = getattr(tenant, "logo_path", None) if tenant else None
    logo_flow = None
    if logo_path:
        try:
            p = Path(logo_path)
            if not p.is_absolute():
                p = Path.cwd() / p
            if p.exists() and p.stat().st_size < 2_000_000:
                logo_flow = RLImage(str(p), width=40 * mm, height=18 * mm, kind="proportional")
        except Exception:
            logo_flow = None

    cedente_lines = [f"<b>{cedente_name}</b>"]
    if cedente_addr:
        cedente_lines.append(str(cedente_addr).replace("\n", "<br/>"))
    fiscal_bits = []
    if cedente_vat:
        fiscal_bits.append(f"P.IVA {cedente_vat}")
    if cedente_cf and cedente_cf != cedente_vat:
        fiscal_bits.append(f"C.F. {cedente_cf}")
    if fiscal_bits:
        cedente_lines.append(" — ".join(fiscal_bits))
    if cedente_rea:
        cedente_lines.append(f"REA {cedente_rea}")
    if cedente_capital:
        cedente_lines.append(f"Cap. soc. {cedente_capital}")
    if cedente_regime:
        cedente_lines.append(f"Regime {cedente_regime} — {FISCAL_REGIME_LABELS.get(cedente_regime, '—')}")
    contact_bits = []
    if cedente_email:
        contact_bits.append(cedente_email)
    if cedente_phone:
        contact_bits.append(cedente_phone)
    if contact_bits:
        cedente_lines.append(" · ".join(contact_bits))
    cedente_html = "<br/>".join(cedente_lines)

    # Header table 2 colonne: cedente sx, doc info dx
    doc_label = DOC_TYPE_LABELS.get(invoice.doc_type or "TD01", "Fattura")
    doc_meta_html = (
        f"<font size=20 color='#6272f5'><b>{doc_label.upper()}</b></font><br/>"
        f"<br/>"
        f"<b>N° {invoice.number}</b><br/>"
        f"Emessa il {_fmt_date(invoice.issue_date)}<br/>"
        f"Scadenza: {_fmt_date(invoice.due_date)}"
    )

    # Se logo presente, prima riga con logo, seconda con cedente; altrimenti cedente unico
    if logo_flow is not None:
        header_left = [[logo_flow], [_p(cedente_html, size=8, leading=11)]]
        header_left_t = Table(header_left, colWidths=[95 * mm])
        header_left_t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 3 * mm),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ]))
    else:
        header_left_t = _p(cedente_html, size=8, leading=11)

    header = Table([
        [header_left_t, _p(doc_meta_html, size=10, align=TA_RIGHT, leading=14)],
    ], colWidths=[105 * mm, 77 * mm])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * mm),
    ]))
    story.append(header)
    story.append(HRFlowable(width="100%", thickness=1.2, color=INDIGO, spaceAfter=4 * mm))

    # ── 2) Cessionario (cliente) ───────────────────────────────
    cli_name = _resolve_field(invoice, "client_legal_name_snap", client, "name") \
        or (client.name if client else "Cliente")
    cli_vat = _resolve_field(invoice, "client_vat_snap", client, "vat_number")
    cli_cf = _resolve_field(invoice, "client_tax_code_snap", client, "tax_code")
    cli_pec = _resolve_field(invoice, "client_pec_snap", client, "pec")
    cli_sdi = _resolve_field(invoice, "client_sdi_snap", client, "sdi_code")
    cli_addr = _resolve_field(invoice, "client_address_snap", client, "address")
    cli_zip = _resolve_field(invoice, "client_zip_snap", client, "zip_code")
    cli_city = _resolve_field(invoice, "client_city_snap", client, "city")
    cli_prov = _resolve_field(invoice, "client_province_snap", client, "province")
    cli_country = _resolve_field(invoice, "client_country_snap", client, "country")

    cli_addr_line = _build_address_line(cli_addr, cli_zip, cli_city, cli_prov, cli_country)
    cli_lines = [f"<b>{cli_name}</b>"]
    if cli_addr_line:
        cli_lines.append(cli_addr_line)
    cli_fiscal_bits = []
    if cli_vat:
        cli_fiscal_bits.append(f"P.IVA {cli_vat}")
    if cli_cf and cli_cf != cli_vat:
        cli_fiscal_bits.append(f"C.F. {cli_cf}")
    if cli_fiscal_bits:
        cli_lines.append(" — ".join(cli_fiscal_bits))
    if cli_pec:
        cli_lines.append(f"PEC: {cli_pec}")
    if cli_sdi:
        cli_lines.append(f"Codice destinatario SDI: <b>{cli_sdi}</b>")
    elif cli_pec:
        cli_lines.append("Codice destinatario SDI: <b>0000000</b> (PEC)")
    cli_html = "<br/>".join(cli_lines)

    cli_box = Table([
        [_p("DESTINATARIO", size=7, color=GRAY, bold=True)],
        [_p(cli_html, size=9, leading=13)],
    ], colWidths=[182 * mm])
    cli_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BAND),
        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
        ("BOX", (0, 0), (-1, -1), 0.5, INDIGO),
    ]))
    story.append(cli_box)
    story.append(Spacer(1, 4 * mm))

    # ── 3) Righe fattura ───────────────────────────────────────
    th = lambda t, a=TA_LEFT: Paragraph(
        f"<b>{t}</b>",
        ParagraphStyle("th", fontSize=8, fontName="Helvetica-Bold",
                       textColor=WHITE, alignment=a),
    )
    body_p = lambda t, a=TA_LEFT: Paragraph(
        str(t) if t not in (None, "") else "",
        ParagraphStyle("td", fontSize=9, fontName="Helvetica",
                       textColor=DARK, alignment=a, leading=12),
    )
    right_p = lambda t: body_p(t, TA_RIGHT)
    center_p = lambda t: body_p(t, TA_CENTER)

    rows = [[
        th("Descrizione"),
        th("Q.tà", TA_RIGHT),
        th("Prezzo", TA_RIGHT),
        th("Sconto", TA_RIGHT),
        th("IVA", TA_RIGHT),
        th("Imponibile", TA_RIGHT),
    ]]
    # Riepilogo IVA per aliquota
    vat_aggr: dict[float, dict[str, float]] = defaultdict(lambda: {"imponibile": 0.0, "imposta": 0.0})
    subtotal = 0.0

    for line in invoice.lines:
        qty = line.quantity or 0.0
        up = line.unit_price or 0.0
        disc = line.discount_pct or 0.0
        vat = line.vat_rate if line.vat_rate is not None else 22.0
        gross = qty * up
        net = gross * (1.0 - disc / 100.0) if disc else gross
        subtotal += net
        vat_amount = net * vat / 100.0
        vat_aggr[vat]["imponibile"] += net
        vat_aggr[vat]["imposta"] += vat_amount
        rows.append([
            body_p(line.description or "—"),
            right_p(f"{qty:g}"),
            right_p(_money(up)),
            right_p(f"{disc:g}%" if disc else "—"),
            right_p(f"{vat:g}%"),
            right_p(_money(net)),
        ])

    line_table = Table(rows, colWidths=[78 * mm, 18 * mm, 26 * mm, 18 * mm, 16 * mm, 26 * mm], repeatRows=1)
    line_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INDIGO),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT]),
        ("GRID", (0, 0), (-1, -1), 0.3, GRAY_LT),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
    ]))
    story.append(line_table)
    story.append(Spacer(1, 4 * mm))

    # ── 4) Riepilogo IVA per aliquota ──────────────────────────
    if len(vat_aggr) > 0:
        vat_rows = [[
            th("Aliquota IVA"),
            th("Imponibile", TA_RIGHT),
            th("Imposta", TA_RIGHT),
        ]]
        for rate in sorted(vat_aggr.keys()):
            vat_rows.append([
                center_p(f"{rate:g}%"),
                right_p(_money(vat_aggr[rate]["imponibile"])),
                right_p(_money(vat_aggr[rate]["imposta"])),
            ])
        vat_table = Table(vat_rows, colWidths=[60 * mm, 35 * mm, 35 * mm])
        vat_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), DARK),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT]),
            ("GRID", (0, 0), (-1, -1), 0.3, GRAY_LT),
            ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
        ]))
        story.append(vat_table)
        story.append(Spacer(1, 3 * mm))

    # ── 5) Totali ──────────────────────────────────────────────
    vat_total = sum(v["imposta"] for v in vat_aggr.values())
    bollo = BOLLO_AMOUNT if (bollo_virtuale and subtotal > BOLLO_THRESHOLD) else 0.0
    grand_total = subtotal + vat_total + bollo

    totals_rows = [
        ["", _p("Imponibile", color=GRAY, align=TA_RIGHT), _p(_money(subtotal), align=TA_RIGHT)],
        ["", _p(f"IVA totale", color=GRAY, align=TA_RIGHT), _p(_money(vat_total), align=TA_RIGHT)],
    ]
    if bollo:
        totals_rows.append([
            "", _p("Bollo virtuale (DM 17/06/2014)", color=GRAY, align=TA_RIGHT, size=8),
            _p(_money(bollo), align=TA_RIGHT),
        ])
    totals_rows.append([
        "", _p("<b>Totale documento</b>", color=INDIGO, align=TA_RIGHT, size=12),
        _p(f"<b>{_money(grand_total)}</b>", color=INDIGO, align=TA_RIGHT, size=12),
    ])
    totals_table = Table(totals_rows, colWidths=[100 * mm, 50 * mm, 32 * mm])
    totals_table.setStyle(TableStyle([
        ("LINEABOVE", (1, -1), (-1, -1), 1.2, INDIGO),
        ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(totals_table)
    story.append(Spacer(1, 4 * mm))

    # ── 6) Box Pagamento ───────────────────────────────────────
    pay_method = invoice.payment_method or (tenant.payment_method_default if tenant else None)
    pay_terms = invoice.payment_terms_days or (tenant.payment_terms_default if tenant else None)
    iban = invoice.iban_snapshot or (tenant.iban if tenant else None)

    pay_lines = []
    if pay_method:
        pay_lines.append(f"<b>Modalità:</b> {pay_method}")
    if pay_terms:
        pay_lines.append(f"<b>Termini:</b> {pay_terms} giorni" + (
            f" — scadenza {_fmt_date(invoice.due_date)}" if invoice.due_date else ""
        ))
    if iban:
        pay_lines.append(f"<b>IBAN:</b> <font face='Courier'>{iban}</font>")
    if pay_lines:
        pay_box = Table([
            [_p("PAGAMENTO", size=7, color=GRAY, bold=True)],
            [_p("<br/>".join(pay_lines), size=9, leading=13)],
        ], colWidths=[182 * mm])
        pay_box.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
            ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
            ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
            ("BOX", (0, 0), (-1, -1), 0.4, GRAY_LT),
        ]))
        story.append(pay_box)
        story.append(Spacer(1, 4 * mm))

    # ── 7) Note + footer aziendale ─────────────────────────────
    if invoice.notes:
        story.append(_p("<b>Note:</b>", size=9, color=GRAY))
        story.append(_p(invoice.notes, size=9))
        story.append(Spacer(1, 3 * mm))

    footer_text = (tenant.invoice_footer if tenant else None)
    if footer_text:
        story.append(HRFlowable(width="100%", thickness=0.4, color=GRAY_LT, spaceBefore=2 * mm, spaceAfter=2 * mm))
        story.append(_p(footer_text, size=8, color=GRAY, leading=11))

    # Footer fisso documento
    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width="100%", thickness=0.3, color=GRAY_LT, spaceAfter=2 * mm))
    story.append(_p(
        f"Documento generato da MediaFlow · {cedente_name} · "
        f"Tipo documento {invoice.doc_type or 'TD01'} ({doc_label})",
        size=7, color=GRAY, align=TA_CENTER,
    ))

    doc.build(story)
    return buf.getvalue()
