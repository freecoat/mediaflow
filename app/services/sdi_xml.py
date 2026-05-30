"""FatturaPA v1.6.1 XML builder — Sprint 6.B BLOCCO 6 audit.

Self-contained Python builder (xml.etree.ElementTree). Produce XML
emissibile via SDI per fatture B2B IT (formato FPR12).

Architettura:
- `build_fattura_xml(invoice, tenant)` → str XML completo + filename SDI
- Usa SOLO snapshot fields di Invoice (immutabilità documento fiscale)
- Subset minimo necessario per fatture standard MediaFlow (TD01/TD02/TD04
  + IVA 22% standard + B2B clienti italiani con SDI o PEC)
- XSD compliance NON validata internamente (richiede xmlschema lib +
  schema XSD scaricato). Validazione delegata al MCP server `fattura-
  elettronica-it` quando disponibile a Claude runtime, oppure al portale
  SDI al primo invio.

Pattern uso (endpoint):
    xml_str, filename = build_fattura_xml(invoice, tenant)
    return Response(xml_str, media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})

Limitazioni note:
- Non supporta `Allegati` (PDF embedded).
- Non gestisce `ScontoMaggiorazione` (mai usato in MediaFlow attuale).
- Per `DatiOrdineAcquisto` / `DatiContratto` (campi opzionali B2B): non
  emessi. Aggiungere quando UI MediaFlow supporta riferimento ordine.

Roadmap S8/S9:
- Firma digitale XAdES-BES (richiesto SDI invio) — usa libreria esterna
- Conservazione sostitutiva 10 anni
- Ricezione notifiche SDI via PEC parsing
"""
from __future__ import annotations
import xml.etree.ElementTree as ET
from datetime import date as _date
from decimal import Decimal
from typing import Optional, Tuple

from app.services.money import to_decimal, money_round

# Namespace FatturaPA v1.6.1
_NS_P = "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2"
_NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"
_NS_DS = "http://www.w3.org/2000/09/xmldsig#"

# Costanti MediaFlow default
_FORMATO_TRASMISSIONE = "FPR12"  # B2B privati
_DIVISA = "EUR"
_DEFAULT_CAUSALE = "Servizi di post-produzione audiovisiva"
_DEFAULT_METODO_PAGAMENTO = "MP05"  # bonifico
_DEFAULT_CONDIZIONI = "TP02"  # pagamento completo
_DEFAULT_REGIME = "RF01"  # ordinario


def _e(parent: ET.Element, tag: str, text: Optional[str] = None) -> ET.Element:
    """Create child element with optional text content."""
    el = ET.SubElement(parent, tag)
    if text is not None:
        el.text = str(text)
    return el


def _fmt_money(value) -> str:
    """Format Decimal/float as SDI 2-decimal string (HALF_UP)."""
    d = to_decimal(value)
    return f"{money_round(d):.2f}"


def _fmt_qty(value) -> str:
    """Format quantity as SDI string (5 decimal supported, trim trailing 0)."""
    d = to_decimal(value).quantize(Decimal("0.00001"))
    s = f"{d:.5f}".rstrip("0").rstrip(".")
    return s or "0"


