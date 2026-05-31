"""
MediaFlow — pdf_export.py
Genera PDF fatture con ReportLab (compatibile Windows senza dipendenze native).
"""
from io import BytesIO
from datetime import date
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, HRFlowable, Image as RLImage,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_LEFT, TA_CENTER

# Palette MediaFlow
INDIGO  = colors.HexColor("#6272f5")
DARK    = colors.HexColor("#0f1117")
GRAY    = colors.HexColor("#9aa3bf")
LIGHT   = colors.HexColor("#f5f6fa")
WHITE   = colors.white
BLACK   = colors.HexColor("#1a1a2e")

_BASE_CURRENCY = "EUR"


def _money(v: float, sign: bool = False, sym: str = "€") -> str:
    """Formatta un importo come '€ 1.234,56'. Se sign=True, prefissa + per positivi."""
    if v is None:
        return ""
    s = f"{sym} {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if sign and v > 0:
        s = "+" + s
    return s


def _money_display(base_v: float, ccy: str, rate: float, sign: bool = False) -> str:
    """Formatta un importo convertito in valuta cliente.

    Se ccy == EUR (base) oppure rate <= 0, passa direttamente a _money.
    Altrimenti converte base_v / rate e usa il simbolo valuta.
    """
    from app.services.currency import to_display, symbol as ccy_symbol
    if not ccy or ccy.upper() == _BASE_CURRENCY or not rate or rate <= 0:
        return _money(base_v, sign=sign)
    display_v = to_display(base_v, rate)
    sym = ccy_symbol(ccy)
    return _money(display_v, sign=sign, sym=sym)


