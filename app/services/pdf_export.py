"""
MediaFlow — pdf_export.py
Genera PDF fatture con ReportLab (compatibile Windows senza dipendenze native).
"""
from io import BytesIO
from datetime import date
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, HRFlowable
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


def generate_invoice_pdf(invoice: dict, lines: list[dict], company: dict = None) -> bytes:
    """
    Genera il PDF di una fattura e restituisce i bytes.

    Args:
        invoice: dizionario con i campi della fattura
        lines: lista di righe {description, quantity, unit_price, total}
        company: dati aziendali del mittente (opzionale)

    Returns:
        bytes del PDF generato
    """
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
    company_name = (company or {}).get("name", "MediaFlow")
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
            Paragraph(f"€ {line.get('unit_price',0):,.2f}".replace(",","X").replace(".",",").replace("X","."), right),
            Paragraph(f"€ {line.get('total',0):,.2f}".replace(",","X").replace(".",",").replace("X","."),      right),
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
    subtotal = invoice.get("subtotal", 0)
    vat_rate = invoice.get("vat_rate", 22)
    vat_amt  = subtotal * vat_rate / 100
    total    = invoice.get("total", subtotal + vat_amt)

    def fmt(n):
        return f"€ {n:,.2f}".replace(",","X").replace(".",",").replace("X",".")

    totals_data = [
        ["", "Imponibile:",  fmt(subtotal)],
        ["", f"IVA {vat_rate}%:", fmt(vat_amt)],
        ["", "TOTALE:",      fmt(total)],
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
