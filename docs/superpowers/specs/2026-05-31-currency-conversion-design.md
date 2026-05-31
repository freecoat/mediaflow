# Spec — Conversione valuta completa (quote + fattura)

**Data**: 2026-05-31
**Versione target**: v3.5.0-alpha.172.155+
**Richiesta**: Matteo — "conversione completa che converta tutta la quotazione in $/£,
visualmente per cliente e utente, tutti i valori economici inclusi i prezzi delle voci,
coi tassi attuali; riportata in egual misura nella fatturazione. Valuta base configurabile
nelle impostazioni."

---

## 1. Problema

Stato attuale (α.137/140): la quote ha già `currency` + `fx_rate_to_base` +
`fx_rate_fixed_at`, esiste il selettore valuta in UI, `fx.py` con tassi live
(frankfurter) + cache `FXRate`, e `Tenant.default_currency`. **MA** — commento
esplicito in `quotes.html` α.140 — *"il cambio valuta NON converte voci/totali/PDF"*:
cambia solo la sigla, i numeri restano identici. Quindi la conversione vera manca,
e non è propagata alla fattura.

## 2. Principio architetturale (base-anchored)

La **valuta base** del tenant (`Tenant.default_currency`, default EUR) è la verità.

- **Tutti gli importi in DB** (`QuoteLine.unit_price`, `Quote.subtotal_*`/`total_*`,
  righe e totali fattura, hardcosts) sono memorizzati **in valuta base**.
- Quote e Fattura portano: `currency` (valuta cliente), `fx_rate_to_base` (tasso
  congelato), `fx_rate_fixed_at` (timestamp snapshot).
- **Display** in valuta cliente = `importo_base / fx_rate_to_base`, arrotondato a 2
  decimali con Decimal HALF_UP (`app.services.money`).
- Semantica tasso: `fx_rate_to_base` = quanti base vale 1 unità di valuta cliente.
  Es. quote USD, base EUR, 1 USD = 0,92 EUR → `fx_rate_to_base = 0.92`. Per mostrare
  in USD un importo base: `usd = eur / 0.92`.

### Redefinizione vs α.137 — sicurezza

α.137 documentava "i subtotal_*/total_* sono memorizzati nella currency della quote".
Questa spec **ribalta** la convenzione (store in base). È sicuro perché la conversione
non ha mai funzionato (α.140 non convertiva) → in pratica **nessuna quote/fattura
estera reale con tasso ≠ 1.0 esiste**. La migrazione verifica questa precondizione e,
per le quote esistenti (tutte EUR, tasso 1.0), base == valuta → nessun dato cambia.

## 3. Decisioni confermate

| # | Decisione | Scelta |
|---|-----------|--------|
| D1 | Comportamento tasso dopo conversione | **Congela alla conversione** + bottone "aggiorna tasso" manuale. Una quote è un'offerta commerciale: il totale non deve fluttuare da solo. |
| D2 | Verità dei prezzi | **Base-anchored**: prezzi in valuta base; display convertito. |
| D3 | XML SDI/FatturaPA in valuta estera | **No**: l'XML legale resta sempre in **EUR base**. La valuta estera è solo su quote + PDF cliente + PDF fattura. (SDI è per clienti IT; cross-border estero = flusso esterometro/TD17-19 fuori scope.) |

## 4. Componenti & modifiche

### 4.1 Servizio conversione (nuovo helper centralizzato)
`app/services/currency.py` (nuovo) — single source per la conversione display:
- `to_display(amount_base: float, fx_rate_to_base: float) -> float` = `money_round(amount_base / rate)`.
- `to_base(amount_ccy: float, fx_rate_to_base: float) -> float` = `money_round(amount_ccy * rate)`.
- `symbol(ccy: str) -> str` (EUR→€, USD→$, GBP→£, CHF→CHF, fallback ISO).
- `SUPPORTED = ["EUR","USD","GBP","CHF", ...]` (qualsiasi ISO supportata da frankfurter; lista UI curata).
- `format_money(amount_base, ccy, rate) -> str` (formato IT "1.234,56 $").
- `fetch_and_freeze(db, ccy, base) -> (rate, ts)` wrapper su `fx.get_fx_rate` con errore esplicito se None.

### 4.2 Backend quote (`app/routers/quotes.py`)
- `create_quote` / `update_quote`: già impostano currency + snapshot. Aggiungere:
  cambio valuta → `fetch_and_freeze`; se rate None → **HTTP 422** "Tasso non disponibile,
  riprova" (mantiene valuta precedente, no €0 silenzioso). NESSUNA riscrittura `unit_price`
  (restano base).
- Endpoint nuovo `POST /quotes/api/{id}/refresh-fx`: refetch + ricongela (solo se quote
  editabile/non approvata). Display ricalcola lato client.
- Add/edit riga: se quote in valuta estera, il valore inviato dall'UI è in valuta →
  backend converte in base (`to_base`) prima di salvare `unit_price`. Riga da listino
  (price_item, base) → salvata base diretta.
- API `GET /quotes/api/{id}`: ritorna importi **base** + `currency` + `fx_rate_to_base` +
  `fx_rate_fixed_at` (frontend converte). Nessun doppio campo.

