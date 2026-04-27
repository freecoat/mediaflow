"""
MediaFlow — quote_pdf.py
Genera PDF quotazione in italiano con header tenant, raggruppamento dinamico per
categoria, subtotali, sconti multilivello e box totali.
"""
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT

INDIGO = colors.HexColor("#6272f5")
INDIGO_DK = colors.HexColor("#4853c8")
DARK   = colors.HexColor("#1a1a2e")
GRAY   = colors.HexColor("#7a8198")
GRAY_LT = colors.HexColor("#c5cad8")
LIGHT  = colors.HexColor("#f5f6fa")
LIGHTER = colors.HexColor("#fbfbfd")
BAND   = colors.HexColor("#eef1ff")
ROSE   = colors.HexColor("#e11d48")
ROSE_BG = colors.HexColor("#fff5f7")
WHITE  = colors.white

CATEGORY_FALLBACK = "Altro"


def _p(text, size=9, color=DARK, bold=False, align=TA_LEFT, leading=None):
    return Paragraph(str(text) if text not in (None, "") else "—", ParagraphStyle(
        "x", fontSize=size, textColor=color,
        fontName="Helvetica-Bold" if bold else "Helvetica",
        alignment=align, leading=leading or (size + 3)))


def _fmt(n):
    if n is None: return "—"
    return f"€ {n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_date(d):
    if d is None: return "—"
    try:
        return d.strftime("%d/%m/%Y")
    except AttributeError:
        return str(d)


def _line_category(line) -> str:
    override = (getattr(line, "category_override", None) or "").strip()
    if override:
        return override
    if line.price_item and line.price_item.category:
        return line.price_item.category.name
    return CATEGORY_FALLBACK


def _get_tenant_info(quote):
    """Ricava i dati del tenant dal client/quote. Fallback se la relazione non c'è."""
    try:
        from app.database import SessionLocal
        from app.models.models import Tenant
        with SessionLocal() as db:
            t = db.query(Tenant).first()
            if t:
                return {
                    "name": t.legal_name or t.name,
                    "vat": t.vat_number, "address": t.address,
                    "email": t.email, "phone": t.phone, "website": t.website,
                }
    except Exception:
        pass
    return {"name": "MediaFlow", "vat": None, "address": None,
            "email": None, "phone": None, "website": None}


