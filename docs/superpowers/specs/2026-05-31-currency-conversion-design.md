# Spec — Conversione valuta completa (quote + fattura)

**Data**: 2026-05-31
**Versione target**: v3.5.0-alpha.172.155+
**Richiesta**: Matteo — conversione completa della quotazione in $/£/CHF, visuale per
cliente e utente, tutti i valori inclusi i prezzi voce; propagata alla fatturazione.
Valuta base configurabile per tenant. La quotazione resta sempre in valuta base;
conversione applicata coi tassi in vigore **al momento dell'emissione fattura**.

---

## 1. Problema

Stato attuale (α.137/140): la quote ha già `currency` + `fx_rate_to_base` +
`fx_rate_fixed_at`, esiste un selettore valuta, `fx.py` con tassi live (frankfurter =
tassi BCE) + cache `FXRate`, e `Tenant.default_currency`. **MA** — commento esplicito
α.140 — *"il cambio valuta NON converte voci/totali/PDF"*: cambia solo la sigla.
Conversione vera assente e non propagata alla fattura.

## 2. Principio architetturale (base-anchored)

La **valuta base** del tenant (`Tenant.default_currency`, default EUR per azienda IT) è
la verità.

- **Tutti gli importi in DB** (`QuoteLine.unit_price`, `Quote.subtotal_*`/`total_*`,
  righe/totali fattura, hardcosts) sono memorizzati **in valuta base**.
- La quotazione è **sempre salvata internamente in valuta base**; la conversione in
  valuta cliente avviene **alla visualizzazione/stampa** (quote) e in modo **vincolante
  all'emissione fattura**.
- Display in valuta cliente = `importo_base / fx_rate_to_base`, arrotondato 2dp Decimal
  HALF_UP (`app.services.money`).
- Semantica tasso: `fx_rate_to_base` = quanti base vale 1 unità di valuta cliente
  (es. base EUR, 1 USD = 0,92 EUR → `0.92`; per mostrare in USD: `usd = eur / 0.92`).

### Redefinizione vs α.137 — sicurezza
α.137 diceva "totali memorizzati nella currency della quote". Questa spec **ribalta** la
convenzione (store in base). Sicuro: la conversione non ha mai funzionato (α.140) → nessuna
quote/fattura estera reale con tasso ≠ 1.0 esiste. Migrazione verifica la precondizione.

## 3. Modello dei due momenti di conversione

| Momento | Tasso usato | Natura | Congelato? |
|---------|-------------|--------|-----------|
| **Quote (vista/stampa/PDF)** | Tasso BCE **live** al momento della stampa | **Indicativo** | No — ricalcolato a ogni stampa |
| **Fattura (emissione)** | Tasso BCE alla **data di emissione fattura** | **Vincolante (legale)** | Sì — congelato sulla fattura |

- La quote NON congela il tasso: mostra sempre la conversione live + **disclaimer** che il
  cambio definitivo è quello all'emissione fattura. (Supera la decisione iniziale
  "congela sulla quote": Matteo ha chiarito che il vincolo legale è alla fatturazione.)
- La fattura, all'emissione, recupera il tasso BCE **della data di emissione** (fetch
  storico per-data) e lo **congela** (`Invoice.fx_rate_to_base` + `fx_rate_fixed_at`). È la
  conversione legalmente rilevante (art. 13 c.4 DPR 633/1972).

## 4. Verifica legale (richiesta Matteo) — ESITO: procedura conforme

- **Conversione**: art. 13 c.4 DPR 633/1972 — importi in valuta estera convertiti in EUR
  al cambio del **giorno di effettuazione dell'operazione** o, in mancanza, del **giorno di
  emissione della fattura**, su tassi BCE/Banca d'Italia. → applicare il tasso all'emissione
  fattura è corretto.
- **Fonte tasso**: frankfurter espone i tassi di riferimento **BCE** (anche storici
  per-data) → fonte conforme. Per valute non BCE userebbe fallback (per EUR/USD/GBP/CHF
  tutte coperte BCE).
- **FatturaPA/SDI**: campo `<Divisa>` obbligatorio; l'Agenzia delle Entrate **richiede che
  imponibile e imposta nel tracciato XML siano in EUR**. → l'XML SDI resta in EUR base
  (imponibile/imposta in EUR, Divisa = EUR). Nessuno scarto SDI. La valuta estera è solo
  su quote + PDF cliente (commerciale).