### 4.3 Frontend quote (`app/templates/pages/quotes.html`)
- Card valuta: valuta + tasso + data congelamento + **↻ Aggiorna tasso** (chiama refresh-fx).
- Rendering righe/subtotali/totali: `format_money(base, ccy, rate)` (helper JS mirror).
- Add-line / inline edit: input mostrati in valuta; al save convertiti in base.
- Helper JS in `global.js` (currency-aware) per evitare shadow (lezione regola helper centralizzati).

### 4.4 PDF quote (`app/services/pdf_export.py`)
- Converte tutti i valori in valuta cliente + riga nota: "Importi in {CCY}, cambio
  {rate} ({CCY}/{BASE}) del {data}." Simbolo valuta nelle celle.

### 4.5 Fattura (`app/routers/finance.py`, `billing.py`, `pdf_export`, `sdi`)
- Fattura creata da quote/job: eredita `currency` + `fx_rate_to_base` + `fx_rate_fixed_at`;
  importi salvati in base.
- PDF fattura cliente: convertito in valuta + nota tasso (come quote).
- **XML SDI** (`app/services/sdi_xml.py` / italian_tax): SEMPRE EUR base. Opzionale: nota
  testuale del tasso/valuta commerciale nel blocco `Causale`/note (non `Divisa`).
- Cashflow / incassi / acconti: tutti in base (verità interna).

### 4.6 Report aggregati (cost report, cashflow, anomalie)
- **Restano in valuta base**. Sono viste interne che mescolano progetti/valute diverse →
  base è l'unico denominatore coerente. Nessuna conversione qui. (Il margine costo-ricavo
  è corretto perché ricavo è memorizzato in base.)

### 4.7 Settings (`settings.py` / `settings.html`)
- Selettore valuta base esiste già (`default_currency`). Confermare lista valute supportate
  (D2 di `currency.SUPPORTED`). Nota che le quote possono essere in valuta diversa.

## 5. Flussi

### 5.1 Crea quote in USD (cliente estero)
1. Nuova quote, selezioni USD → backend `fetch_and_freeze(USD, EUR)` → `rate=0.92`, congela.
2. Aggiungi righe da listino (prezzi EUR base) → salvate base; UI mostra `base/0.92` in $.
3. Totali calcolati in base; UI/PDF mostrano $ convertiti + nota tasso.

### 5.2 Aggiorna tasso
- "↻ Aggiorna tasso" → refetch USD/EUR → nuovo rate, ricongela. Importi base invariati,
  display $ ricalcola. Lossless.

### 5.3 Quote → Fattura
- Job/fattura ereditano currency+rate+importi base. PDF fattura in $; XML SDI in EUR.

## 6. Regole / edge

- **Tasso non disponibile** (API frankfurter down / coppia non valida): cambio valuta →
  422 con messaggio; valuta resta quella precedente. Refresh → toast errore, tasso invariato.
- **Quote approvata / fatturata**: tasso **immutabile** (no refresh-fx → 409). Coerente con
  immutabilità post-emissione.
- **Arrotondamento**: ogni conversione → `money_round` (Decimal HALF_UP, 2dp). Display only;
  la verità base non si arrotonda in conversione.
- **Same currency** (quote in base): `fx_rate_to_base = 1.0`, nessuna conversione.

## 7. Migrazione

`scripts/migrate_currency_baseanchored.py` (idempotente, `--dry`):
1. Verifica precondizione: nessuna quote/fattura con `currency != default_currency` e
   `fx_rate_to_base != 1.0` (se esistono → report + stop, vanno gestite a mano).
2. Per quote/fatture esistenti (EUR, rate 1.0): nessuna modifica (base == currency).
3. Backfill `fx_rate_to_base = 1.0` / `currency = default_currency` dove null.

## 8. Testing

**Unit** (`tests/test_currency.py`):
- `to_display`/`to_base` round-trip + arrotondamento.
- `symbol`/`format_money` per EUR/USD/GBP.
- `fetch_and_freeze` con rate None → errore.
- Invariante: importi base invariati dopo cambio valuta + refresh.

**Integrazione**:
- create_quote USD → unit_price base, display USD coerente.
- refresh-fx idempotente (base invariato).
- Fattura eredita currency+rate; SDI XML resta EUR; PDF fattura in valuta.
- Quote approvata → refresh-fx 409.

**E2E (browser, pivot API se Playwright instabile)**:
- Quote USD, righe da listino EUR, verifica $ in UI + PDF, converti job→fattura,
  scarica XML SDI (EUR) + PDF (USD).

## 9. Fuori scope (debito futuro)

- XML SDI in valuta estera (Divisa) + flusso esterometro/TD17-19 cross-border.
- Conversione storica/retroattiva report multi-valuta (sempre base per ora).
- Hedging / tassi forward / multi-rate per riga.

## 10. File toccati (stima)

`app/services/currency.py` (nuovo), `app/services/fx.py` (riuso), `app/routers/quotes.py`,
`app/templates/pages/quotes.html`, `app/static/js/global.js`, `app/services/pdf_export.py`,
`app/routers/finance.py`, `app/routers/billing.py`, `app/services/sdi_xml.py` (verifica
EUR), `app/templates/pages/settings.html` (conferma), `scripts/migrate_currency_baseanchored.py`,
`tests/test_currency.py`.