def _split_name(legal_name: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Estrai (denominazione, nome, cognome) da una legal_name.
    Per persone giuridiche: denominazione=intero, nome/cognome=None.
    MediaFlow lavora B2B → sempre denominazione."""
    if not legal_name:
        return (None, None, None)
    return (legal_name.strip(), None, None)


def _build_header(root: ET.Element, invoice, tenant, progressivo: str) -> None:
    """FatturaElettronicaHeader: DatiTrasmissione + Cedente + Cessionario."""
    header = _e(root, "FatturaElettronicaHeader")

    # ─── DatiTrasmissione ───
    dt = _e(header, "DatiTrasmissione")
    id_trasm = _e(dt, "IdTrasmittente")
    _e(id_trasm, "IdPaese", "IT")
    _e(id_trasm, "IdCodice", _strip_it(tenant.vat_number or ""))
    _e(dt, "ProgressivoInvio", progressivo)
    _e(dt, "FormatoTrasmissione", _FORMATO_TRASMISSIONE)
    # Codice destinatario: 7-char (privati) o 6-char (PA, Codice Univoco
    # Ufficio iPA). v3.5.0-alpha.172.142 — prima solo 7-char → i codici PA a
    # 6 char venivano persi (fallback 0000000). Ora emessi entrambi.
    sdi = (invoice.client_sdi_snap or "").strip().upper()
    if sdi and len(sdi) in (6, 7):
        _e(dt, "CodiceDestinatario", sdi)
    else:
        _e(dt, "CodiceDestinatario", "0000000")
        if invoice.client_pec_snap:
            _e(dt, "PECDestinatario", invoice.client_pec_snap.strip())

    # ─── CedentePrestatore (tenant) ───
    cp = _e(header, "CedentePrestatore")
    cp_da = _e(cp, "DatiAnagrafici")
    cp_id = _e(cp_da, "IdFiscaleIVA")
    _e(cp_id, "IdPaese", getattr(tenant, "country", None) or "IT")
    _e(cp_id, "IdCodice", _strip_it(invoice.tenant_vat_snap or tenant.vat_number or ""))
    if invoice.tenant_tax_code_snap or tenant.tax_code:
        _e(cp_da, "CodiceFiscale", invoice.tenant_tax_code_snap or tenant.tax_code)
    cp_anag = _e(cp_da, "Anagrafica")
    denom, _n, _c = _split_name(invoice.tenant_legal_name_snap or tenant.legal_name or tenant.name)
    _e(cp_anag, "Denominazione", denom or "")
    _e(cp_da, "RegimeFiscale", invoice.tenant_fiscal_regime_snap or tenant.fiscal_regime or _DEFAULT_REGIME)
    # Sede legale tenant — v3.5.0-alpha.172.60 usa campi strutturati con
    # fallback ad `address` legacy free-text.
    cp_sede = _e(cp, "Sede")
    _e(cp_sede, "Indirizzo", _safe(
        getattr(tenant, "street_address", None) or invoice.tenant_address_snap or tenant.address
    ))
    _e(cp_sede, "CAP", _safe(getattr(tenant, "zip_code", None) or "00000"))
    _e(cp_sede, "Comune", _safe(getattr(tenant, "city", None) or "—"))
    if getattr(tenant, "province", None):
        _e(cp_sede, "Provincia", tenant.province)
    _e(cp_sede, "Nazione", getattr(tenant, "country", None) or "IT")
    # ─── IscrizioneREA (società di capitali IT) ───
    # v3.5.0-alpha.172.60 — Sezione opzionale ma obbligatoria per SRL/SPA.
    # Emessa SOLO se tenant ha tutti i campi minimi (rea_office + rea_number).
    rea_office = getattr(tenant, "rea_office", None)
    rea_num = tenant.rea_number
    if rea_office and rea_num:
        cp_rea = _e(cp, "IscrizioneREA")
        _e(cp_rea, "Ufficio", rea_office.upper().strip())
        _e(cp_rea, "NumeroREA", str(rea_num).strip())
        cap_eur = getattr(tenant, "rea_capital_eur", None)
        if cap_eur is not None and cap_eur > 0:
            _e(cp_rea, "CapitaleSociale", _fmt_money(cap_eur))
        socio = getattr(tenant, "socio_unico", None)
        if socio in ("SU", "SM"):
            _e(cp_rea, "SocioUnico", socio)
        _e(cp_rea, "StatoLiquidazione", getattr(tenant, "stato_liquidazione", None) or "LN")
    # ─── Contatti tenant (opzionale) ───
    if tenant.email or tenant.phone:
        cp_cont = _e(cp, "Contatti")
        if tenant.phone:
            _e(cp_cont, "Telefono", tenant.phone.strip()[:12])
        if tenant.email:
            _e(cp_cont, "Email", tenant.email.strip())

    # ─── CessionarioCommittente (cliente) ───
    cc = _e(header, "CessionarioCommittente")
    cc_da = _e(cc, "DatiAnagrafici")
    if invoice.client_vat_snap:
        cc_id = _e(cc_da, "IdFiscaleIVA")
        _e(cc_id, "IdPaese", "IT")
        _e(cc_id, "IdCodice", _strip_it(invoice.client_vat_snap))
    if invoice.client_tax_code_snap:
        _e(cc_da, "CodiceFiscale", invoice.client_tax_code_snap)
    cc_anag = _e(cc_da, "Anagrafica")
    denom_c, _n, _c = _split_name(invoice.client_legal_name_snap)
    _e(cc_anag, "Denominazione", denom_c or "—")
    # Sede cliente
    cc_sede = _e(cc, "Sede")
    _e(cc_sede, "Indirizzo", _safe(invoice.client_address_snap))
    _e(cc_sede, "CAP", _safe(invoice.client_zip_snap or "00000"))
    _e(cc_sede, "Comune", _safe(invoice.client_city_snap or "—"))
    if invoice.client_province_snap:
        _e(cc_sede, "Provincia", invoice.client_province_snap)
    _e(cc_sede, "Nazione", invoice.client_country_snap or "IT")


def _build_body(root: ET.Element, invoice) -> None:
    """FatturaElettronicaBody: DatiGenerali + DatiBeniServizi + DatiPagamento."""
    body = _e(root, "FatturaElettronicaBody")

    # ─── DatiGenerali ───
    dg = _e(body, "DatiGenerali")
    dgd = _e(dg, "DatiGeneraliDocumento")
    _e(dgd, "TipoDocumento", invoice.doc_type or "TD01")
    _e(dgd, "Divisa", _DIVISA)
    _e(dgd, "Data", str(invoice.issue_date))
    _e(dgd, "Numero", invoice.number)
    _e(dgd, "ImportoTotaleDocumento", _fmt_money(invoice.total or 0))
    _e(dgd, "Causale", invoice.notes or _DEFAULT_CAUSALE)

    # ─── DatiBeniServizi ───
    dbs = _e(body, "DatiBeniServizi")
    # Per ogni linea
    lines = sorted(invoice.lines or [], key=lambda x: x.id)
    by_rate: dict = {}  # aliquota → {imponibile, imposta}
    for idx, ln in enumerate(lines, start=1):
        dl = _e(dbs, "DettaglioLinee")
        _e(dl, "NumeroLinea", str(idx))
        _e(dl, "Descrizione", (ln.description or "—")[:1000])
        _e(dl, "Quantita", _fmt_qty(ln.quantity or 1))
        _e(dl, "PrezzoUnitario", _fmt_money(ln.unit_price or 0))
        _e(dl, "PrezzoTotale", _fmt_money(ln.total or 0))
        rate = to_decimal(ln.vat_rate or invoice.vat_rate or 22)
        _e(dl, "AliquotaIVA", f"{rate:.2f}")
        # TODO: Natura se rate=0 (delegato a future config UI per riga)
        # Accumula per riepilogo
        k = f"{rate:.2f}"
        b = by_rate.setdefault(k, {"imponibile": Decimal("0"), "imposta": Decimal("0"), "aliquota": rate})
        line_total = to_decimal(ln.total or 0)
        b["imponibile"] += line_total
        b["imposta"] += money_round(line_total * rate / Decimal("100"))

    # ─── DatiRiepilogo (per aliquota IVA) ───
    for k, vals in sorted(by_rate.items(), key=lambda kv: kv[0]):
        dr = _e(dbs, "DatiRiepilogo")
        _e(dr, "AliquotaIVA", f"{vals['aliquota']:.2f}")
        _e(dr, "ImponibileImporto", _fmt_money(vals["imponibile"]))
        _e(dr, "Imposta", _fmt_money(vals["imposta"]))
        _e(dr, "EsigibilitaIVA", "I")  # I=immediata (default)

    # ─── DatiPagamento ───
    dp = _e(body, "DatiPagamento")
    _e(dp, "CondizioniPagamento", _DEFAULT_CONDIZIONI)
    ddp = _e(dp, "DettaglioPagamento")
    _e(ddp, "ModalitaPagamento",
       _map_payment_method(invoice.payment_method) or _DEFAULT_METODO_PAGAMENTO)
    if invoice.due_date:
        _e(ddp, "DataScadenzaPagamento", str(invoice.due_date))
    _e(ddp, "ImportoPagamento", _fmt_money(invoice.total or 0))
    if invoice.iban_snapshot:
        _e(ddp, "IBAN", invoice.iban_snapshot.replace(" ", "").upper())


def _map_payment_method(internal: Optional[str]) -> Optional[str]:
    """Map MediaFlow payment_method free-text → codice SDI MP01-MP23."""
    if not internal:
        return None
    s = internal.strip().lower()
    if "bonifico" in s:
        return "MP05"
    if "contanti" in s or "cash" in s:
        return "MP01"
    if "assegno" in s:
        return "MP02"
    if "carta" in s or "card" in s:
        return "MP08"
    if "riba" in s:
        return "MP09"
    if "rid" in s:
        return "MP12"
    if "pagopa" in s:
        return "MP23"
    return None  # default fallback applicato dal chiamante


def _strip_it(piva: str) -> str:
    """Rimuovi prefisso `IT` da P.IVA."""
    s = (piva or "").strip().upper().replace(" ", "")
    return s.lstrip("IT")


def _safe(s: Optional[str]) -> str:
    """None → stringa vuota. SDI accetta vuoto su alcuni campi opzionali."""
    return (s or "—").strip() or "—"


def get_sdi_filename(tenant_vat: str, progressivo: str) -> str:
    """Compose SDI filename: IT{piva}_{progressivo}.xml.

    Naming spec FatturaPA: IT + 11 cifre P.IVA + _ + progressivo univoco
    + .xml. Progressivo è alfanumerico univoco per cedente (Base32 5 char
    abbastanza per ~30M fatture).
    """
    piva = _strip_it(tenant_vat)
    return f"IT{piva}_{progressivo}.xml"


def _next_progressivo(invoice_id: int, year: int) -> str:
    """Genera progressivo univoco per invio. Base32 5-char da (year, id).

    Univoco per cedente. Convenzione MediaFlow: deriva da invoice.id +
    year per stabilità (re-emissione XML dello stesso invoice = stesso
    progressivo).
    """
    n = ((year % 100) * 1_000_000) + invoice_id
    # Base32-like Crockford (no I,L,O,U)
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    out = ""
    x = n
    for _ in range(5):
        out = alphabet[x % 32] + out
        x //= 32
    return out


def build_fattura_xml(invoice, tenant) -> Tuple[str, str]:
    """Build FatturaPA v1.6.1 XML string + SDI filename.

    Args:
        invoice: Invoice ORM record (deve avere campi `*_snap` popolati
                 + `lines` relationship caricata).
        tenant:  Tenant ORM record (fallback per snapshot mancanti).

    Returns:
        (xml_string, filename) — xml_string è UTF-8 con declaration,
        filename segue convention SDI IT{piva}_{progressivo}.xml
    """
    progressivo = _next_progressivo(
        invoice.id, (invoice.issue_date.year if invoice.issue_date else _date.today().year)
    )

    # Root element con namespaces
    ET.register_namespace("p", _NS_P)
    ET.register_namespace("ds", _NS_DS)
    ET.register_namespace("xsi", _NS_XSI)
    root = ET.Element(
        f"{{{_NS_P}}}FatturaElettronica",
        attrib={
            f"{{{_NS_XSI}}}schemaLocation": (
                f"{_NS_P} http://www.fatturapa.gov.it/export/fatturazione/sdi/fatturapa/v1.2/Schema_del_file_xml_FatturaPA_versione_1.2.xsd"
            ),
            "versione": _FORMATO_TRASMISSIONE,
        },
    )

    _build_header(root, invoice, tenant, progressivo)
    _build_body(root, invoice)

    # Serializzazione XML con declaration
    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    xml_str = xml_bytes.decode("utf-8")

    filename = get_sdi_filename(
        invoice.tenant_vat_snap or tenant.vat_number or "00000000000",
        progressivo,
    )
    return xml_str, filename