- **Quote/preventivo**: documento non fiscale → conversione indicativa + disclaimer è
  legittima.

**Conclusione**: modello (base EUR + conversione vincolante all'emissione col tasso BCE del
giorno + XML EUR) è legalmente OK. Eventuale fatturazione a cliente **estero** (non IT) segue
flusso cross-border (esterometro/TD17-19): fuori scope, documentato.

## 5. Disclaimer legale (testo)

Mostrato su quote (vista + PDF) e su PDF fattura quando `currency != base`:

> "La quotazione è espressa in {BASE}. Gli importi in {VALUTA} sono indicativi, convertiti
> al tasso BCE del {data} ({rate} {VALUTA}/{BASE}). La conversione definitiva applica il
> tasso BCE in vigore alla data di emissione della fattura (art. 13, c. 4, DPR 633/1972)."

Su PDF fattura emessa il disclaimer diventa: "Importi convertiti al tasso BCE del {data
emissione} ({rate}). Ai fini fiscali imponibile e imposta sono espressi in EUR."

## 6. Valute supportate

EUR, USD, GBP, CHF (maggiori valute mercati internazionali europei). Lista in
`currency.SUPPORTED`; estendibile, ma UI limitata a queste 4 per ora.

## 7. Componenti & modifiche

### 7.1 `app/services/currency.py` (nuovo) — single source conversione
- `to_display(amount_base, rate) -> float` = `money_round(amount_base / rate)`.
- `to_base(amount_ccy, rate) -> float` = `money_round(amount_ccy * rate)`.
- `symbol(ccy)` (EUR→€, USD→$, GBP→£, CHF→CHF).
- `SUPPORTED = ["EUR","USD","GBP","CHF"]`.
- `format_money(amount_base, ccy, rate) -> str` (formato IT "1.234,56 $").
- `disclaimer(base, ccy, rate, date, *, emitted=False) -> str` (testo §5).

### 7.2 `app/services/fx.py` (estendere)
- Aggiungere fetch **storico per-data**: `get_fx_rate_on(db, from, to, date)` →
  frankfurter `/{YYYY-MM-DD}?from=&to=`. Usato all'emissione fattura (tasso del giorno).
- `get_fx_rate` (latest) resta per il display live quote.
- Errore esplicito se tasso None (no €0/None silenzioso).

### 7.3 Quote (`app/routers/quotes.py` + `quotes.html`)
- `Quote.currency` = valuta target display (selettore). NESSUN congelamento tasso sulla
  quote (rate live). I campi `fx_rate_to_base`/`fx_rate_fixed_at` su Quote diventano
  informativi (ultimo tasso mostrato + data) o restano null.
- Add/edit riga in quote estera: UI mostra/accetta in valuta; al save backend `to_base`
  (tasso live) → salva `unit_price` base. Riga da listino (base) → diretta.
- `GET /quotes/api/{id}`: ritorna importi base + currency + tasso live corrente +
  disclaimer. Frontend converte per display.
- Card valuta: valuta + tasso live + data + disclaimer. Nessun bottone "congela".
- **Quote approvata**: non modificabile (già 409); valuta/tasso non cambiabili.

### 7.4 PDF quote (`pdf_export.py`)
- Converte tutti i valori in valuta cliente (tasso live alla stampa) + disclaimer §5.

### 7.5 Fattura (`finance.py`/`billing.py`/`pdf_export`/`sdi_xml`)
- **All'emissione**: `get_fx_rate_on(ccy, base, data_emissione)` → congela
  `Invoice.fx_rate_to_base` + `fx_rate_fixed_at`. Importi salvati in base.
- PDF fattura cliente: convertito col tasso congelato + disclaimer "emessa".
- **XML SDI** (`sdi_xml.py`): imponibile/imposta/totali in **EUR base**, `Divisa = EUR`.
  Opzionale nota tasso/valuta commerciale in `Causale`. (Conferma: già EUR-only.)
- Cashflow/incassi/acconti: base.

### 7.6 Report aggregati (cost report, cashflow, anomalie)
- **Restano in valuta base** (verità interna, mix progetti/valute → base unico denominatore;
  margine corretto perché ricavo è in base). Nessuna conversione.