def generate_invoice_pdf(invoice: dict, lines: list[dict], company: dict = None) -> bytes:
    """
    Genera il PDF di una fattura e restituisce i bytes.

    Args:
        invoice: dizionario con i campi della fattura
        lines: lista di righe {description, quantity, unit_price, total}
        company: dati aziendali del mittente (opzionale)

    Returns:
        bytes del PDF generato

    v3.5.0-alpha.172.156 — Task 10 currency: se invoice['currency'] != EUR,
    tutti gli importi vengono convertiti base/fx_rate_to_base per la
    visualizzazione PDF, e un disclaimer legale è aggiunto in calce.
    Gli importi in DB restano in EUR (base). SDI XML non è toccato.
    """
    # ── Valuta display ────────────────────────────────────────
    ccy = (invoice.get("currency") or _BASE_CURRENCY).upper()
    rate = invoice.get("fx_rate_to_base") or 1.0
    is_foreign = ccy != _BASE_CURRENCY and rate > 0

    def _m(v: float, sign: bool = False) -> str:
        """Importo in valuta display (convertito se estera)."""
        return _money_display(v, ccy, rate, sign=sign)

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20*mm, rightMargin=20*mm,
        topMargin=20*mm, bottomMargin=20*mm,
    )

    styles = getSampleStyleSheet()
    story = []

    # ── Stili custom ──────────────────────────────────────────
    h1 = ParagraphStyle("h1", fontSize=22, textColor=INDIGO,
                        fontName="Helvetica-Bold", spaceAfter=2*mm)
    h2 = ParagraphStyle("h2", fontSize=11, textColor=BLACK,
                        fontName="Helvetica-Bold", spaceAfter=1*mm)
    body = ParagraphStyle("body", fontSize=9, textColor=BLACK,
                          fontName="Helvetica", leading=13)
    muted = ParagraphStyle("muted", fontSize=8, textColor=GRAY,
                           fontName="Helvetica", leading=12)
    right = ParagraphStyle("right", fontSize=9, textColor=BLACK,
                           fontName="Helvetica", alignment=TA_RIGHT)
    total_style = ParagraphStyle("total", fontSize=13, textColor=INDIGO,
                                 fontName="Helvetica-Bold", alignment=TA_RIGHT)

    # ── Header ────────────────────────────────────────────────
    company_name = (company or {}).get("name", "Claqo")
    company_info = (company or {}).get("info", "Via Esempio 1 — 00100 Roma\nP.IVA IT01234567890")

    header_data = [
        [Paragraph(f"<b>{company_name}</b>", h1),
         Paragraph("FATTURA", ParagraphStyle("inv_label", fontSize=28,
                   textColor=INDIGO, fontName="Helvetica-Bold", alignment=TA_RIGHT))],
        [Paragraph(company_info.replace("\n", "<br/>"), muted),
         Paragraph(
             f"<b>N° {invoice.get('number','—')}</b><br/>"
             f"Data: {invoice.get('issue_date','—')}<br/>"
             f"Scadenza: {invoice.get('due_date','—') or 'non specificata'}",
             ParagraphStyle("inv_meta", fontSize=9, textColor=BLACK,
                            fontName="Helvetica", alignment=TA_RIGHT, leading=14)
         )],
    ]
    header_table = Table(header_data, colWidths=[95*mm, 75*mm])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4*mm),
    ]))
    story.append(header_table)
    story.append(HRFlowable(width="100%", thickness=1, color=INDIGO, spaceAfter=4*mm))

    # ── Dati cliente ──────────────────────────────────────────
    client_name = invoice.get("client_name", "—")
    client_info = invoice.get("client_info", "")
    story.append(Paragraph("Destinatario", muted))
    story.append(Paragraph(f"<b>{client_name}</b>", h2))
    if client_info:
        story.append(Paragraph(client_info, body))
    story.append(Spacer(1, 6*mm))

    # ── Righe fattura ──────────────────────────────────────────
    col_w = [85*mm, 20*mm, 30*mm, 35*mm]
    table_data = [[
        Paragraph("<b>Descrizione</b>", ParagraphStyle("th", fontSize=8, fontName="Helvetica-Bold", textColor=WHITE)),
        Paragraph("<b>Q.tà</b>",        ParagraphStyle("th", fontSize=8, fontName="Helvetica-Bold", textColor=WHITE, alignment=TA_RIGHT)),
        Paragraph("<b>Prezzo unit.</b>", ParagraphStyle("th", fontSize=8, fontName="Helvetica-Bold", textColor=WHITE, alignment=TA_RIGHT)),
        Paragraph("<b>Totale</b>",       ParagraphStyle("th", fontSize=8, fontName="Helvetica-Bold", textColor=WHITE, alignment=TA_RIGHT)),
    ]]

    for line in lines:
        table_data.append([
            Paragraph(str(line.get("description", "")), body),
            Paragraph(str(line.get("quantity", 1)),     right),
            Paragraph(_m(line.get("unit_price") or 0),  right),
            Paragraph(_m(line.get("total") or 0),        right),
        ])

    line_table = Table(table_data, colWidths=col_w, repeatRows=1)
    line_table.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0), INDIGO),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [WHITE, LIGHT]),
        ("GRID",          (0,0), (-1,-1), 0.3, colors.HexColor("#e0e3f0")),
        ("TOPPADDING",    (0,0), (-1,-1), 3*mm),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3*mm),
        ("LEFTPADDING",   (0,0), (-1,-1), 2*mm),
        ("RIGHTPADDING",  (0,0), (-1,-1), 2*mm),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
    ]))
    story.append(line_table)
    story.append(Spacer(1, 5*mm))

    # ── Totali ────────────────────────────────────────────────
    # v3.5.0-alpha.112 — autorevole: ricalcola subtotal da Σ lines per
    # evitare drift fattura-stampata vs lista/report (Matteo P7).
    # invoice.subtotal/total stored sono solo fallback se lines vuote.
    lines_sum = round(sum((l.get("total") or 0) for l in lines), 2)
    stored_subtotal = invoice.get("subtotal", 0) or 0
    subtotal = lines_sum if lines_sum > 0 else stored_subtotal
    vat_rate = invoice.get("vat_rate", 22)
    vat_amt  = round(subtotal * vat_rate / 100, 2)
    total    = round(subtotal + vat_amt, 2)

    totals_data = [
        ["", "Imponibile:",  _m(subtotal)],
        ["", f"IVA {vat_rate}%:", _m(vat_amt)],
        ["", "TOTALE:",      _m(total)],
    ]
    totals_table = Table(totals_data, colWidths=[100*mm, 40*mm, 30*mm])
    totals_table.setStyle(TableStyle([
        ("ALIGN",        (1,0), (-1,-1), "RIGHT"),
        ("FONTNAME",     (1,2), (-1,2), "Helvetica-Bold"),
        ("FONTSIZE",     (1,2), (-1,2), 11),
        ("TEXTCOLOR",    (1,2), (-1,2), INDIGO),
        ("TOPPADDING",   (0,0), (-1,-1), 2*mm),
        ("BOTTOMPADDING",(0,0), (-1,-1), 2*mm),
        ("LINEABOVE",    (1,2), (-1,2), 1, INDIGO),
    ]))
    story.append(totals_table)

    # ── Sezione chiusura progetto (v3.5.0-alpha.112) ──────────
    if invoice.get("is_closing"):
        story.append(Spacer(1, 10*mm))
        story.append(HRFlowable(width="100%", thickness=1, color=INDIGO, spaceAfter=3*mm))
        proj_code = invoice.get("project_code", "—")
        proj_title = invoice.get("project_title", "")
        story.append(Paragraph(
            f"<b>FATTURA DI CHIUSURA PROGETTO</b> — {proj_code} · {proj_title}",
            h2,
        ))
        story.append(Paragraph(
            "Riepilogo di tutte le fatture emesse sul progetto:", muted
        ))
        story.append(Spacer(1, 3*mm))
        summary = invoice.get("closing_summary", []) or []
        if summary:
            sum_header = [
                Paragraph("<b>N°</b>", ParagraphStyle("sh", fontSize=8, fontName="Helvetica-Bold", textColor=WHITE)),
                Paragraph("<b>Data</b>", ParagraphStyle("sh", fontSize=8, fontName="Helvetica-Bold", textColor=WHITE)),
                Paragraph("<b>Tipo</b>", ParagraphStyle("sh", fontSize=8, fontName="Helvetica-Bold", textColor=WHITE)),
                Paragraph("<b>Stato</b>", ParagraphStyle("sh", fontSize=8, fontName="Helvetica-Bold", textColor=WHITE)),
                Paragraph("<b>Totale</b>", ParagraphStyle("sh", fontSize=8, fontName="Helvetica-Bold", textColor=WHITE, alignment=TA_RIGHT)),
                Paragraph("<b>Pagato</b>", ParagraphStyle("sh", fontSize=8, fontName="Helvetica-Bold", textColor=WHITE, alignment=TA_RIGHT)),
            ]
            sum_rows = [sum_header]
            for s in summary:
                sum_rows.append([
                    Paragraph(str(s.get("number", "")), body),
                    Paragraph(str(s.get("issue_date", "")), body),
                    Paragraph(str(s.get("doc_type", "")), body),
                    Paragraph(str(s.get("status", "")), body),
                    Paragraph(
                        f"€ {s.get('total',0):,.2f}".replace(",","X").replace(".",",").replace("X","."),
                        right,
                    ),
                    Paragraph(
                        f"€ {s.get('amount_paid',0):,.2f}".replace(",","X").replace(".",",").replace("X","."),
                        right,
                    ),
                ])
            t_total = sum((s.get("total") or 0) for s in summary)
            t_paid = sum((s.get("amount_paid") or 0) for s in summary)
            sum_rows.append([
                Paragraph("<b>Tot.</b>", body), "", "", "",
                Paragraph(
                    f"<b>€ {t_total:,.2f}</b>".replace(",","X").replace(".",",").replace("X","."),
                    right,
                ),
                Paragraph(
                    f"<b>€ {t_paid:,.2f}</b>".replace(",","X").replace(".",",").replace("X","."),
                    right,
                ),
            ])
            sum_col_w = [28*mm, 22*mm, 16*mm, 24*mm, 25*mm, 25*mm]
            sum_table = Table(sum_rows, colWidths=sum_col_w, repeatRows=1)
            sum_table.setStyle(TableStyle([
                ("BACKGROUND",    (0,0), (-1,0), INDIGO),
                ("ROWBACKGROUNDS",(0,1), (-1,-2), [WHITE, LIGHT]),
                ("GRID",          (0,0), (-1,-1), 0.3, colors.HexColor("#e0e3f0")),
                ("TOPPADDING",    (0,0), (-1,-1), 2*mm),
                ("BOTTOMPADDING", (0,0), (-1,-1), 2*mm),
                ("LEFTPADDING",   (0,0), (-1,-1), 2*mm),
                ("RIGHTPADDING",  (0,0), (-1,-1), 2*mm),
                ("LINEABOVE",     (0,-1),(-1,-1), 1, INDIGO),
                ("FONTNAME",      (0,-1),(-1,-1), "Helvetica-Bold"),
            ]))
            story.append(sum_table)
        else:
            story.append(Paragraph("Nessuna fattura precedente.", muted))

    # ── Disclaimer valuta estera (Task 10) ────────────────────
    if is_foreign:
        from app.services.currency import disclaimer as ccy_disclaimer
        issue_date_str = invoice.get("issue_date") or ""
        disc_text = ccy_disclaimer(_BASE_CURRENCY, ccy, rate, issue_date_str, emitted=True)
        story.append(Spacer(1, 6*mm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=GRAY, spaceAfter=3*mm))
        disclaimer_style = ParagraphStyle(
            "disclaimer", fontSize=7, textColor=GRAY,
            fontName="Helvetica-Oblique", leading=11
        )
        story.append(Paragraph(disc_text, disclaimer_style))

    # ── Note ──────────────────────────────────────────────────
    notes = invoice.get("notes")
    if notes:
        story.append(Spacer(1, 8*mm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=GRAY, spaceAfter=3*mm))
        story.append(Paragraph("Note", muted))
        story.append(Paragraph(notes, body))

    # ── Footer ────────────────────────────────────────────────
    story.append(Spacer(1, 12*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=GRAY, spaceAfter=2*mm))
    story.append(Paragraph(
        "Documento generato da MediaFlow · Pagamento da effettuarsi entro la data di scadenza",
        ParagraphStyle("footer", fontSize=7, textColor=GRAY,
                       fontName="Helvetica", alignment=TA_CENTER)
    ))

    doc.build(story)
    return buf.getvalue()


