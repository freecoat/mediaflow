"""Money utilities — Sprint 3.5 minimal (v3.5.0-alpha.172.38).

Decision audit BLOCCO 4 (option C): SQLite memorizza già float64 (~15
cifre significative), errori di rappresentazione sui float monetari sono
trascurabili a scale MediaFlow realistica (centinaia di righe/fattura,
non milioni). Conversione di tutti i ~70 campi Float → Numeric(15,2)
rimandata a porting Postgres futuro (high-risk migration, basso ROI ora).

Sprint 3.5 minimale = uso Decimal al boundary di aggregazione critica
(invoice_totals.compute_invoice_totals_from_lines) per garantire
Σ(round(x, 2)) == round(Σ(x), 2) anche su molte righe.

Helper qui esposti:
- `to_decimal(value)` — float → Decimal stabile
- `money_round(d)` — Decimal → Decimal arrotondato 2 cifre, HALF_UP
- `money_to_float(d)` — Decimal → float per persistenza (back-compat)

Roadmap: a porting Postgres convertire colonne a `Numeric(15, 2)` e
introdurre type adapter SQLAlchemy che restituisce Decimal direttamente
(eliminando questa indirezione).
"""
from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from typing import Union

Number = Union[int, float, Decimal, str, None]


def to_decimal(value: Number) -> Decimal:
    """Conversione safe a Decimal. None → Decimal(0)."""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    # str() invece di Decimal(float) per evitare rappresentazione binaria
    return Decimal(str(value))


def money_round(value: Decimal) -> Decimal:
    """Arrotonda a 2 cifre con HALF_UP (convenzione bancaria/fiscale).

    Python default banker's rounding (HALF_EVEN) può deviare da
    aspettative SDI/FatturaPA che usa HALF_UP standard.
    """
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def money_to_float(value: Decimal) -> float:
    """Decimal → float per persistenza colonna Float legacy.
    Conversione obbligatoriamente dopo `money_round` per garantire
    stabilità di scrittura."""
    return float(value)