def generate_quote_pdf(quote) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=14*mm, rightMargin=14*mm, topMargin=14*mm, bottomMargin=14*mm,
        title=f"Quotazione {quote.number}", author="MediaFlow")
    story = []

    tenant = _get_tenant_info(quote)

    # ── Header: brand a sinistra, numero quote a destra ───────
    tenant_lines = []
    if tenant["name"]:    tenant_lines.append(f"<b>{tenant['name']}</b>")
    if tenant["address"]: tenant_lines.append(tenant['address'])
    contact_bits = []
    if tenant["email"]:   contact_bits.append(tenant["email"])
    if tenant["phone"]:   contact_bits.append(tenant["phone"])
    if tenant["website"]: contact_bits.append(tenant["website"])
    if contact_bits: tenant_lines.append(" · ".join(contact_bits))
    if tenant["vat"]:     tenant_lines.append(f"P.IVA {tenant['vat']}")
    tenant_block = Paragraph("<br/>".join(tenant_lines) or "MediaFlow",
        ParagraphStyle("tt", fontSize=8, textColor=GRAY, leading=11))

    quote_meta = [
        f'<font size="22" color="#6272f5"><b>QUOTAZIONE</b></font>',
        f'<font size="14" color="#1a1a2e"><b>{quote.number}</b></font>'
        + (f'<font size="9" color="#7a8198">  ·  versione {quote.version}</font>' if quote.version and quote.version != 1 else ''),
    ]
    quote_block = Paragraph("<br/>".join(quote_meta),
        ParagraphStyle("qm", fontSize=10, alignment=TA_RIGHT, leading=22))

    hdr = Table([[tenant_block, quote_block]], colWidths=[100*mm, 80*mm])
    hdr.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP")]))
    story.append(hdr)
    story.append(Spacer(1, 3*mm))
    story.append(HRFlowable(width="100%", thickness=2, color=INDIGO, spaceAfter=4*mm))

    # ── Blocco cliente + dati emissione su due colonne ─────────
    client = quote.client
    client_lines = []
    if client:
        client_lines.append(f"<b>{client.name}</b>")
        if client.address:    client_lines.append(client.address)
        ll = ", ".join(filter(None, [client.city, client.country]))
        if ll: client_lines.append(ll)
        if client.vat_number: client_lines.append(f"P.IVA {client.vat_number}")
        if client.contact_name:
            who = client.contact_name + (f" — {client.contact_role}" if client.contact_role else "")
            client_lines.append(who)
    cli_para = Paragraph("<br/>".join(client_lines) or "—",
        ParagraphStyle("cl", fontSize=9, leading=12, textColor=DARK))

    meta_data = [
        [_p("Cliente", 7, GRAY, bold=True), cli_para],
        [_p("Titolo", 7, GRAY, bold=True), _p(quote.title or "—", 9, DARK, bold=True)],
        [_p("Data emissione", 7, GRAY, bold=True), _p(_fmt_date(quote.issue_date), 9)],
        [_p("Validità", 7, GRAY, bold=True),
         _p(f"fino al {_fmt_date(quote.valid_until)}" if quote.valid_until else "—", 9)],
    ]
    mt = Table(meta_data, colWidths=[28*mm, 152*mm])
    mt.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("TOPPADDING", (0,0), (-1,-1), 1.2*mm),
        ("BOTTOMPADDING", (0,0), (-1,-1), 1.2*mm),
        ("LINEBELOW", (0,0), (-1,-2), 0.3, GRAY_LT),
    ]))
    story.append(mt)
    story.append(Spacer(1, 5*mm))

    # ── Critical assumptions (specs tecniche del progetto) ────
    if any([quote.production_material, quote.length_minutes, quote.delivery_format, quote.shooting_days]):
        assume_data = []
        if quote.production_material:
            assume_data.append([_p("Materiale di partenza", 8, GRAY, bold=True),
                                _p(quote.production_material, 8)])
        if quote.length_minutes:
            assume_data.append([_p("Durata", 8, GRAY, bold=True),
                                _p(f"{quote.length_minutes} min @ {quote.fps or '?'} fps", 8)])
        if quote.delivery_format:
            assume_data.append([_p("Formato consegna", 8, GRAY, bold=True),
                                _p(quote.delivery_format, 8)])
        if quote.shooting_days:
            assume_data.append([_p("Giorni di ripresa", 8, GRAY, bold=True),
                                _p(str(quote.shooting_days), 8)])
        at = Table(assume_data, colWidths=[40*mm, 140*mm])
        at.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), BAND),
            ("TOPPADDING", (0,0), (-1,-1), 1.5*mm),
            ("BOTTOMPADDING", (0,0), (-1,-1), 1.5*mm),
            ("LEFTPADDING", (0,0), (-1,-1), 3*mm),
        ]))
        story.append(_p("PREMESSE TECNICHE", 8, INDIGO_DK, bold=True))
        story.append(Spacer(1, 1.2*mm))
        story.append(at)
        story.append(Spacer(1, 4*mm))

    # ── Tabella righe quotazione ──────────────────────────────
    col_w = [62*mm, 16*mm, 14*mm, 24*mm, 18*mm, 28*mm]
    header_row = [
        _p("Descrizione", 8, WHITE, bold=True),
        _p("Q.tà", 8, WHITE, bold=True, align=TA_RIGHT),
        _p("Unità", 8, WHITE, bold=True, align=TA_RIGHT),
        _p("Prezzo/Un. €", 8, WHITE, bold=True, align=TA_RIGHT),
        _p("Sconto %", 8, WHITE, bold=True, align=TA_RIGHT),
        _p("Totale €", 8, WHITE, bold=True, align=TA_RIGHT),
    ]
    rows = [header_row]
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), INDIGO),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, INDIGO_DK),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHTER]),
        ("TOPPADDING", (0, 0), (-1, -1), 2*mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2*mm),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.5*mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.5*mm),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]

    cat_disc = quote.category_discounts or {}
    sorted_lines = sorted(quote.lines, key=lambda l: l.sort_order)
    groups: dict[str, list] = {}
    group_order = []
    for line in sorted_lines:
        cat = _line_category(line)
        if cat not in groups:
            groups[cat] = []
            group_order.append(cat)
        groups[cat].append(line)

    for cat in group_order:
        cat_lines = groups[cat]
        # Header categoria
        idx = len(rows)
        rows.append([_p(cat.upper(), 9, INDIGO_DK, bold=True),
                     _p(""), _p(""), _p(""), _p(""), _p("")])
        style_cmds.append(("BACKGROUND", (0, idx), (-1, idx), BAND))
        style_cmds.append(("SPAN", (0, idx), (4, idx)))
        style_cmds.append(("LINEBELOW", (0, idx), (-1, idx), 0.3, INDIGO))

        for line in cat_lines:
            disc_str = f"{(line.line_discount_pct or 0)*100:.1f}%" if line.line_discount_pct else "—"
            rows.append([
                _p(line.description, 8) if not line.detail else
                    Paragraph(f"<b>{line.description}</b><br/><font size='7' color='#7a8198'>{line.detail}</font>",
                              ParagraphStyle("x2", fontSize=8, fontName="Helvetica", leading=11)),
                _p(f"{line.quantity:g}", 8, align=TA_RIGHT),
                _p(line.unit, 8, align=TA_RIGHT),
                _p(_fmt(line.unit_price), 8, align=TA_RIGHT),
                _p(disc_str, 8, align=TA_RIGHT, color=ROSE if line.line_discount_pct else GRAY),
                _p(_fmt(line.total), 8, DARK, bold=True, align=TA_RIGHT),
            ])

        # Subtotale categoria
        cat_subtotal = sum(l.total for l in cat_lines)
        sub_idx = len(rows)
        rows.append([
            _p(f"Subtotale {cat}", 8, DARK, bold=True, align=TA_RIGHT),
            _p(""), _p(""), _p(""), _p(""),
            _p(_fmt(cat_subtotal), 8, DARK, bold=True, align=TA_RIGHT),
        ])
        style_cmds.append(("SPAN", (0, sub_idx), (4, sub_idx)))
        style_cmds.append(("BACKGROUND", (0, sub_idx), (-1, sub_idx), LIGHT))
        style_cmds.append(("LINEABOVE", (0, sub_idx), (-1, sub_idx), 0.4, GRAY_LT))

        # Sconto categoria (se presente)
        cd = cat_disc.get(cat, 0)
        if cd:
            disc_amount = cat_subtotal * cd
            d_idx = len(rows)
            rows.append([
                _p(f"Sconto categoria ({cd*100:.1f}%)", 8, ROSE, align=TA_RIGHT),
                _p(""), _p(""), _p(""), _p(""),
                _p("−" + _fmt(disc_amount), 8, ROSE, bold=True, align=TA_RIGHT),
            ])
            style_cmds.append(("SPAN", (0, d_idx), (4, d_idx)))
            style_cmds.append(("BACKGROUND", (0, d_idx), (-1, d_idx), ROSE_BG))

    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle(style_cmds))
    story.append(tbl)
    story.append(Spacer(1, 6*mm))

    # ── Box totali (riquadro a destra) ────────────────────────
    pkg_pct = abs((quote.package_discount or 0) * 100)
    pkg_amount = (quote.subtotal or 0) - (quote.total_after_discount or 0)
    line_cat_disc_total = (quote.subtotal_gross or 0) - (quote.subtotal or 0)
    vat_amount = (quote.total_with_vat or 0) - (quote.total_after_discount or 0)

    totals_rows = [
        [_p("Totale lordo", 9, GRAY, align=TA_RIGHT),
         _p(_fmt(quote.subtotal_gross), 9, GRAY, align=TA_RIGHT)],
    ]
    if line_cat_disc_total > 0.005:
        totals_rows.append(
            [_p("Sconti voci + categorie", 9, ROSE, align=TA_RIGHT),
             _p("−" + _fmt(line_cat_disc_total), 9, ROSE, align=TA_RIGHT)]
        )
    totals_rows.append(
        [_p("Subtotale", 9, DARK, bold=True, align=TA_RIGHT),
         _p(_fmt(quote.subtotal), 9, DARK, bold=True, align=TA_RIGHT)]
    )
    if pkg_pct > 0.05:
        totals_rows.append(
            [_p(f"Sconto pacchetto ({pkg_pct:.1f}%)", 9, ROSE, align=TA_RIGHT),
             _p("−" + _fmt(pkg_amount), 9, ROSE, align=TA_RIGHT)]
        )
    totals_rows.extend([
        [_p("Totale netto (base IVA)", 9, DARK, bold=True, align=TA_RIGHT),
         _p(_fmt(quote.total_after_discount), 9, DARK, bold=True, align=TA_RIGHT)],
        [_p(f"IVA {quote.vat_rate:.0f}%", 9, GRAY, align=TA_RIGHT),
         _p(_fmt(vat_amount), 9, GRAY, align=TA_RIGHT)],
        [_p("TOTALE (IVA inclusa)", 12, WHITE, bold=True, align=TA_RIGHT),
         _p(_fmt(quote.total_with_vat), 12, WHITE, bold=True, align=TA_RIGHT)],
    ])
    last = len(totals_rows) - 1
    tt = Table(totals_rows, colWidths=[62*mm, 38*mm])
    tt_style = [
        ("TOPPADDING", (0,0), (-1,-1), 1.8*mm),
        ("BOTTOMPADDING", (0,0), (-1,-1), 1.8*mm),
        ("LEFTPADDING", (0,0), (-1,-1), 3*mm),
        ("RIGHTPADDING", (0,0), (-1,-1), 3*mm),
        ("BACKGROUND", (0,0), (-1,-2), LIGHT),
        ("BACKGROUND", (0,last), (-1,last), INDIGO),
        ("LINEABOVE", (0,last), (-1,last), 1, INDIGO_DK),
        ("BOX", (0,0), (-1,-1), 0.5, GRAY_LT),
    ]
    tt.setStyle(TableStyle(tt_style))
    # Allineiamo il box a destra usando una tabella wrapper
    spacer_cell = Paragraph("", ParagraphStyle("sp", fontSize=8))
    wrap = Table([[spacer_cell, tt]], colWidths=[80*mm, 100*mm])
    wrap.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP")]))
    story.append(wrap)

    # ── Termini & note ────────────────────────────────────────
    if quote.payment_terms:
        story.append(Spacer(1, 6*mm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=GRAY_LT, spaceAfter=2*mm))
        story.append(_p("TERMINI DI PAGAMENTO", 8, INDIGO_DK, bold=True))
        story.append(_p(quote.payment_terms, 8))

    if quote.notes:
        story.append(Spacer(1, 3*mm))
        story.append(_p("NOTE", 8, INDIGO_DK, bold=True))
        story.append(_p(quote.notes, 8))

    story.append(Spacer(1, 8*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=GRAY_LT, spaceAfter=2*mm))
    story.append(_p(
        "Si applicano le nostre Condizioni Generali di Vendita.  ·  "
        "Spese di spedizione, corriere e trasferte non sono incluse e verranno fatturate separatamente.",
        7, GRAY, align=TA_CENTER))

    doc.build(story)
    return buf.getvalue()
