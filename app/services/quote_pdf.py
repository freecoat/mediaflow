"""
MediaFlow — quote_pdf.py
Genera PDF quotazione in italiano con header tenant, raggruppamento dinamico per
categoria, subtotali, sconti multilivello e box totali.
"""
from io import BytesIO
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable,
    Image as RLImage,
)
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


def _fmt(n, sym="€"):
    if n is None: return "—"
    formatted = f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{sym} {formatted}"


def _conv(n, rate: float, sym: str):
    """Converte un importo BASE in valuta display e lo formatta."""
    if n is None: return "—"
    from app.services.currency import to_display
    converted = to_display(float(n), rate)
    formatted = f"{converted:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{sym} {formatted}"


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
    """Ricava i dati del tenant + branding completo (v3.5.0-alpha.66.13).

    Restituisce dict con: name + address + email + phone + website + vat
    + tagline + brand_color + show_powered_by + logo_path + document_header.
    """
    try:
        from app.database import SessionLocal
        from app.services.branding import get_branding
        with SessionLocal() as db:
            b = get_branding(db)
            return {
                "name": b["name"],
                "vat": b["vat_number"] or None,
                "address": b["address"] or None,
                "email": b["email"] or None,
                "phone": b["phone"] or None,
                "website": b["website"] or None,
                "tagline": b["tagline"],
                "brand_color": b["brand_color"],
                "show_powered_by": b["show_powered_by"],
                "logo_path": b["logo_path"],
                "document_header": b["document_header"],
            }
    except Exception:
        pass
    return {"name": "Claqo", "vat": None, "address": None,
            "email": None, "phone": None, "website": None,
            "tagline": "", "brand_color": "#6272f5",
            "show_powered_by": True, "logo_path": None, "document_header": ""}