### 7.7 Settings (`settings.py`/`settings.html`)
- Selettore valuta base esiste (`default_currency`); limitare opzioni a EUR/USD/GBP/CHF.
  Nota: le quote possono essere mostrate in valuta diversa; la conversione fattura usa il
  tasso BCE del giorno di emissione.

## 8. Flussi

1. **Quote USD**: selezioni USD → righe da listino EUR (salvate base) → UI/PDF mostrano $
   convertiti al tasso live + disclaimer. Nessun congelamento.
2. **Emissione fattura**: tasso BCE della data emissione → congelato su Invoice; PDF in $,
   XML SDI in EUR; disclaimer fattura.
3. **Cambio valuta quote**: cambia solo `currency`; importi base invariati; display ricalcola.

## 9. Regole / edge

- Tasso non disponibile (API down / coppia non valida): display quote → mostra valore base
  con avviso "tasso non disponibile" (no conversione errata). Emissione fattura → **blocca
  con 422** (serve tasso del giorno per la conversione legale).
- Same currency (quote/fattura in base): rate 1.0, nessuna conversione, nessun disclaimer.
- Arrotondamento: ogni conversione `money_round` (Decimal HALF_UP, 2dp). La verità base non
  si arrotonda.
- Quote approvata/fattura emessa: immutabili.

## 10. Migrazione

`scripts/migrate_currency_baseanchored.py` (idempotente, `--dry`):
1. Verifica: nessuna quote/fattura con `currency != default_currency` e `fx_rate_to_base != 1.0`
   (se esistono → report + stop).
2. Quote/fatture EUR esistenti (rate 1.0): nessuna modifica.
3. Backfill `fx_rate_to_base = 1.0` / `currency = default_currency` dove null.

## 11. Testing

**Unit** (`tests/test_currency.py`):
- `to_display`/`to_base` round-trip + arrotondamento; `symbol`/`format_money`; `disclaimer`.
- `get_fx_rate_on` per-data (mock); errore se None.
- Invariante: importi base invariati al cambio valuta quote.

**Integrazione**:
- create_quote USD → unit_price base, display USD coerente.
- Emissione fattura → tasso congelato = tasso della data emissione; XML SDI EUR; PDF in valuta.
- Quote approvata → non modificabile.

**E2E (browser/API)**: quote USD, righe listino EUR, $ in UI+PDF, converti job→fattura,
scarica XML SDI (EUR) + PDF (USD) + disclaimer.

## 12. Fuori scope (debito futuro)

- XML SDI in valuta estera (Divisa estera) + flusso esterometro/TD17-19 cross-border.
- Tenant base ≠ EUR con regole fiscali non-IT (la logica SDI assume base EUR / contesto IT).
- Hedging / tassi forward / multi-rate per riga.

## 13. File toccati (stima)

`app/services/currency.py` (nuovo), `app/services/fx.py` (+per-data), `app/routers/quotes.py`,
`app/templates/pages/quotes.html`, `app/static/js/global.js`, `app/services/pdf_export.py`,
`app/routers/finance.py`, `app/routers/billing.py`, `app/services/sdi_xml.py` (conferma EUR),
`app/templates/pages/settings.html`, `scripts/migrate_currency_baseanchored.py`,
`tests/test_currency.py`.

## 14. Fonti legali

- [Art. 13 DPR 633/1972 — base imponibile (Brocardi)](https://www.brocardi.it/testo-unico-iva/titolo-i/art13.html)
- [Conversione in euro importi valuta estera (Commercialista Telematico)](https://www.commercialistatelematico.com/articoli/2013/05/la-conversione-in-euro-degli-importi-in-valuta-estera.html)
- [Fatture per operazioni in valuta estera (Takobi)](https://www.takobi.online/blog/blog-di-takobi-1/fatture-per-operazioni-in-valuta-estera-come-comportarsi-10)
- [Agenzia delle Entrate — fatture transfrontaliere / compilazione FE](https://www.agenziaentrate.gov.it/portale/web/guest/schede/comunicazioni/fatture-e-corrispettivi/faq-fe/risposte-alle-domande-piu-frequenti-categoria/compilazione-della-fattura-elettronica)
- [Fatturazione elettronica in valuta estera (Stripe)](https://stripe.com/resources/more/e-invoices-in-foreign-currency-italy)
