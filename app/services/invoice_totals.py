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
"""
from __future__ import annotations
from typing import Iterable, List, Dict, Any


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

    Tutti gli importi arrotondati a 2 decimali (precisione SDI).
    Se `lines` è vuoto, ritorna struttura zero.
    """
    sub_total = 0.0
    vat_total = 0.0
    buckets: Dict[float, Dict[str, Any]] = {}

    for ln in lines:
        line_total = float(getattr(ln, "total", 0.0) or 0.0)
        rate = float(getattr(ln, "vat_rate", 0.0) or 0.0)
        line_vat = round(line_total * rate / 100.0, 2)
        sub_total += line_total
        vat_total += line_vat
        b = buckets.setdefault(rate, {"subtotal": 0.0, "vat_amount": 0.0, "lines": 0})
        b["subtotal"] += line_total
        b["vat_amount"] += line_vat
        b["lines"] += 1

    sub_total = round(sub_total, 2)
    vat_total = round(vat_total, 2)
    by_rate: List[dict] = []
    for rate in sorted(buckets.keys()):
        b = buckets[rate]
        by_rate.append({
            "rate": rate,
            "subtotal": round(b["subtotal"], 2),
            "vat_amount": round(b["vat_amount"], 2),
            "lines": int(b["lines"]),
        })

    return {
        "subtotal": sub_total,
        "vat_amount": vat_total,
        "total": round(sub_total + vat_total, 2),
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
