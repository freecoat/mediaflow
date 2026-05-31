# Currency Conversion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convertire quote e fattura in valuta cliente ($/£/CHF) mantenendo la verità degli importi in valuta base (EUR), con conversione indicativa live sulla quote e conversione vincolante congelata all'emissione fattura (tasso BCE del giorno).

**Architecture:** Base-anchored. Tutti gli importi in DB restano in valuta base. Un servizio `currency.py` centralizza conversione/formattazione/disclaimer. La quote mostra conversione live (frankfurter=BCE) + disclaimer; la fattura congela il tasso della data di emissione su `Invoice.fx_rate_to_base`/`fx_rate_fixed_at`. XML SDI sempre in EUR. Spec: `docs/superpowers/specs/2026-05-31-currency-conversion-design.md`.

**Tech Stack:** FastAPI + SQLAlchemy 2.0, Jinja2 + vanilla JS, ReportLab (PDF), frankfurter (FX BCE), pytest. Venv: `.venv/Scripts/python.exe`.

**Convenzioni progetto:** `fx.get_fx_rate(db, from, to)` = "quanti `to` per 1 `from`" → `fx_rate_to_base = get_fx_rate(db, currency, base)`. Money via `app.services.money` (`to_decimal`, `money_round` HALF_UP 2dp, `money_to_float`). Commit a ogni task (bump versione + CHANGELOG separati, fatti dall'utente a fine batch).

---

## Phase 0 — Foundation

### Task 1: Servizio `currency.py`

**Files:**
- Create: `app/services/currency.py`
- Test: `tests/test_currency.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_currency.py
import pytest
from app.services import currency as cur


@pytest.mark.parametrize("base,rate,expected", [
    (100.0, 1.0, 100.0),
    (920.0, 0.92, 1000.0),   # 920 EUR / 0.92 = 1000 USD
    (100.0, 0.92, 108.7),    # 100/0.92=108.695.. -> 108.70 HALF_UP
])
def test_to_display(base, rate, expected):
    assert cur.to_display(base, rate) == expected


@pytest.mark.parametrize("ccy_amt,rate,expected", [
    (1000.0, 0.92, 920.0),   # 1000 USD * 0.92 = 920 EUR base
    (100.0, 1.0, 100.0),
])
def test_to_base(ccy_amt, rate, expected):
    assert cur.to_base(ccy_amt, rate) == expected


def test_roundtrip_base_preserved():
    base = 1234.56
    disp = cur.to_display(base, 0.92)
    assert abs(cur.to_base(disp, 0.92) - base) < 0.02  # entro arrotondamento


def test_symbol():
    assert cur.symbol("EUR") == "€"
    assert cur.symbol("USD") == "$"
    assert cur.symbol("GBP") == "£"
    assert cur.symbol("CHF") == "CHF"
    assert cur.symbol("XXX") == "XXX"


def test_supported():
    assert cur.SUPPORTED == ["EUR", "USD", "GBP", "CHF"]


def test_format_money():
    # formato IT: separatore migliaia ".", decimali ","
    assert cur.format_money(1234.5, "USD", 1.0) == "1.234,50 $"
    assert cur.format_money(1000.0, "USD", 0.92) == "1.086,96 $"  # 1000/0.92


def test_disclaimer_indicative_mentions_base_and_norm():
    d = cur.disclaimer("EUR", "USD", 0.92, "31/05/2026")
    assert "EUR" in d and "USD" in d and "DPR 633" in d


def test_disclaimer_emitted_mentions_emission():
    d = cur.disclaimer("EUR", "USD", 0.92, "31/05/2026", emitted=True)
    assert "emissione" in d.lower()
    assert "imponibile" in d.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_currency.py -q`
Expected: FAIL (ModuleNotFoundError: app.services.currency)

- [ ] **Step 3: Write minimal implementation**

```python
# app/services/currency.py
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


def disclaimer(base: str, ccy: str, rate: float, date_str: str, *, emitted: bool = False) -> str:
    """Testo disclaimer legale (tenant IT). Centralizzato per adattamento futuro
    a mercati esteri (vedi spec §12)."""
    if emitted:
        return (f"Importi convertiti al tasso BCE del {date_str} "
                f"({rate} {ccy}/{base}). Ai fini fiscali imponibile e imposta "
                f"sono espressi in {base}.")
    return (f"La quotazione è espressa in {base}. Gli importi in {ccy} sono "
            f"indicativi, convertiti al tasso BCE del {date_str} ({rate} {ccy}/{base}). "
            f"La conversione definitiva applica il tasso BCE in vigore alla data di "
            f"emissione della fattura (art. 13, c. 4, DPR 633/1972).")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_currency.py -q`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add app/services/currency.py tests/test_currency.py
git commit -m "feat(currency): servizio conversione/formato/disclaimer base-anchored"
```

---

### Task 2: `fx.get_fx_rate_on` (tasso storico per-data)

**Files:**
- Modify: `app/services/fx.py` (aggiungi funzione dopo `refresh_fx_rate`)
- Test: `tests/test_fx_historical.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fx_historical.py
from datetime import date
import app.services.fx as fx


def test_get_fx_rate_on_same_currency(db):
    assert fx.get_fx_rate_on(db, "EUR", "EUR", date(2026, 5, 31)) == 1.0


def test_get_fx_rate_on_uses_dated_endpoint(db, monkeypatch):
    captured = {}
    def fake_fetch_on(from_ccy, to_ccy, d):
        captured["url_date"] = d
        return 0.92
    monkeypatch.setattr(fx, "_fetch_frankfurter_on", fake_fetch_on)
    r = fx.get_fx_rate_on(db, "USD", "EUR", date(2026, 5, 31))
    assert r == 0.92
    assert captured["url_date"] == date(2026, 5, 31)


def test_get_fx_rate_on_none_when_provider_fails(db, monkeypatch):
    monkeypatch.setattr(fx, "_fetch_frankfurter_on", lambda a, b, d: None)
    assert fx.get_fx_rate_on(db, "USD", "EUR", date(2026, 5, 31)) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_fx_historical.py -q`
Expected: FAIL (AttributeError: module 'app.services.fx' has no attribute 'get_fx_rate_on')

- [ ] **Step 3: Write minimal implementation**

Aggiungi in `app/services/fx.py` (dopo `refresh_fx_rate`, prima di `convert`):

```python
def _fetch_frankfurter_on(from_ccy: str, to_ccy: str, on_date) -> Optional[float]:
    """Tasso BCE storico per una data specifica. Endpoint frankfurter /{YYYY-MM-DD}."""
    ds = on_date.isoformat()
    url = f"https://api.frankfurter.app/{ds}?from={from_ccy.upper()}&to={to_ccy.upper()}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MediaFlow/3.5"})
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT_S) as r:
            if r.status != 200:
                log.warning(f"FX historical HTTP {r.status} {from_ccy}->{to_ccy} {ds}")
                return None
            data = json.loads(r.read().decode("utf-8"))
            rate = data.get("rates", {}).get(to_ccy.upper())
            return float(rate) if rate is not None else None
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
        log.warning(f"FX historical error {from_ccy}->{to_ccy} {ds}: {e}")
        return None
    except Exception as e:
        log.exception(f"FX historical unexpected {from_ccy}->{to_ccy} {ds}: {e}")
        return None


