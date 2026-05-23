"""Italian tax compliance validators — Sprint 5.E BLOCCO 6 audit.

Foundation per validazione campi fiscali italiani:
- P.IVA (Luhn mod-10 checksum 11 cifre)
- Codice fiscale (16 alfanum persona fisica / 11 cifre PG)
- Codice SDI (7 alfanum, casi speciali 0000000/999999)
- IBAN IT (mod-97)
- Enum RegimeFiscale RF01-RF19
- Enum TipoDocumento TD01-TD28
- Enum NaturaIVA N1-N7.x

Riferimento spec: developers.italia.it/en/fatturapa/, schema FatturaPA v1.6.1+.

Wire-up nei router (clients.py, billing.py, finance.py, tenants.py, suppliers.py)
fatto in Sprint 6 — qui solo foundation per import via `from app.services.italian_tax import ...`.

Quando il MCP server `fattura-elettronica-it` è disponibile, DELEGARE
validazioni avanzate (XSD, CedentePrestatore completo) al server. Questo
modulo copre solo i check field-level base.
"""
from __future__ import annotations
import re
from typing import Optional, Set

# ── Enum: RegimeFiscale RF01-RF19 (snapshot v1.6.1) ─────────────
REGIME_FISCALE_CODES: Set[str] = {
    "RF01", "RF02", "RF04", "RF05", "RF06", "RF07", "RF08", "RF09",
    "RF10", "RF11", "RF12", "RF13", "RF14", "RF15", "RF16", "RF17",
    "RF18", "RF19",
}
REGIME_FISCALE_LABELS = {
    "RF01": "Ordinario",
    "RF02": "Contribuenti minimi",
    "RF04": "Agricoltura/pesca",
    "RF05": "Vendita sali e tabacchi",
    "RF06": "Commercio fiammiferi",
    "RF07": "Editoria",
    "RF08": "Telefonia pubblica",
    "RF09": "Rivendita documenti trasporto pubblico",
    "RF10": "Intrattenimenti/giochi DPR 640/72",
    "RF11": "Agenzie viaggi (art. 74-ter)",
    "RF12": "Agriturismo",
    "RF13": "Vendite a domicilio",
    "RF14": "Beni usati/arte/antiquariato",
    "RF15": "Vendite all'asta arte/antiquariato",
    "RF16": "IVA per cassa P.A.",
    "RF17": "IVA per cassa (DL 83/2012)",
    "RF18": "Altro",
    "RF19": "Forfettario (L. 190/2014)",
}

# ── Enum: TipoDocumento TD01-TD28 ───────────────────────────────
TIPO_DOCUMENTO_CODES: Set[str] = {
    "TD01", "TD02", "TD03", "TD04", "TD05", "TD06",
    "TD16", "TD17", "TD18", "TD19", "TD20", "TD21",
    "TD22", "TD23", "TD24", "TD25", "TD26", "TD27", "TD28",
}
TIPO_DOCUMENTO_LABELS = {
    "TD01": "Fattura",
    "TD02": "Acconto/anticipo su fattura",
    "TD03": "Acconto/anticipo su parcella",
    "TD04": "Nota di credito",
    "TD05": "Nota di debito",
    "TD06": "Parcella",
    "TD16": "Integrazione reverse charge interno",
    "TD17": "Integrazione/autofattura servizi UE",
    "TD18": "Integrazione beni intra-UE",
    "TD19": "Integrazione/autofattura art.17 c.2",
    "TD20": "Autofattura per regolarizzazione",
    "TD21": "Autofattura per splafonamento",
    "TD22": "Estrazione beni da Deposito IVA",
    "TD23": "Estrazione beni Deposito IVA con IVA",
    "TD24": "Fattura differita art.21 c.4",
    "TD25": "Fattura differita art.21 c.4 lett.b",
    "TD26": "Cessione beni ammortizzabili",
    "TD27": "Fattura per autoconsumo",
    "TD28": "Acquisti da San Marino con IVA (B2B)",
}

# ── Enum: NaturaIVA N1-N7.x ─────────────────────────────────────
NATURA_IVA_CODES: Set[str] = {
    "N1",
    "N2.1", "N2.2",
    "N3.1", "N3.2", "N3.3", "N3.4", "N3.5", "N3.6",
    "N4",
    "N5",
    "N6.1", "N6.2", "N6.3", "N6.4", "N6.5", "N6.6", "N6.7", "N6.8", "N6.9",
    "N7",
}


# ── Validators ──────────────────────────────────────────────────

def validate_partita_iva(p_iva: Optional[str]) -> bool:
    """Valida P.IVA italiana: 11 cifre + Luhn mod-10 checksum.

    Tollera prefisso `IT` (es. "IT12345678901"). Tollera whitespace.
    Ritorna False per None/vuoto/formato errato.
    """
    if not p_iva:
        return False
    s = p_iva.strip().upper().replace(" ", "").lstrip("IT")
    if len(s) != 11 or not s.isdigit():
        return False
    total = 0
    for i, c in enumerate(s[:10]):
        n = int(c)
        if i % 2 == 1:  # cifre dispari (1-based: 2,4,6,8,10) → ×2
            n *= 2
            if n > 9:
                n -= 9
        total += n
    check = (10 - (total % 10)) % 10
    return check == int(s[10])


_CF_PERSONA_FISICA_RE = re.compile(
    r"^[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]$"
)


