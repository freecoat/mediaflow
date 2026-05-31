"""Conversione/formattazione valuta — v3.5.0-alpha.172.155.

Single source per la conversione DISPLAY tra valuta base (verità) e valuta
cliente. Gli importi in DB sono SEMPRE in base; qui si converte solo per
visualizzazione/PDF. Tasso: fx_rate_to_base = "quanti base per 1 unità valuta
cliente" (es. base EUR, 1 USD = 0,92 EUR -> 0.92). Display in valuta = base / rate.
"""
from __future__ import annotations
from typing import Optional

from app.services.money import to_decimal, money_round, money_to_float

SUPPORTED = ["EUR", "USD", "GBP", "CHF"]

_SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF"}


def symbol(ccy: Optional[str]) -> str:
    if not ccy:
        return ""
    return _SYMBOLS.get(ccy.upper(), ccy.upper())


def to_display(amount_base: float, fx_rate_to_base: float) -> float:
    """base -> valuta cliente. rate<=0 trattato come 1.0 (safety)."""
    r = fx_rate_to_base if fx_rate_to_base and fx_rate_to_base > 0 else 1.0
    return money_to_float(money_round(to_decimal(amount_base) / to_decimal(r)))


def to_base(amount_ccy: float, fx_rate_to_base: float) -> float:
    """valuta cliente -> base."""
    r = fx_rate_to_base if fx_rate_to_base and fx_rate_to_base > 0 else 1.0
    return money_to_float(money_round(to_decimal(amount_ccy) * to_decimal(r)))


def format_money(amount_base: float, ccy: str, fx_rate_to_base: float) -> str:
    """Formato IT '1.234,56 $' del valore convertito in valuta cliente."""
    v = to_display(amount_base, fx_rate_to_base)
    s = f"{v:,.2f}"  # '1,234.56'
    s = s.replace(",", "§").replace(".", ",").replace("§", ".")  # -> '1.234,56'
    return f"{s} {symbol(ccy)}"


def freeze_invoice_fx(db, inv, base: str):
    """Congela sull'Invoice il tasso BCE della data di emissione (issue_date).

    Conversione legale art. 13 c.4 DPR 633/72. Imposta `fx_rate_to_base` (=
    quanti `base` per 1 unità della valuta della fattura) e `fx_rate_fixed_at`
    (timestamp del congelamento). Per fatture in valuta base è un no-op che
    fissa rate=1.0 (nessuna chiamata di rete). Solleva HTTPException 422 se il
    tasso non è disponibile e la valuta != base.
    """
    from fastapi import HTTPException
    from app.services import fx
    from app.services.clock import now_utc
    ccy = (getattr(inv, "currency", None) or base).upper()
    if ccy == base.upper():
        inv.fx_rate_to_base = 1.0
        inv.fx_rate_fixed_at = now_utc()
        return
    d = getattr(inv, "issue_date", None) or now_utc().date()
    rate = fx.get_fx_rate_on(db, ccy, base, d)
    if rate is None:
        raise HTTPException(422, "Tasso di cambio non disponibile per la data di emissione")
    inv.fx_rate_to_base = rate
    inv.fx_rate_fixed_at = now_utc()


def disclaimer(base: str, ccy: str, rate: float, date_str: str, *, emitted: bool = False) -> str:
    """Testo disclaimer legale (tenant IT). Centralizzato per adattamento futuro
    a mercati esteri."""
    if emitted:
        return (f"Importi convertiti al tasso BCE alla data di emissione della fattura "
                f"({date_str}, {rate} {ccy}/{base}). Ai fini fiscali imponibile e imposta "
                f"sono espressi in {base}.")
    return (f"La quotazione è espressa in {base}. Gli importi in {ccy} sono "
            f"indicativi, convertiti al tasso BCE del {date_str} ({rate} {ccy}/{base}). "
            f"La conversione definitiva applica il tasso BCE in vigore alla data di "
            f"emissione della fattura (art. 13, c. 4, DPR 633/1972).")
