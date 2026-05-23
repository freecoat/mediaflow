"""Calcolo totali fattura da InvoiceLine — Sprint 3.D BLOCCO 4 audit.

Pre-α.172.37 i totali fattura erano calcolati sul subtotal aggregato:
    vat_amount = subtotal * vat_rate_header / 100

Questo è CORRETTO solo quando tutte le InvoiceLine hanno lo stesso
`vat_rate`. Per fatture multi-aliquota (futuro UI differenziato per
riga, requisito FatturaPA con `<DatiRiepilogo>` per aliquota/natura)
il totale aggregato arrotonda diversamente da Σ(line.total × line.vat_rate).

Questo modulo centralizza il calcolo per-riga + riepilogo per aliquota,
in modo che (a) header Invoice.subtotal/total restino coerenti, (b)
emissione FatturaPA XML futura possa generare `<DatiRiepilogo>` per
ogni aliquota distinta.

v3.5.0-alpha.172.38 (Sprint 3.5) — calcolo interno con `Decimal` per
garantire Σ(round(x, 2)) = round(Σ(x), 2) anche su molte righe.
Persistenza resta `float` (colonne SQLite Float legacy); Sprint 5 +
porting Postgres convertirà colonne a `Numeric(15,2)`.
"""
from __future__ import annotations
from decimal import Decimal
from typing import Iterable, List, Dict, Any

from app.services.money import to_decimal, money_round


def compute_invoice_totals_from_lines(lines: Iterable[Any]) -> dict:
    """Aggrega subtotal/vat/total + riepilogo per aliquota.

    `lines` = iterable di InvoiceLine (o oggetti con attr `total`, `vat_rate`,
    `discount_pct` opzionale).

    Ritorna:
        {
          "subtotal": Σ(line.total),
          "vat_amount": Σ(line.total × line.vat_rate / 100),
          "total": subtotal + vat_amount,
          "by_rate": [
            {"rate": 22.0, "subtotal": ..., "vat_amount": ..., "lines": N},
            {"rate": 10.0, ...},
          ],
        }

    Tutti gli importi arrotondati a 2 decimali HALF_UP (precisione SDI).
    Calcolo interno via `Decimal` per stabilità su grandi aggregati;
    boundary di output torna `float` per back-compat colonne Float.
    """
    sub_total = Decimal("0")
    vat_total = Decimal("0")
    buckets: Dict[Decimal, Dict[str, Any]] = {}

    for ln in lines:
        line_total = to_decimal(getattr(ln, "total", 0.0))
        rate = to_decimal(getattr(ln, "vat_rate", 0.0))
        line_vat = money_round(line_total * rate / Decimal("100"))
        sub_total += line_total
        vat_total += line_vat
        b = buckets.setdefault(rate, {
            "subtotal": Decimal("0"), "vat_amount": Decimal("0"), "lines": 0,
        })
        b["subtotal"] += line_total
        b["vat_amount"] += line_vat
        b["lines"] += 1

    sub_total_r = money_round(sub_total)
    vat_total_r = money_round(vat_total)
    by_rate: List[dict] = []
    for rate in sorted(buckets.keys()):
        b = buckets[rate]
        by_rate.append({
            "rate": float(rate),
            "subtotal": float(money_round(b["subtotal"])),
            "vat_amount": float(money_round(b["vat_amount"])),
            "lines": int(b["lines"]),
        })

    return {
        "subtotal": float(sub_total_r),
        "vat_amount": float(vat_total_r),
        "total": float(money_round(sub_total_r + vat_total_r)),
        "by_rate": by_rate,
    }


def apply_totals_to_invoice(invoice, totals: dict) -> None:
    """Applica `totals` (output di compute_invoice_totals_from_lines) su
    `invoice.subtotal` / `invoice.total`. NON tocca `invoice.vat_rate`
    header (resta come hint UI / fallback per nuove righe).

    Idempotente: ri-chiamarlo con stessi totals non cambia nulla.
    """
    invoice.subtotal = totals.get("subtotal", 0.0)
    invoice.total = totals.get("total", 0.0)