def validate_codice_fiscale(cf: Optional[str]) -> bool:
    """Valida codice fiscale italiano.

    Persona fisica: 16 alfanumerici, pattern [A-Z]{6}\\d{2}[A-Z]\\d{2}[A-Z]\\d{3}[A-Z]
    Persona giuridica: 11 cifre (= P.IVA — delega a validate_partita_iva).

    NON valida checksum CF persona fisica (algoritmo complesso non standard
    SDI-blocking). Per full checksum usa lib `codicefiscale`.
    """
    if not cf:
        return False
    s = cf.strip().upper().replace(" ", "")
    if len(s) == 16:
        return bool(_CF_PERSONA_FISICA_RE.match(s))
    if len(s) == 11:
        return validate_partita_iva(s)
    return False


def validate_sdi_code(sdi: Optional[str]) -> bool:
    """Valida codice destinatario SDI.

    - 7 alfanumerici uppercase (società)
    - `0000000` (consumer/PEC-only)
    - `999999` (PA, 6 caratteri)
    - `XXXXXXX` (estero, 7 caratteri)
    """
    if not sdi:
        return False
    s = sdi.strip().upper()
    if s == "999999":
        return True
    if len(s) == 7 and s.isalnum():
        return True
    return False


_IBAN_IT_RE = re.compile(r"^IT\d{2}[A-Z]\d{10}[A-Z0-9]{12}$")


def validate_iban_it(iban: Optional[str]) -> bool:
    """Valida IBAN italiano via mod-97 (ISO 13616).

    Format IT: `IT` + 2 cifre check + 1 CIN + 5 ABI + 5 CAB + 12 conto = 27.
    """
    if not iban:
        return False
    s = iban.strip().upper().replace(" ", "")
    if len(s) != 27 or not _IBAN_IT_RE.match(s):
        return False
    rearranged = s[4:] + s[:4]
    try:
        numeric = "".join(
            str(ord(c) - 55) if c.isalpha() else c for c in rearranged
        )
        return int(numeric) % 97 == 1
    except (ValueError, OverflowError):
        return False


def validate_regime_fiscale(code: Optional[str]) -> bool:
    """Valida codice regime fiscale RF01-RF19."""
    if not code:
        return False
    return code.strip().upper() in REGIME_FISCALE_CODES


def validate_tipo_documento(code: Optional[str]) -> bool:
    """Valida codice tipo documento TD01-TD28."""
    if not code:
        return False
    return code.strip().upper() in TIPO_DOCUMENTO_CODES


def validate_natura_iva(code: Optional[str]) -> bool:
    """Valida codice natura IVA N1-N7.x."""
    if not code:
        return False
    return code.strip().upper() in NATURA_IVA_CODES


# ── Helpers di mapping (semantica MediaFlow) ────────────────────

def map_invoice_kind_to_tipo_documento(kind: Optional[str], is_credit_note: bool = False) -> str:
    """Mappa Invoice.kind (MediaFlow) → TD code SDI.

    - `advance` → TD02 (acconto/anticipo)
    - `regular` / `balance` → TD01 (fattura standard)
    - Override `is_credit_note=True` → TD04 (Nota di credito) per storno
    """
    if is_credit_note:
        return "TD04"
    if kind == "advance":
        return "TD02"
    return "TD01"


def invoice_sdi_compliance_check(
    *,
    client_vat: Optional[str],
    client_tax_code: Optional[str],
    client_sdi: Optional[str],
    client_pec: Optional[str],
    client_country: Optional[str],
    tenant_vat: Optional[str],
    tenant_fiscal_regime: Optional[str],
    vat_rate: Optional[float],
    natura: Optional[str] = None,
) -> list[str]:
    """Pre-emit check: ritorna lista errori bloccanti per invio SDI.
    Lista vuota = fattura emissibile. Lista non-vuota = HARD-BLOCK.
    """
    errors: list[str] = []
    # Cessionario (cliente): almeno uno tra vat o tax_code
    if not (client_vat or client_tax_code):
        errors.append("Manca P.IVA o codice fiscale del cliente (cessionario)")
    elif client_vat and not validate_partita_iva(client_vat):
        errors.append(f"P.IVA cliente non valida: {client_vat}")
    # Recapito: SDI 7-char OPPURE PEC
    if not (client_sdi or client_pec):
        errors.append("Manca codice destinatario SDI o PEC del cliente")
    elif client_sdi and not validate_sdi_code(client_sdi):
        errors.append(f"Codice SDI cliente non valido: {client_sdi}")
    # Cedente (tenant): P.IVA + regime
    if not tenant_vat:
        errors.append("Manca P.IVA del tenant (cedente)")
    elif not validate_partita_iva(tenant_vat):
        errors.append(f"P.IVA tenant non valida: {tenant_vat}")
    if not tenant_fiscal_regime:
        errors.append("Manca regime fiscale tenant (RF01-RF19)")
    elif not validate_regime_fiscale(tenant_fiscal_regime):
        errors.append(f"Regime fiscale tenant non valido: {tenant_fiscal_regime}")
    # Natura IVA obbligatoria se vat_rate=0
    if vat_rate is not None and float(vat_rate) == 0.0:
        if not natura:
            errors.append("Natura IVA obbligatoria quando vat_rate=0 (N1-N7)")
        elif not validate_natura_iva(natura):
            errors.append(f"Natura IVA non valida: {natura}")
    return errors