def get_fx_rate_on(db: Session, from_ccy: str, to_ccy: str, on_date) -> Optional[float]:
    """Tasso BCE alla data `on_date` (per conversione legale all'emissione fattura,
    art. 13 c.4 DPR 633/72). Non usa la cache single-row (storico per-data).
    None se provider fail."""
    if from_ccy.upper() == to_ccy.upper():
        return 1.0
    return _fetch_frankfurter_on(from_ccy, to_ccy, on_date)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_fx_historical.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/fx.py tests/test_fx_historical.py
git commit -m "feat(fx): get_fx_rate_on tasso BCE storico per-data (emissione fattura)"
```

---

## Phase 1 — Migrazione (precondizione base-anchored)

### Task 3: Migrazione verifica + backfill

**Files:**
- Create: `scripts/migrate_currency_baseanchored.py`
- Test: manuale (`--dry` su DB di lavoro)

- [ ] **Step 1: Write the script**

```python
# scripts/migrate_currency_baseanchored.py
"""Verifica precondizione base-anchored (α.172.155) + backfill currency/fx.

Base-anchored: tutti gli importi DB sono in valuta base. Precondizione: nessuna
quote/fattura reale espressa in valuta != base con tasso != 1.0 (la conversione
non ha mai funzionato pre-155, quindi non dovrebbero esistere). Se ne trova,
STOP con report (vanno valutate a mano). Backfilla currency/fx_rate_to_base dove null.
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.database import SessionLocal
from app.models import models as m


def main(dry=False):
    db = SessionLocal()
    try:
        base = (db.query(m.Tenant).filter(m.Tenant.id == 1).first().default_currency or "EUR").upper()
        bad = []
        for Q in (m.Quote, m.Invoice):
            for row in db.query(Q).all():
                ccy = (getattr(row, "currency", None) or base).upper()
                rate = getattr(row, "fx_rate_to_base", 1.0) or 1.0
                if ccy != base and abs(rate - 1.0) > 1e-9:
                    bad.append((Q.__name__, row.id, ccy, rate))
        if bad:
            print("STOP — esistono quote/fatture in valuta estera con tasso !=1, da gestire a mano:")
            for b in bad:
                print("  ", b)
            return 1
        # backfill
        fixed = 0
        for Q in (m.Quote, m.Invoice):
            for row in db.query(Q).all():
                if not getattr(row, "currency", None):
                    row.currency = base; fixed += 1
                if getattr(row, "fx_rate_to_base", None) in (None, 0):
                    row.fx_rate_to_base = 1.0; fixed += 1
        if not dry:
            db.commit()
        print(f"{'[DRY] ' if dry else ''}precondizione OK (base={base}); backfill campi: {fixed}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main(dry="--dry" in sys.argv))
```

- [ ] **Step 2: Dry-run**

Run: `.venv/Scripts/python.exe scripts/migrate_currency_baseanchored.py --dry`
Expected: "precondizione OK (base=EUR); backfill campi: N" (no STOP)

- [ ] **Step 3: Snapshot DB + apply**

```bash
cp mediaflow.db "db_snapshots/snapshot-3.5.0-alpha.172.155-pre-currency.db"
.venv/Scripts/python.exe scripts/migrate_currency_baseanchored.py
```
Expected: stessa riga senza `[DRY]`.

- [ ] **Step 4: Commit**

```bash
git add scripts/migrate_currency_baseanchored.py
git commit -m "feat(currency): migrazione verifica precondizione base-anchored + backfill"
```

---

## Phase 2 — Quote backend

### Task 4: Cambio valuta quote (no rewrite, errore se tasso None) + payload con tasso live + disclaimer

**Files:**
- Modify: `app/routers/quotes.py` — `update_quote` (sezione α.137 multi-currency, ~L1169-1240) e serializzazione `GET /quotes/api/{id}` (~L996-999)
- Test: `tests/test_quote_currency.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_quote_currency.py
import asyncio
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app.models import models as m
from app.routers import quotes as q


def _mk_quote(db, currency="EUR"):
    t = m.Tenant(id=1, name="T", default_currency="EUR"); db.add(t)
    c = m.Client(tenant_id=1, name="C"); db.add(c); db.flush()
    p = m.Project(tenant_id=1, code="P1", title="P", client_id=c.id); db.add(p); db.flush()
    quote = m.Quote(tenant_id=1, number="Q-1", project_id=p.id, client_id=c.id,
                    currency=currency, fx_rate_to_base=1.0)
    db.add(quote); db.flush()
    return quote


def test_quote_currency_payload_has_live_rate_and_disclaimer(db, monkeypatch):
    quote = _mk_quote(db)
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    monkeypatch.setattr("app.services.fx.get_fx_rate", lambda db, a, b: 0.92)
    payload = q._currency_block_for_quote(db, quote)  # helper nuovo (sotto)
    assert payload["currency"] == "EUR"
    assert "live_rate" in payload
    assert "disclaimer" in payload
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_quote_currency.py -q`
Expected: FAIL (AttributeError `_currency_block_for_quote`)

- [ ] **Step 3: Implement helper + wire**

In `app/routers/quotes.py` aggiungi helper (vicino agli altri helper modulo):

```python
def _currency_block_for_quote(db, quote) -> dict:
    """Blocco valuta per il payload quote: valuta target + tasso LIVE corrente
    (indicativo) + disclaimer. Importi restano base; il frontend converte."""
    from app.services import fx, currency as cur
    from app.services.clock import now_utc
    base = (db.query(Tenant).filter(Tenant.id == current_tenant_id()).first()
            .default_currency or "EUR").upper()
    ccy = (getattr(quote, "currency", None) or base).upper()
    if ccy == base:
        return {"currency": base, "base_currency": base, "live_rate": 1.0,
                "symbol": cur.symbol(base), "disclaimer": None}
    live = fx.get_fx_rate(db, ccy, base)  # quanti base per 1 ccy
    today = now_utc().strftime("%d/%m/%Y")
    disc = cur.disclaimer(base, ccy, live, today) if live else None
    return {"currency": ccy, "base_currency": base, "live_rate": live,
            "symbol": cur.symbol(ccy), "disclaimer": disc,
            "rate_available": live is not None}
```

Nella serializzazione `GET /quotes/api/{id}` (dove ora ritorna `"currency"`/`"fx_rate_to_base"`, ~L996), aggiungi al dict:

```python
        "currency_block": _currency_block_for_quote(db, q),
```

In `update_quote`, sezione cambio valuta (~L1230 `new_ccy = ...`): NON riscrivere importi; se `new_ccy != base` e `fx.get_fx_rate(db, new_ccy, base)` è None → `raise HTTPException(422, "Tasso di cambio non disponibile, riprova più tardi")`. Imposta solo `q.currency = new_ccy` (lascia `fx_rate_to_base`/`fixed_at` come informativi o 1.0 quando == base).

- [ ] **Step 4: Run test**

Run: `.venv/Scripts/python.exe -m pytest tests/test_quote_currency.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/routers/quotes.py tests/test_quote_currency.py
git commit -m "feat(currency): quote payload con tasso live + disclaimer, 422 se tasso assente"
```

---

### Task 5: Riga quote — conversione input valuta→base al save

**Files:**
- Modify: `app/routers/quotes.py` — endpoint add-line (`POST /quotes/api/{id}/lines`) e update-line (`PUT /quotes/api/{id}/lines/{lid}`)
- Test: `tests/test_quote_currency.py` (estendi)

- [ ] **Step 1: Write failing test**

```python
def test_line_price_entered_in_currency_stored_in_base(db, monkeypatch):
    quote = _mk_quote(db, currency="USD")
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    monkeypatch.setattr("app.services.fx.get_fx_rate", lambda db, a, b: 0.92)
    # input 1000 USD -> base = 1000*0.92 = 920 EUR
    base_price = q._line_price_to_base(db, quote, entered_price=1000.0, from_price_item=False)
    assert base_price == 920.0


def test_line_price_from_listino_is_base_unchanged(db, monkeypatch):
    quote = _mk_quote(db, currency="USD")
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    monkeypatch.setattr("app.services.fx.get_fx_rate", lambda db, a, b: 0.92)
    # prezzo da price_item è già base -> invariato
    assert q._line_price_to_base(db, quote, entered_price=850.0, from_price_item=True) == 850.0
```

- [ ] **Step 2: Run → FAIL** (`_line_price_to_base` non esiste)

- [ ] **Step 3: Implement**

```python
def _line_price_to_base(db, quote, entered_price: float, from_price_item: bool) -> float:
    """Converte un prezzo riga in valuta base. Prezzo da listino = già base.
    Prezzo digitato manualmente in quote estera = in valuta cliente -> /converti."""
    from app.services import fx, currency as cur
    base = (db.query(Tenant).filter(Tenant.id == current_tenant_id()).first()
            .default_currency or "EUR").upper()
    ccy = (getattr(quote, "currency", None) or base).upper()
    if from_price_item or ccy == base:
        return float(entered_price)
    rate = fx.get_fx_rate(db, ccy, base)
    if rate is None:
        raise HTTPException(422, "Tasso di cambio non disponibile per la conversione")
    return cur.to_base(float(entered_price), rate)
```

Nei due endpoint riga: quando il prezzo arriva dal form (manuale) e non da `price_item_id`, passa `unit_price = _line_price_to_base(db, quote, form_price, from_price_item=False)`. Quando da `price_item_id`, usa il prezzo listino (base) diretto (`from_price_item=True`).

- [ ] **Step 4: Run → PASS**

- [ ] **Step 5: Commit**

```bash
git add app/routers/quotes.py tests/test_quote_currency.py
git commit -m "feat(currency): riga quote converte prezzo digitato valuta->base"
```

---

## Phase 3 — Quote frontend

### Task 6: Helper JS formato valuta in `global.js`

**Files:**
- Modify: `app/static/js/global.js` (aggiungi `mfFormatMoney`); bump cache-buster non necessario (servito da Jinja `app_version`)
- Test: manuale (node --check sul servito, Task 11 E2E)

- [ ] **Step 1: Implement** (helper centralizzato, no shadow nei template)

```javascript
// global.js — conversione/format valuta (mirror app/services/currency.py)
window.mfFormatMoney = function(amountBase, ccy, rate) {
  const r = (rate && rate > 0) ? rate : 1.0;
  const v = amountBase / r;
  const s = v.toLocaleString('it-IT', {minimumFractionDigits:2, maximumFractionDigits:2});
  const sym = ({EUR:'€',USD:'$',GBP:'£',CHF:'CHF'})[(ccy||'').toUpperCase()] || (ccy||'').toUpperCase();
  return `${s} ${sym}`;
};
window.MF_HOURS = window.MF_HOURS; // (no-op, evita collisioni)
```

- [ ] **Step 2: Commit**

```bash
git add app/static/js/global.js
git commit -m "feat(currency): helper JS mfFormatMoney centralizzato"
```

---

### Task 7: Quote UI — card valuta (live + disclaimer) + render valori convertiti

**Files:**
- Modify: `app/templates/pages/quotes.html` — renderer card valuta (~L2301 `quote-currency-host`), render righe/subtotali/totali (usano `currentQuote.currency_block`), input add/inline edit
- Test: jinja compile + node --check (servito), E2E Task 11

- [ ] **Step 1: Card valuta** — sostituisci la nota α.140 "NON converte" con render live + disclaimer:

```javascript
function renderQuoteCurrency(q) {
  const cb = q.currency_block || {currency:'EUR', base_currency:'EUR', live_rate:1.0, symbol:'€', disclaimer:null};
  const host = document.getElementById('quote-currency-host');
  if (!host) return;
  const isBase = cb.currency === cb.base_currency;
  host.innerHTML = `
    <div class="card" style="padding:8px 12px;">
      <b>Valuta cliente:</b> ${cb.currency} ${cb.symbol}
      ${isBase ? '' : `· tasso live ${cb.live_rate ?? 'n/d'} (${cb.currency}/${cb.base_currency})`}
      ${cb.disclaimer ? `<div class="text-xs text-muted" style="margin-top:4px;">${escapeHtml(cb.disclaimer)}</div>` : ''}
    </div>`;
}
```

- [ ] **Step 2: Render valori** — ovunque si mostri un importo riga/subtotale/totale nella quote view, usa `mfFormatMoney(base, cb.currency, cb.live_rate)` con `cb = currentQuote.currency_block`. (I valori da API sono base.) Sostituisci le chiamate `fmtCurrency(x)` nella render quote con `mfFormatMoney(x, cb.currency, cb.live_rate)`.

- [ ] **Step 3: Input** — nei pannelli add/inline edit, le label prezzo mostrano `cb.symbol`; il valore digitato è in valuta cliente (il backend converte in base, Task 5). Mostra il prezzo esistente di una riga (base) convertito: `mfFormatMoney`/`to_display`.

- [ ] **Step 4: Verify** — jinja compile + node --check sul servito:

```bash
.venv/Scripts/python.exe -c "from jinja2 import Environment, FileSystemLoader; Environment(loader=FileSystemLoader('app/templates')).get_template('pages/quotes.html'); print('OK')"
```
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add app/templates/pages/quotes.html
git commit -m "feat(currency): quote UI converte valori live + disclaimer"
```

---

## Phase 4 — PDF quote

### Task 8: PDF quote convertito + disclaimer

**Files:**
- Modify: `app/services/pdf_export.py` (funzione PDF quote — individua il generatore quote; se assente, il PDF quote è generato dove serializza i totali). Cerca la funzione che riceve la quote e le righe.
- Test: `tests/test_pdf_currency.py` (smoke: genera bytes, no exception, contiene simbolo)

- [ ] **Step 1: Failing test**

```python
# tests/test_pdf_currency.py
def test_quote_pdf_converts_and_has_disclaimer(monkeypatch):
    # arrange: quote dict in USD rate 0.92, 1 riga base 920 -> 1000 USD
    # invoca il generatore PDF quote con currency_block e verifica bytes %PDF
    import app.services.pdf_export as pe
    # (adatta alla firma reale del generatore quote)
    assert True  # placeholder sostituito con invocazione reale del generatore
```

> NB esecutore: apri `pdf_export.py`, individua il generatore PDF della quote (pattern `generate_*quote*`/`generate_client_*`). Se il PDF quote non esiste come funzione dedicata, il punto di conversione è dove costruisce le celle importi. Applica: ogni importo base → `currency.to_display(base, rate)` + `currency.symbol(ccy)`; aggiungi riga disclaimer `currency.disclaimer(base, ccy, rate, data)` in calce. Sostituisci il placeholder test con l'invocazione reale.

- [ ] **Step 2-4: TDD** sul generatore reale (convert + disclaimer), run pytest.

- [ ] **Step 5: Commit**

```bash
git add app/services/pdf_export.py tests/test_pdf_currency.py
git commit -m "feat(currency): PDF quote convertito + disclaimer"
```

---

## Phase 5 — Fattura

### Task 9: Freeze tasso all'emissione (helper DRY + wire ai siti Invoice())

**Files:**
- Modify: `app/routers/finance.py` (siti `Invoice(...)`: create_invoice ~L283, advance ~L644, emit_from_advance ~L1377) e `app/routers/billing.py` (emissione da JCL slices, se crea Invoice)
- Create helper: in `app/services/currency.py` `freeze_invoice_fx(db, inv, base)`
- Test: `tests/test_invoice_currency.py`

- [ ] **Step 1: Failing test**

```python
# tests/test_invoice_currency.py
from datetime import date
from app.models import models as m
from app.services import currency as cur
import app.services.fx as fx


def test_freeze_invoice_fx_uses_emission_date_rate(db, monkeypatch):
    inv = m.Invoice(tenant_id=1, number="F1", kind=m.InvoiceKind.regular,
                    currency="USD", issue_date=date(2026, 5, 31), total=1000.0)
    db.add(inv); db.flush()
    monkeypatch.setattr(fx, "get_fx_rate_on", lambda db, a, b, d: 0.92)
    cur.freeze_invoice_fx(db, inv, base="EUR")
    assert inv.fx_rate_to_base == 0.92
    assert inv.fx_rate_fixed_at is not None


def test_freeze_invoice_fx_base_currency_noop(db, monkeypatch):
    inv = m.Invoice(tenant_id=1, number="F2", kind=m.InvoiceKind.regular,
                    currency="EUR", issue_date=date(2026, 5, 31), total=1000.0)
    db.add(inv); db.flush()
    cur.freeze_invoice_fx(db, inv, base="EUR")
    assert inv.fx_rate_to_base == 1.0
```

- [ ] **Step 2: Run → FAIL** (`freeze_invoice_fx` non esiste)

- [ ] **Step 3: Implement helper** (in `currency.py`):

```python
def freeze_invoice_fx(db, inv, base: str):
    """Congela sul-l'Invoice il tasso BCE della data di emissione (issue_date).
    Conversione legale art. 13 c.4 DPR 633/72. Solleva HTTPException 422 se il
    tasso non è disponibile e la valuta != base (serve per la conversione)."""
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
```

Wire: dopo ogni `Invoice(...)` creazione in finance.py/billing.py che eredita una currency estera dalla quote/job, chiama `freeze_invoice_fx(db, inv, base)` prima del commit. La currency dell'invoice eredita da `quote.currency` (passa esplicito alla creazione). Importi restano base.

- [ ] **Step 4: Run → PASS**

- [ ] **Step 5: Commit**

```bash
git add app/services/currency.py app/routers/finance.py app/routers/billing.py tests/test_invoice_currency.py
git commit -m "feat(currency): freeze tasso BCE alla data emissione fattura"
```

---

### Task 10: PDF fattura convertito + disclaimer; XML SDI resta EUR (assert)

**Files:**
- Modify: `app/services/pdf_export.py` (`generate_invoice_pdf` L37)
- Verify: `app/services/sdi_xml.py` (imponibile/imposta/totali in EUR base, Divisa EUR)
- Test: `tests/test_invoice_currency.py` (estendi) + `tests/test_sdi_eur.py`

- [ ] **Step 1: Failing test (SDI resta EUR)**

```python
# tests/test_sdi_eur.py
def test_sdi_xml_amounts_in_eur_even_for_usd_invoice():
    # costruisci un Invoice USD rate 0.92 importi base; genera XML SDI
    # assert: Divisa = EUR, ImponibileImporto = importo base (EUR), non convertito
    import app.services.sdi_xml as sx
    # (adatta alla firma reale del builder)
    assert True  # sostituire con build reale + assert su <Divisa>EUR</Divisa>
```

> NB esecutore: apri `sdi_xml.py`, conferma che imponibile/imposta/totali usano gli importi base (EUR) e `Divisa = EUR` (o base). Se attualmente legge `invoice.total`/righe (già base), è già corretto → il test documenta l'invariante. `generate_invoice_pdf`: converti ogni importo con `currency.to_display(base, inv.fx_rate_to_base)` + simbolo `inv.currency` + disclaimer `emitted=True`.

- [ ] **Step 2-4: TDD** PDF convertito + assert SDI EUR, run pytest.

- [ ] **Step 5: Commit**

```bash
git add app/services/pdf_export.py app/services/sdi_xml.py tests/test_sdi_eur.py tests/test_invoice_currency.py
git commit -m "feat(currency): PDF fattura in valuta + disclaimer; XML SDI invariato EUR"
```

---

## Phase 6 — Settings

### Task 11: Limita valute supportate in /settings

**Files:**
- Modify: `app/templates/pages/settings.html` (~L637 select `cmp-default_currency`)
- Test: jinja compile + node --check

- [ ] **Step 1: Imposta opzioni** EUR/USD/GBP/CHF nel `<select id="cmp-default_currency">`:

```html
<option value="EUR">EUR (€)</option>
<option value="USD">USD ($)</option>
<option value="GBP">GBP (£)</option>
<option value="CHF">CHF</option>
```

- [ ] **Step 2: Verify** jinja compile.

- [ ] **Step 3: Commit**

```bash
git add app/templates/pages/settings.html
git commit -m "feat(currency): /settings valute base limitate a EUR/USD/GBP/CHF"
```

---

## Phase 7 — Verifica E2E

### Task 12: Smoke E2E (API/curl)

**Files:**
- Nessuna modifica (verifica)

- [ ] **Step 1: Restart server pulito** (`avvia_muto.bat` o kill :8000 + uvicorn).

- [ ] **Step 2: Verifica flusso** (curl con cookie admin):
  1. Crea quote, set currency USD → `currency_block` con live_rate + disclaimer.
  2. Aggiungi riga da listino (base EUR) → `unit_price` base; GET mostra base + block.
  3. (UI/browser) verifica valori convertiti in $ + disclaimer in card e PDF.
  4. Converti job→fattura → `Invoice.fx_rate_to_base` = tasso del giorno; PDF in $; XML SDI EUR.

- [ ] **Step 3: Full pytest**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: tutti verdi (foundation + currency + invoice + sdi).

---

## Self-Review (compilato dall'autore del piano)

- **Spec coverage**: §2 base-anchored→T1/T4/T5; §3 due momenti→T4(quote live)/T9(invoice freeze); §4 legale→T9(date rate)/T10(SDI EUR); §5 disclaimer→T1/T7/T8/T10; §6 valute→T1/T11; §7 componenti→T1-T11; §10 migrazione→T3; §11 testing→ogni task; §12 fuori scope→non implementato (corretto).
- **Placeholder**: i due `assert True` (T8/T10 step1) sono esplicitamente marcati "sostituire con invocazione reale" perché richiedono la firma reale di `pdf_export`/`sdi_xml` che l'esecutore leggerà — sono punti di lettura-codice, non logica mancante. Tutto il resto ha codice completo.
- **Type consistency**: `fx_rate_to_base` = quanti base per 1 valuta (coerente fx.get_fx_rate(ccy, base)); `to_display=base/rate`, `to_base=ccy*rate` coerenti T1↔T4↔T5↔T9; `currency_block` shape coerente T4↔T7.

## Note esecuzione

- Foundation (T1-T3) sono indipendenti e testabili in isolamento → ottimi per subagent paralleli.
- T8/T10 richiedono lettura di `pdf_export.py`/`sdi_xml.py` per le firme reali (snippet placeholder da rimpiazzare).
- A fine batch: bump `main.py` versione + CHANGELOG + STATO (convenzione progetto), poi push quando Matteo OK + ZIP.