def generate_client_cost_report_pdf(report: dict, company: dict = None,
                                    rendiconto: bool = False,
                                    vista: str = "now",
                                    branding: dict = None) -> bytes:
    """v3.4.33 — Cost report **vista cliente** in PDF.

    A differenza di `generate_invoice_pdf` (fatturazione), questo è un report
    di rendicontazione: mostra solo cosa è stato fatto, niente importi finali
    né margini interni. Solo lavorazioni quote + extra con ore previste/lavorate
    e scostamento. NIENTE hardcost, NIENTE rate risorsa, NIENTE costi-margine.

    `report` è il dict ritornato da `/cost-report/api/job/{id}` arricchito con:
      - cost_lines: list of {description, unit, quantity_quoted, quantity_actual,
                              unit_price, total_quoted, total_accrued, is_extra,
                              category, notes}
      - bookings_breakdown: dict con regular/overtime/night/sunday/holiday
      - job: {code, title, client, start_date, end_date}

    v3.5.0-alpha.16: nuova flag `rendiconto`. Se True, oltre alle quantità
    mostra Quotato/Maturato/Stimato e Over/Under per ogni riga + totale finale.
    Il PDF rimane "vista cliente" (niente hardcost/rate/margine) ma più
    informativo per la fatturazione progressiva. Default False = comportamento
    pre-alpha.16 (solo quantità).
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20*mm, rightMargin=20*mm,
        topMargin=20*mm, bottomMargin=20*mm,
    )
    styles = getSampleStyleSheet()
    story = []

    # v3.5.0-alpha.66.13 — Branding tenant: brand_color + logo + tagline
    branding = branding or {}
    brand_hex = branding.get("brand_color") or "#6272f5"
    try:
        BRAND = colors.HexColor(brand_hex)
    except Exception:
        BRAND = INDIGO

    h1 = ParagraphStyle("h1", fontSize=22, textColor=BRAND,
                        fontName="Helvetica-Bold", spaceAfter=2*mm)
    h2 = ParagraphStyle("h2", fontSize=11, textColor=BLACK,
                        fontName="Helvetica-Bold", spaceAfter=1*mm)
    body = ParagraphStyle("body", fontSize=9, textColor=BLACK,
                          fontName="Helvetica", leading=13)
    muted = ParagraphStyle("muted", fontSize=8, textColor=GRAY,
                           fontName="Helvetica", leading=12)
    right = ParagraphStyle("right", fontSize=9, textColor=BLACK,
                           fontName="Helvetica", alignment=TA_RIGHT)
    tagline_style = ParagraphStyle("tagline", fontSize=9, textColor=BRAND,
                                   fontName="Helvetica-Oblique", leading=12)

    company_name = branding.get("name") or (company or {}).get("name") or "Claqo"
    company_info = branding.get("info") or (company or {}).get("info") or ""
    tagline = branding.get("tagline") or ""
    document_header = branding.get("document_header") or ""
    show_powered_by = branding.get("show_powered_by", True)
    logo_path = branding.get("logo_path")  # Path o None

    job = report.get("job", {})
    job_code = job.get("code", "—")
    job_title = job.get("title", "—")
    client_name = job.get("client") or "—"
    start = job.get("start_date") or "—"
    end = job.get("end_date") or "—"

    # ── Header con logo (v3.5.0-alpha.66.13) ─────────────────
    logo_flow = None
    if logo_path:
        try:
            p = Path(logo_path) if not isinstance(logo_path, Path) else logo_path
            if p.exists() and p.stat().st_size < 5_000_000:
                logo_flow = RLImage(str(p), width=40*mm, height=18*mm, kind="proportional")
        except Exception:
            logo_flow = None

    name_block_parts = [Paragraph(f"<b>{company_name}</b>", h1)]
    if tagline:
        name_block_parts.append(Paragraph(tagline, tagline_style))

    if logo_flow:
        name_cell = Table([[logo_flow], *[[p] for p in name_block_parts]],
                          colWidths=[90*mm])
        name_cell.setStyle(TableStyle([
            ("LEFTPADDING", (0,0), (-1,-1), 0),
            ("RIGHTPADDING", (0,0), (-1,-1), 0),
            ("BOTTOMPADDING", (0,0), (0,0), 2*mm),
            ("TOPPADDING", (0,0), (-1,-1), 0),
        ]))
        left_block = name_cell
    elif tagline:
        left_block = Table([[p] for p in name_block_parts], colWidths=[90*mm])
        left_block.setStyle(TableStyle([
            ("LEFTPADDING", (0,0), (-1,-1), 0),
            ("RIGHTPADDING", (0,0), (-1,-1), 0),
        ]))
    else:
        left_block = name_block_parts[0]

    header_data = [
        [left_block,
         Paragraph("RENDICONTAZIONE",
                   ParagraphStyle("title_label", fontSize=18,
                                  textColor=BRAND, fontName="Helvetica-Bold",
                                  alignment=TA_RIGHT))],
        [Paragraph(company_info.replace("\n", "<br/>") if company_info else "", muted),
         Paragraph(
             f"<b>Job: {job_code}</b><br/>"
             f"{job_title}<br/>"
             f"Periodo: {start} → {end}",
             ParagraphStyle("meta", fontSize=9, textColor=BLACK,
                            fontName="Helvetica", alignment=TA_RIGHT, leading=14)
         )],
    ]
    header_table = Table(header_data, colWidths=[95*mm, 75*mm])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4*mm),
    ]))
    story.append(header_table)
    story.append(HRFlowable(width="100%", thickness=1, color=BRAND, spaceAfter=4*mm))

    # Document header opzionale (sopra il contenuto del report)
    if document_header:
        story.append(Paragraph(document_header.replace("\n", "<br/>"), body))
        story.append(Spacer(1, 4*mm))

    # ── Cliente ──────────────────────────────────────────────
    story.append(Paragraph("Cliente", muted))
    story.append(Paragraph(f"<b>{client_name}</b>", h2))
    story.append(Spacer(1, 6*mm))

    # ── Lavorazioni quotate ──────────────────────────────────
    quoted_lines = [l for l in (report.get("cost_lines") or []) if not l.get("is_extra")]
    extra_lines = [l for l in (report.get("cost_lines") or []) if l.get("is_extra")]

    def _row_qty(l):
        qq = l.get("quantity_quoted") or 0
        qa = l.get("quantity_actual") or 0
        delta = qa - qq
        sign = "+" if delta > 0 else ""
        return f"{qq} → {qa} ({sign}{delta:.1f})" if delta else f"{qq}"

    if quoted_lines:
        story.append(Paragraph("<b>Lavorazioni preventivate</b>", h2))
        if rendiconto:
            # Modalità rendiconto: 6 colonne con importi Quotato/Maturato/Stimato + Over/Under
            col_w = [62*mm, 14*mm, 14*mm, 24*mm, 24*mm, 24*mm, 18*mm]
            th = lambda t, a=TA_LEFT: Paragraph(f"<b>{t}</b>", ParagraphStyle(
                "th", fontSize=8, fontName="Helvetica-Bold", textColor=WHITE, alignment=a))
            table_data = [[
                th("Descrizione"),
                th("Unità", TA_CENTER),
                th("Q.tà", TA_RIGHT),
                th("Quotato", TA_RIGHT),
                th("Maturato", TA_RIGHT),
                th("Stimato", TA_RIGHT),
                th("±", TA_RIGHT),
            ]]
            # v3.5.0-alpha.55: vista now=maturato vs quotato (segno positivo
            # = OVER/sforamento, rosso). vista forecast=stima vs quotato.
            is_forecast = (vista == "forecast")
            ov_field = "over_under_forecast" if is_forecast else "over_under_now"
            tot_quoted = tot_accrued = tot_expected = 0.0
            for l in quoted_lines:
                qq = l.get("quantity_quoted") or 0
                qa = l.get("quantity_actual") or 0
                tq = l.get("total_quoted") or 0
                ta = l.get("total_accrued") or 0
                te = l.get("total_expected") or 0
                ou = l.get(ov_field)
                if ou is None:
                    ou = (te - tq) if is_forecast else (ta - tq)
                tot_quoted += tq
                tot_accrued += ta
                tot_expected += te
                cat = l.get("category") or ""
                desc_html = f"{l.get('description', '')}"
                if cat:
                    desc_html += f"<br/><font size=7 color='#888'>{cat}</font>"
                ou_color = "#dc2626" if ou > 0 else "#16a34a"
                table_data.append([
                    Paragraph(desc_html, body),
                    Paragraph(l.get("unit", ""), ParagraphStyle("c", fontSize=9, fontName="Helvetica", alignment=TA_CENTER)),
                    Paragraph(_row_qty(l), right),
                    Paragraph(_money(tq), right),
                    Paragraph(_money(ta), right),
                    Paragraph(_money(te), right),
                    Paragraph(f"<font color='{ou_color}'>{_money(ou, sign=True)}</font>", right),
                ])
            tot_ou = (tot_expected - tot_quoted) if is_forecast else (tot_accrued - tot_quoted)
            tot_color = "#dc2626" if tot_ou > 0 else "#16a34a"
            table_data.append([
                Paragraph("<b>Totale</b>", body),
                Paragraph("", body),
                Paragraph("", body),
                Paragraph(f"<b>{_money(tot_quoted)}</b>", right),
                Paragraph(f"<b>{_money(tot_accrued)}</b>", right),
                Paragraph(f"<b>{_money(tot_expected)}</b>", right),
                Paragraph(f"<font color='{tot_color}'><b>{_money(tot_ou, sign=True)}</b></font>", right),
            ])
            line_table = Table(table_data, colWidths=col_w, repeatRows=1)
            line_table.setStyle(TableStyle([
                ("BACKGROUND",     (0,0), (-1,0), INDIGO),
                ("ROWBACKGROUNDS", (0,1), (-1,-2), [WHITE, LIGHT]),
                ("BACKGROUND",     (0,-1), (-1,-1), colors.HexColor("#eef0fb")),
                ("LINEABOVE",      (0,-1), (-1,-1), 0.8, INDIGO),
                ("GRID",           (0,0), (-1,-1), 0.3, colors.HexColor("#e0e3f0")),
                ("TOPPADDING",     (0,0), (-1,-1), 3*mm),
                ("BOTTOMPADDING",  (0,0), (-1,-1), 3*mm),
                ("LEFTPADDING",    (0,0), (-1,-1), 2*mm),
                ("RIGHTPADDING",   (0,0), (-1,-1), 2*mm),
                ("VALIGN",         (0,0), (-1,-1), "MIDDLE"),
            ]))
        else:
            # Modalità "stato lavorazioni" (solo quantità) — comportamento storico
            col_w = [80*mm, 18*mm, 35*mm, 37*mm]
            table_data = [[
                Paragraph("<b>Descrizione</b>", ParagraphStyle("th", fontSize=8, fontName="Helvetica-Bold", textColor=WHITE)),
                Paragraph("<b>Unità</b>",       ParagraphStyle("th", fontSize=8, fontName="Helvetica-Bold", textColor=WHITE, alignment=TA_CENTER)),
                Paragraph("<b>Q.tà preventivo → consuntivo</b>", ParagraphStyle("th", fontSize=8, fontName="Helvetica-Bold", textColor=WHITE, alignment=TA_RIGHT)),
                Paragraph("<b>Stato</b>",       ParagraphStyle("th", fontSize=8, fontName="Helvetica-Bold", textColor=WHITE, alignment=TA_CENTER)),
            ]]
            for l in quoted_lines:
                qq = l.get("quantity_quoted") or 0
                qa = l.get("quantity_actual") or 0
                if qa == 0 and qq > 0:
                    stato = "Da fare"
                elif qa < qq:
                    stato = "In corso"
                elif qa == qq:
                    stato = "Completata"
                else:
                    stato = "Sforamento"
                cat = l.get("category") or ""
                desc_html = f"{l.get('description', '')}"
                if cat:
                    desc_html += f"<br/><font size=7 color='#888'>{cat}</font>"
                table_data.append([
                    Paragraph(desc_html, body),
                    Paragraph(l.get("unit", ""), ParagraphStyle("c", fontSize=9, fontName="Helvetica", alignment=TA_CENTER)),
                    Paragraph(_row_qty(l), right),
                    Paragraph(stato, ParagraphStyle("c", fontSize=9, fontName="Helvetica", alignment=TA_CENTER)),
                ])
            line_table = Table(table_data, colWidths=col_w, repeatRows=1)
            line_table.setStyle(TableStyle([
                ("BACKGROUND",     (0,0), (-1,0), INDIGO),
                ("ROWBACKGROUNDS", (0,1), (-1,-1), [WHITE, LIGHT]),
                ("GRID",           (0,0), (-1,-1), 0.3, colors.HexColor("#e0e3f0")),
                ("TOPPADDING",     (0,0), (-1,-1), 3*mm),
                ("BOTTOMPADDING",  (0,0), (-1,-1), 3*mm),
                ("LEFTPADDING",    (0,0), (-1,-1), 2*mm),
                ("RIGHTPADDING",   (0,0), (-1,-1), 2*mm),
                ("VALIGN",         (0,0), (-1,-1), "MIDDLE"),
            ]))
        story.append(line_table)
        story.append(Spacer(1, 5*mm))

    if extra_lines:
        story.append(Paragraph("<b>Lavorazioni extra</b> <font color='#888'>(richieste oltre il preventivo originale)</font>", h2))
        col_w = [110*mm, 22*mm, 38*mm]
        ed = [[
            Paragraph("<b>Descrizione</b>", ParagraphStyle("th", fontSize=8, fontName="Helvetica-Bold", textColor=WHITE)),
            Paragraph("<b>Unità</b>",       ParagraphStyle("th", fontSize=8, fontName="Helvetica-Bold", textColor=WHITE, alignment=TA_CENTER)),
            Paragraph("<b>Q.tà</b>",        ParagraphStyle("th", fontSize=8, fontName="Helvetica-Bold", textColor=WHITE, alignment=TA_RIGHT)),
        ]]
        for l in extra_lines:
            ed.append([
                Paragraph(str(l.get("description", "")), body),
                Paragraph(l.get("unit", ""), ParagraphStyle("c", fontSize=9, fontName="Helvetica", alignment=TA_CENTER)),
                Paragraph(str(l.get("quantity_actual") or l.get("quantity_quoted") or 0), right),
            ])
        et = Table(ed, colWidths=col_w, repeatRows=1)
        et.setStyle(TableStyle([
            ("BACKGROUND",     (0,0), (-1,0), colors.HexColor("#fb923c")),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [WHITE, LIGHT]),
            ("GRID",           (0,0), (-1,-1), 0.3, colors.HexColor("#e0e3f0")),
            ("TOPPADDING",     (0,0), (-1,-1), 3*mm),
            ("BOTTOMPADDING",  (0,0), (-1,-1), 3*mm),
            ("LEFTPADDING",    (0,0), (-1,-1), 2*mm),
            ("RIGHTPADDING",   (0,0), (-1,-1), 2*mm),
        ]))
        story.append(et)
        story.append(Spacer(1, 5*mm))

    # ── Riepilogo ore lavorate (da bookings) ─────────────────
    bd = report.get("bookings_breakdown") or {}
    summary = report.get("summary") or {}
    bk_hours = summary.get("bookings_hours", 0)
    if bk_hours and bk_hours > 0:
        story.append(Paragraph("<b>Riepilogo ore lavorate</b>", h2))
        rows = []
        if bd.get("regular_hours"):
            rows.append(("Ore regolari", f"{bd.get('regular_hours'):.2f}h"))
        if bd.get("overtime_hours"):
            rows.append(("Ore straordinarie", f"{bd.get('overtime_hours'):.2f}h"))
        if bd.get("night_hours"):
            rows.append(("Ore notturne", f"{bd.get('night_hours'):.2f}h"))
        if bd.get("sunday_hours"):
            rows.append(("Ore domenicali", f"{bd.get('sunday_hours'):.2f}h"))
        if bd.get("holiday_hours"):
            rows.append(("Ore festive", f"{bd.get('holiday_hours'):.2f}h"))
        rows.append(("Totale", f"{bk_hours:.2f}h"))
        td = []
        for label, val in rows:
            is_total = (label == "Totale")
            td.append([
                Paragraph(f"<b>{label}</b>" if is_total else label, body),
                Paragraph(f"<b>{val}</b>" if is_total else val, right),
            ])
        ott = Table(td, colWidths=[120*mm, 50*mm])
        ott.setStyle(TableStyle([
            ("ALIGN",        (1,0), (1,-1), "RIGHT"),
            ("LINEABOVE",    (0,-1), (-1,-1), 0.8, INDIGO),
            ("TOPPADDING",   (0,0), (-1,-1), 2*mm),
            ("BOTTOMPADDING",(0,0), (-1,-1), 2*mm),
        ]))
        story.append(ott)

    # ── Footer (v3.5.0-alpha.66.13: branding-aware) ──────────
    story.append(Spacer(1, 12*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=GRAY, spaceAfter=2*mm))
    footer_bits = [f"<b>{company_name}</b>"]
    if show_powered_by:
        footer_bits.append("Generato con MediaFlow")
    footer_bits.append("Rendicontazione lavorazioni — non è una fattura")
    story.append(Paragraph(
        " · ".join(footer_bits),
        ParagraphStyle("footer", fontSize=7, textColor=GRAY,
                       fontName="Helvetica", alignment=TA_CENTER)
    ))

    doc.build(story)
    return buf.getvalue()