def generate_quote_pdf(quote, *, ccy: str = None, rate: float = 1.0,
                       disclaimer: str = None) -> bytes:
    """Genera PDF quotazione.

    Parametri opzionali per valuta display:
    - ccy: codice ISO valuta display (es. "USD"). None o uguale alla valuta base → EUR, nessuna conversione.
    - rate: fx_rate_to_base (quanti EUR per 1 ccy). Usato da to_display(amount_base, rate).
    - disclaimer: testo legale da aggiungere in calce. None → nessun disclaimer.

    Backward-compatible: senza parametri si comporta esattamente come prima.
    """
    from app.services.currency import symbol as ccy_symbol
    _foreign = bool(ccy and ccy.upper() not in ("EUR", "") and rate and rate != 1.0)
    _sym = ccy_symbol(ccy) if _foreign else "€"
    _rate = rate if (_foreign and rate and rate > 0) else 1.0

    def _m(n):
        """Formatta importo: converte se valuta estera, altrimenti formato base."""
        if _foreign:
            return _conv(n, _rate, _sym)
        return _fmt(n)

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=14*mm, rightMargin=14*mm, topMargin=14*mm, bottomMargin=14*mm,
        title=f"Quotazione {quote.number}", author="Claqo")
    story = []

    tenant = _get_tenant_info(quote)
    # v3.5.0-alpha.66.13 — Branding: brand_color + tagline + logo
    brand_hex = tenant.get("brand_color") or "#6272f5"
    try:
        BRAND = colors.HexColor(brand_hex)
    except Exception:
        BRAND = INDIGO

    # ── Header: brand a sinistra, numero quote a destra ───────
    tenant_lines = []
    if tenant["name"]:    tenant_lines.append(f"<b>{tenant['name']}</b>")
    if tenant.get("tagline"): tenant_lines.append(f"<i>{tenant['tagline']}</i>")
    if tenant["address"]: tenant_lines.append(tenant['address'])
    contact_bits = []
    if tenant["email"]:   contact_bits.append(tenant["email"])
    if tenant["phone"]:   contact_bits.append(tenant["phone"])
    if tenant["website"]: contact_bits.append(tenant["website"])
    if contact_bits: tenant_lines.append(" · ".join(contact_bits))
    if tenant["vat"]:     tenant_lines.append(f"P.IVA {tenant['vat']}")
    tenant_block = Paragraph("<br/>".join(tenant_lines) or "Claqo",
        ParagraphStyle("tt", fontSize=8, textColor=GRAY, leading=11))

    # Logo opzionale: messo in colonna dedicata se presente
    logo_flow = None
    logo_path = tenant.get("logo_path")
    if logo_path:
        try:
            p = Path(logo_path) if not isinstance(logo_path, Path) else logo_path
            if p.exists() and p.stat().st_size < 5_000_000:
                logo_flow = RLImage(str(p), width=35*mm, height=16*mm, kind="proportional")
        except Exception:
            logo_flow = None

    quote_meta = [
        f'<font size="22" color="{brand_hex}"><b>QUOTAZIONE</b></font>',
        f'<font size="14" color="#1a1a2e"><b>{quote.number}</b></font>'
        + (f'<font size="9" color="#7a8198">  ·  versione {quote.version}</font>' if quote.version and quote.version != 1 else ''),
    ]
    quote_block = Paragraph("<br/>".join(quote_meta),
        ParagraphStyle("qm", fontSize=10, alignment=TA_RIGHT, leading=22))

    if logo_flow:
        # 3 colonne: logo + tenant info + quote meta
        hdr = Table([[logo_flow, tenant_block, quote_block]],
                    colWidths=[40*mm, 60*mm, 80*mm])
    else:
        hdr = Table([[tenant_block, quote_block]], colWidths=[100*mm, 80*mm])
    hdr.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP")]))
    story.append(hdr)
    story.append(Spacer(1, 3*mm))
    story.append(HRFlowable(width="100%", thickness=2, color=BRAND, spaceAfter=4*mm))

    # Document header opzionale
    if tenant.get("document_header"):
        story.append(Paragraph(
            tenant["document_header"].replace("\n", "<br/>"),
            ParagraphStyle("dh", fontSize=9, textColor=DARK, leading=12)))
        story.append(Spacer(1, 4*mm))

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
    _ccy_label = _sym if _foreign else "€"
    header_row = [
        _p("Descrizione", 8, WHITE, bold=True),
        _p("Q.tà", 8, WHITE, bold=True, align=TA_RIGHT),
        _p("Unità", 8, WHITE, bold=True, align=TA_RIGHT),
        _p(f"Prezzo/Un. {_ccy_label}", 8, WHITE, bold=True, align=TA_RIGHT),
        _p("Sconto %", 8, WHITE, bold=True, align=TA_RIGHT),
        _p(f"Totale {_ccy_label}", 8, WHITE, bold=True, align=TA_RIGHT),
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
    # v3.5.0-alpha.27: tabella principale solo righe billabili. Le opzionali
    # vengono raccolte qui e renderizzate in una tabella separata dopo i totali.
    billable_lines = [l for l in sorted_lines if not getattr(l, "is_optional", False)]
    optional_lines = [l for l in sorted_lines if getattr(l, "is_optional", False)]
    groups: dict[str, list] = {}
    group_order = []
    for line in billable_lines:
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

        # v3.5.0-alpha.27: section_label intra-categoria. Quando il label
        # cambia tra righe consecutive, emettiamo un mini-header e un
        # subtotale di sezione al cambio.
        current_section = None
        section_accum = 0.0
        section_first_idx = -1

        def _flush_section():
            nonlocal current_section, section_accum, section_first_idx
            if current_section and section_first_idx >= 0:
                sub_i = len(rows)
                rows.append([
                    _p(f"  Subtotale sezione {current_section}", 8, GRAY,
                       bold=True, align=TA_RIGHT),
                    _p(""), _p(""), _p(""), _p(""),
                    _p(_m(section_accum), 8, GRAY, bold=True, align=TA_RIGHT),
                ])
                style_cmds.append(("SPAN", (0, sub_i), (4, sub_i)))
                style_cmds.append(("LINEABOVE", (0, sub_i), (-1, sub_i),
                                   0.2, GRAY_LT))

        for line in cat_lines:
            lbl = (getattr(line, "section_label", None) or "").strip() or None
            if lbl != current_section:
                _flush_section()
                current_section = lbl
                section_accum = 0.0
                section_first_idx = -1
                if current_section:
                    h_idx = len(rows)
                    rows.append([
                        _p(f"📦 {current_section}", 8, INDIGO_DK, bold=True),
                        _p(""), _p(""), _p(""), _p(""), _p(""),
                    ])
                    style_cmds.append(("SPAN", (0, h_idx), (-1, h_idx)))
                    style_cmds.append(
                        ("BACKGROUND", (0, h_idx), (-1, h_idx), BAND))
                    style_cmds.append(
                        ("LINEBELOW", (0, h_idx), (-1, h_idx), 0.2, INDIGO))
            disc_str = f"{(line.line_discount_pct or 0)*100:.1f}%" if line.line_discount_pct else "—"
            rows.append([
                _p(line.description, 8) if not line.detail else
                    Paragraph(f"<b>{line.description}</b><br/><font size='7' color='#7a8198'>{line.detail}</font>",
                              ParagraphStyle("x2", fontSize=8, fontName="Helvetica", leading=11)),
                _p(f"{line.quantity:g}", 8, align=TA_RIGHT),
                _p(line.unit, 8, align=TA_RIGHT),
                _p(_m(line.unit_price), 8, align=TA_RIGHT),
                _p(disc_str, 8, align=TA_RIGHT, color=ROSE if line.line_discount_pct else GRAY),
                _p(_m(line.total), 8, DARK, bold=True, align=TA_RIGHT),
            ])
            section_accum += (line.total or 0.0)
            if section_first_idx < 0:
                section_first_idx = len(rows) - 1
        _flush_section()

        # Subtotale categoria (escluse opzionali, già filtrate sopra)
        cat_subtotal = sum(l.total for l in cat_lines)
        sub_idx = len(rows)
        rows.append([
            _p(f"Subtotale {cat}", 8, DARK, bold=True, align=TA_RIGHT),
            _p(""), _p(""), _p(""), _p(""),
            _p(_m(cat_subtotal), 8, DARK, bold=True, align=TA_RIGHT),
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
                _p("−" + _m(disc_amount), 8, ROSE, bold=True, align=TA_RIGHT),
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
         _p(_m(quote.subtotal_gross), 9, GRAY, align=TA_RIGHT)],
    ]
    if line_cat_disc_total > 0.005:
        totals_rows.append(
            [_p("Sconti voci + categorie", 9, ROSE, align=TA_RIGHT),
             _p("−" + _m(line_cat_disc_total), 9, ROSE, align=TA_RIGHT)]
        )
    totals_rows.append(
        [_p("Subtotale", 9, DARK, bold=True, align=TA_RIGHT),
         _p(_m(quote.subtotal), 9, DARK, bold=True, align=TA_RIGHT)]
    )
    if pkg_pct > 0.05:
        totals_rows.append(
            [_p(f"Sconto pacchetto ({pkg_pct:.1f}%)", 9, ROSE, align=TA_RIGHT),
             _p("−" + _m(pkg_amount), 9, ROSE, align=TA_RIGHT)]
        )
    totals_rows.extend([
        [_p("Totale netto (base IVA)", 9, DARK, bold=True, align=TA_RIGHT),
         _p(_m(quote.total_after_discount), 9, DARK, bold=True, align=TA_RIGHT)],
        [_p(f"IVA {quote.vat_rate:.0f}%", 9, GRAY, align=TA_RIGHT),
         _p(_m(vat_amount), 9, GRAY, align=TA_RIGHT)],
        [_p("TOTALE (IVA inclusa)", 12, WHITE, bold=True, align=TA_RIGHT),
         _p(_m(quote.total_with_vat), 12, WHITE, bold=True, align=TA_RIGHT)],
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

    # ── Optional aggiuntivi (v3.5.0-alpha.27) ─────────────────
    # Tabella separata, dichiaratamente fuori dal totale. Stesso schema della
    # tabella principale ma senza subtotali categoria/sconti — sono voci che
    # il cliente decide se attivare a parte.
    if optional_lines:
        AMBER = colors.HexColor("#f59e0b")
        AMBER_BG = colors.HexColor("#fffaf0")
        story.append(Spacer(1, 8*mm))
        story.append(_p(
            "OPTIONAL AGGIUNTIVI — non inclusi nel totale", 9, AMBER, bold=True))
        story.append(_p(
            "Voci proposte come opzionali. Possono essere attivate "
            "separatamente con quotazione integrativa.", 7, GRAY))
        story.append(Spacer(1, 2*mm))

        opt_rows = [header_row]
        opt_style = [
            ("BACKGROUND", (0, 0), (-1, 0), AMBER),
            ("LINEBELOW", (0, 0), (-1, 0), 0.4, AMBER),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [AMBER_BG, WHITE]),
            ("TOPPADDING", (0, 0), (-1, -1), 2*mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2*mm),
            ("LEFTPADDING", (0, 0), (-1, -1), 2.5*mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2.5*mm),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]
        for line in optional_lines:
            disc_str = (
                f"{(line.line_discount_pct or 0)*100:.1f}%"
                if line.line_discount_pct else "—"
            )
            opt_rows.append([
                _p(line.description, 8) if not line.detail else
                    Paragraph(
                        f"<b>{line.description}</b><br/>"
                        f"<font size='7' color='#7a8198'>{line.detail}</font>",
                        ParagraphStyle("xo", fontSize=8,
                                       fontName="Helvetica", leading=11)),
                _p(f"{line.quantity:g}", 8, align=TA_RIGHT),
                _p(line.unit, 8, align=TA_RIGHT),
                _p(_m(line.unit_price), 8, align=TA_RIGHT),
                _p(disc_str, 8, align=TA_RIGHT,
                   color=ROSE if line.line_discount_pct else GRAY),
                _p(_m(line.total), 8, AMBER, bold=True, align=TA_RIGHT),
            ])
        # subtotale opzionale
        opt_subtotal = sum((l.total or 0.0) for l in optional_lines)
        sub_i = len(opt_rows)
        opt_rows.append([
            _p("Totale optional", 9, AMBER, bold=True, align=TA_RIGHT),
            _p(""), _p(""), _p(""), _p(""),
            _p("+" + _m(opt_subtotal), 9, AMBER, bold=True, align=TA_RIGHT),
        ])
        opt_style.append(("SPAN", (0, sub_i), (4, sub_i)))
        opt_style.append(("LINEABOVE", (0, sub_i), (-1, sub_i), 0.5, AMBER))
        opt_style.append(("BACKGROUND", (0, sub_i), (-1, sub_i), AMBER_BG))

        opt_tbl = Table(opt_rows, colWidths=col_w, repeatRows=1)
        opt_tbl.setStyle(TableStyle(opt_style))
        story.append(opt_tbl)

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
    # ── Disclaimer valuta estera (in calce, solo se presente) ──
    if disclaimer:
        story.append(Spacer(1, 3*mm))
        story.append(_p(disclaimer, 7, GRAY, align=TA_LEFT))

    # v3.5.0-alpha.66.13 — Footer branding "powered by" toggleable
    if tenant.get("show_powered_by", True):
        story.append(Spacer(1, 1*mm))
        story.append(_p("Generato con MediaFlow", 6, GRAY, align=TA_CENTER))

    doc.build(story)
    return buf.getvalue()
