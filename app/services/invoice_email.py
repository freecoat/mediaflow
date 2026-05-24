"""v3.5.0-alpha.130 — Helper send invoice via SMTP, condiviso fra endpoint
HTTP (F6 α.127) e capability AI (propose_send_invoice_email α.130).

Pattern: extracted helper per evitare duplicazione 50+ righe di logica SMTP
fra POST /finance/api/invoices/{id}/send-email e _h_propose_send_invoice_email.

Provider-agnostic via .env (SMTP_HOST/PORT/USER/PASS/FROM/USE_TLS). Compatibile
con qualsiasi provider standard: Gmail (app-pass), Microsoft 365, AWS SES,
Mailgun, SendGrid, Postmark, etc.
"""
from __future__ import annotations
import os
import smtplib
from email.message import EmailMessage
from typing import Optional

from sqlalchemy.orm import Session, joinedload

from app.models import Invoice, Job, Tenant, InvoiceStatus
from app.context import current_tenant_id


class InvoiceEmailError(Exception):
    """Errore send fattura. Attributi: code (HTTP status), message."""
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def send_invoice_via_smtp(
    db: Session,
    invoice_id: int,
    recipient_override: Optional[str] = None,
) -> dict:
    """Invia fattura via email. Ritorna {recipient, subject, invoice_number}.

    Solleva InvoiceEmailError:
      - 503 se SMTP non configurato
      - 404 se fattura non trovata
      - 409 se fattura cancelled (non-stampabile)
      - 400 se cliente senza email (e nessun recipient_override)
      - 502 se SMTP fallisce
    """
    smtp_host = os.environ.get("SMTP_HOST", "").strip()
    if not smtp_host:
        raise InvoiceEmailError(
            503,
            "SMTP non configurato. Imposta SMTP_HOST/PORT/USER/PASS/FROM "
            "in .env per abilitare l'invio email."
        )

    inv = db.query(Invoice).options(
        joinedload(Invoice.client),
        joinedload(Invoice.lines),
        joinedload(Invoice.job).joinedload(Job.project),
    ).filter(Invoice.id == invoice_id).first()
    if not inv:
        raise InvoiceEmailError(404, "Fattura non trovata")
    if inv.status == InvoiceStatus.cancelled:
        raise InvoiceEmailError(409, "Fattura annullata: non inviabile via email.")

    if recipient_override:
        admin_email = recipient_override.strip()
    else:
        admin_email = (
            getattr(inv, "client_admin_email_snap", None)
            or (inv.client.admin_email if inv.client and getattr(inv.client, "admin_email", None) else None)
            or (inv.client.contact_email if inv.client and inv.client.contact_email else None)
        )
    if not admin_email:
        raise InvoiceEmailError(
            400,
            f"Cliente {inv.client.name if inv.client else '?'} senza admin_email/contact_email. "
            "Imposta un indirizzo email o passa recipient_override."
        )

    from app.services.invoice_pdf import generate_invoice_pdf
    tenant_obj = db.query(Tenant).filter(Tenant.id == current_tenant_id()).first()
    project_obj = inv.job.project if (inv.job and inv.job.project) else None
    pdf_bytes = generate_invoice_pdf(inv, tenant=tenant_obj, client=inv.client, project=project_obj)

    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "").strip()
    smtp_pass = os.environ.get("SMTP_PASS", "")
    smtp_from = os.environ.get("SMTP_FROM", smtp_user).strip()
    use_tls = os.environ.get("SMTP_USE_TLS", "1") == "1"
    if not smtp_from:
        raise InvoiceEmailError(503, "SMTP_FROM non configurato in .env.")

    doc_label = "Nota di credito" if inv.doc_type == "TD04" else "Fattura"
    subject = f"{doc_label} {inv.number} — {tenant_obj.name if tenant_obj else 'Claqo'}"
    proj_line = ""
    if project_obj:
        proj_line = f"\nProgetto: {project_obj.code} · {project_obj.title}"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp_from
    msg["To"] = admin_email
    msg.set_content(
        f"Buongiorno,\n\n"
        f"in allegato {doc_label.lower()} {inv.number} del "
        f"{inv.issue_date.strftime('%d/%m/%Y') if inv.issue_date else '?'}.\n"
        f"Cliente: {inv.client.name if inv.client else '?'}"
        f"{proj_line}\n"
        f"Imponibile: {(inv.subtotal or 0):.2f} €\n"
        f"Totale (IVA inclusa): {(inv.total or 0):.2f} €\n\n"
        f"Cordiali saluti."
    )
    safe_num = (inv.number or f"invoice-{inv.id}").replace("/", "-")
    msg.add_attachment(
        pdf_bytes, maintype="application", subtype="pdf",
        filename=f"{doc_label}-{safe_num}.pdf",
    )

    try:
        if use_tls:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as srv:
                srv.starttls()
                if smtp_user:
                    srv.login(smtp_user, smtp_pass)
                srv.send_message(msg)
        else:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20) as srv:
                if smtp_user:
                    srv.login(smtp_user, smtp_pass)
                srv.send_message(msg)
    except Exception as e:
        raise InvoiceEmailError(502, f"Invio SMTP fallito: {e}")

    return {
        "invoice_id": inv.id,
        "invoice_number": inv.number,
        "recipient": admin_email,
        "subject": subject,
    }
