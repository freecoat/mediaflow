# Design — Batch SAL + fix deliverables (13 giu 2026)

> Spec unico per 11 richieste di Matteo (13 giu 2026): 3 bug nel planning
> deliverables + 7 feature sulla pagina `/finance/sal` + 2 policy trasversali.
> Stato base: v3.5.0-alpha.172.218.

---

## 0. Policy trasversali (valgono per OGNI punto di questo batch)

### P1 — i18n sempre (PINNED)
Ogni nuova label, legenda, header colonna, opzione select, toast o testo UI
introdotto da questo batch **deve** essere tradotto in tutte e 5 le lingue del
menu lingue **nello stesso commit**:

- Aggiungere la chiave a `app/static/js/i18n.js` → `window.MF_I18N` con
  `{it, en, fr, de, es}`.
- Nel template usare `data-i18n="namespace.key"` (e `data-i18n-attr` per
  placeholder/title).
- In JS dinamico usare `mfT('namespace.key')`.
- Convenzione chiavi: dot-notation con prefisso semantico. Namespace di questo
  batch: `sal.*` (filtri, colonne, legenda, toggle) e `deliv.*` dove serve.
- Niente stringhe italiane hardcoded senza `data-i18n`.

Fallback runtime: `mfT()` → lingua corrente → `it` → key letterale.

### P2 — ordine colonne/menu deterministico (item 10)
Ogni dropdown/select e ogni colonna ordinabile introdotti da questo batch hanno
un ordine esplicito e deterministico:

- Liste anagrafiche (clienti, progetti) → **alfabetico** (case-insensitive, per
  nome/titolo).
- Categorie e reparti → per `sort_order` poi nome.
- Documentare la regola come convenzione standing in `CLAUDE.md`
  (sezione "Convenzioni di codice").

---

## 1. Area A — Bug deliverables (`/planning/?view=deliverables`)

File coinvolti:
- `app/templates/pages/planning.html` (editor tech-spec `dsm*`, audio preset).
- `app/services/delivery_item_validation.py` (regole codec/container, funzioni pure).
- `app/routers/delivery_items.py` (endpoint `POST /delivery-items/api/spec-schema`).
- `app/static/css/main.css` (`.form-select`).

### Bug 3 — select audio preset taglia il testo
**Causa:** `#dsm-audio-preset` creato con
`height:30px;font-size:12px;flex:1;min-width:200px;` dentro una riga
`display:flex;flex-wrap:wrap` troppo stretta. Il box select è più corto del
nome preset → il browser cliffa il testo dell'opzione selezionata (i `<select>`
nativi non fanno ellipsis sul valore visualizzato).

**Fix:** portare il select a larghezza piena su riga propria.
- Riga preset: `width:100%` (no competizione con altri elementi flex).
- Select: `flex:1 1 100%; width:100%; min-width:0;` (rimuovere `min-width:200px`
  che, combinato col wrap, lo lasciava stretto).
- Verifica visiva in browser (Playwright/manuale) con un preset dal nome lungo
  (es. preset audio Atmos 7.1.4).

Nessuna stringa nuova → P1 non si applica qui.

### Bug 1 — cambiando codec in ProRes il container non cambia
**Causa:** `dsmApplySpecSchema()` filtra solo le **opzioni codec** in base al
container (whitelist container→codec, `valid_video_codec_ids`). Non esiste la
direzione inversa: scegliendo un codec non viene proposto/impostato il container.

**Fix (generico):**
1. Nuova funzione **pura** in `delivery_item_validation.py`:
   ```python
   def preferred_container_for_codec(*, codec_family, containers) -> int | None:
       """Id del container preferito per la famiglia codec.
       PURA: nessun DB. `containers` = iterabile con .id/.name (o dict).
       - 'prores' in family → id del primo container QuickTime/.mov, altrimenti None.
       - altre family → None (nessuna preferenza forzata).
       """
   ```
   Derivata dalla regola R3 esistente (ProRes preferisce QuickTime).
   Estendibile in futuro con altre coppie codec→container.
2. Endpoint `spec-schema` ritorna in più `preferred_container_id`
   (calcolato quando arriva `video_codec_id`, risolvendo i container attivi).
3. JS in `planning.html`: in `dsmApplySpecSchema()`, dopo aver gestito le
   opzioni, se `data.preferred_container_id` è valorizzato e il container
   corrente è ProRes-incompatibile, impostare `#dsm-s-container` al valore
   preferito. L'utente può comunque cambiarlo (override).
   - Per evitare loop: l'auto-set scatta sul cambio di **codec**, non di
     container. Distinguere quale combo ha generato il `change` (flag o confronto
     valore precedente memorizzato).

### Bug 2 — item QuickTime/ProRes senza container
**Causa:** ProRes→QuickTime è solo WARNING (R3), mai applicato; gli item con
codec ProRes e container nullo restano senza container.

**Fix:**
1. Stesso resolver `preferred_container_for_codec`: quando il container è
   **vuoto** e il codec è ProRes, l'editor auto-compila QuickTime (riusa il
   meccanismo del Bug 1).
2. **Micro-migrazione opzionale** non distruttiva
   `scripts/migrate_prores_container.py`: per ogni `DeliveryItem`/spec con codec
   famiglia ProRes e `container_id` nullo, settare il container QuickTime.
   - Prerequisito verificato in fase implementativa: esiste un container
     "QuickTime"/".mov" attivo in tassonomia. Se non esiste, lo si crea nel
     seed/migrazione.
   - Idempotente, con conteggio righe toccate a log.

---

## 2. Area B — Pagina SAL (`/finance/sal`)

File coinvolti:
- `app/services/sal_metrics.py` (metriche, pure functions).
- `app/routers/finance.py` (route `/sal` + API `/finance/api/sal/*`).
- `app/templates/pages/sal.html` (UI tab Per progetto + Temporale).
- `app/static/js/i18n.js` (stringhe nuove).

### 2.1 Service — estensioni `sal_metrics.py`

**Metriche euro (speculari alle ore), da JobCostLine:**
- `quoted_amount(job) -> float` = Σ `JobCostLine.total_quoted`.
- `accrued_amount(job) -> float` = Σ `JobCostLine.total_accrued`.
- Estendere `job_metrics`, `project_metrics`, `by_department` con
  `quoted_eur`, `accrued_eur`, `pct_eur` (= accrued/quoted, 0 se quoted=0).
- L'allarme resta calcolato sulle ore (definizione invariata); il rosso riga
  (item 8) usa lo stesso `alarm=="red"`.

**Helper per-anno (per le colonne item 4), bucketed by Booking.start_datetime:**
- `worked_hours_in_year(job, year) -> float` = Σ billable hours dei booking
  non-cancelled con `execution_status==done` e `start_datetime` in `year`.
- `planned_hours_in_year(job, year) -> float` = Σ billable hours dei booking
  non-cancelled con `start_datetime` in `year` (qualsiasi execution_status).
- Aggregati a livello progetto in `project_metrics`/endpoint.

**Tasso blended (per €-anno quando il toggle è su budget):**
- `blended_rate(project) = quoted_eur / quoted_hours` (0 se quoted_hours=0).
- Colonna anno in modalità budget = `ore_anno × blended_rate`. È una **stima**
  (le ore booking non hanno un € maturato per-anno diretto) → dichiararlo nella
  UI con tooltip i18n.

### 2.2 Tab "Per progetto"

**Item 9 — toggle Ore ↔ Budget**
- Switch (segmented control) in testa al tab. Stato in `localStorage`
  (`sal_unit = hours|budget`), default `hours`.
- Modalità Ore: colonna "Monte ore" come oggi (Quotate/Pianif/Lavorate).
- Modalità Budget: "Monte €" (Quotato/Maturato in €), % = `pct_eur`.
- Il toggle vale **solo** in questo tab. Nel tab Temporale la cella è una % ratio
  (cumulato/quotato): identica in ore e budget → niente toggle lì.
- Stringhe i18n: `sal.unit.hours`, `sal.unit.budget`, `sal.col.monte_eur`,
  `sal.col.quoted_eur`, `sal.col.accrued_eur`.

**Item 4 — colonne Anno precedente / Anno successivo**
- Due colonne nuove: "Anno N-1" (lavorate) e "Anno N+1" (pianificate), dove N =
  anno corrente (server).
- Modalità Ore: ore lavorate (N-1) / ore pianificate (N+1).
- Modalità Budget: valore × `blended_rate` (stima, con tooltip).
- Header con anno esplicito (es. "2025" / "2027") + label i18n
  `sal.col.prev_year`, `sal.col.next_year`, tooltip
  `sal.col.prev_year.hint` ("ore lavorate"), `sal.col.next_year.hint`
  ("ore pianificate").

**Item 8 — riga rossa su sforamento**
- Se `project.alarm == "red"` → classe CSS `sal-row-overrun` sulla `<tr>`
  (sfondo rosso tenue, leggibile in dark + light mode, via variabili CSS).
- Niente nuova stringa (il badge allarme esistente resta).

**Item 12 — filtri**
- Aggiungere alla filter-bar (oltre a ricerca/stato/cliente già presenti):
  - **Reparto** (`department_id`): 4 reparti, ordinati per `sort_order`.
  - **Tipo lavorazione / Categoria** (`category_id`): 12 PriceCategory,
    ordinate per `sort_order`.
  - **Progetto** (`project_id`): elenco progetti, **alfabetico** per titolo.
- Semantica (dichiarata in UI con tooltip):
  - Tutti i filtri sono **row-filter**: includono un progetto se ha
    almeno una JobCostLine (o risorsa booking) nel reparto/categoria scelto,
    o se è il progetto selezionato.
  - **Reparto** inoltre **scala** la metrica di riga usando `by_department`
    (quotate/pianif/lavorate del solo reparto) — già attribuibile.
  - **Categoria** resta **solo row-filter**: le ore booking non sono
    attribuibili in modo affidabile a una PriceCategory (i booking hanno
    risorsa→reparto, non categoria). La % e le ore restano di progetto intero.
    Dichiararlo con tooltip i18n `sal.filter.category.hint`.
- Endpoint `/finance/api/sal/projects` accetta i nuovi parametri opzionali
  `department_id`, `category_id`, `project_id`.
- Reset filtri azzera tutto.
- Tutte le label/option dei select via i18n: `sal.filter.department`,
  `sal.filter.category`, `sal.filter.project`, `sal.filter.all` (opzione vuota).
- Ordine opzioni: P2 (alfabetico clienti/progetti, sort_order reparti/categorie).

### 2.3 Tab "Temporale" (matrix)

**Item 5 — passato = lavorate, futuro = pianificate (colori distinti)**
- Confine: **mese corrente** dal server (`date.today()`), passato esplicitamente
  a `matrix_metrics` (param `today` o calcolato dentro).
- Per ogni periodo, cella = cumulato a fine periodo:
  - periodo che termina **nel passato** (cutoff ≤ inizio mese corrente) →
    cumulato **lavorato** (done) — comportamento attuale.
  - periodo che termina **nel futuro** → cumulato **pianificato** (tutti i
    booking non-cancelled).
- **Regola unica (no ambiguità):** un periodo è "passato" se il suo **ultimo
  giorno < primo giorno del mese corrente** → basis `worked`. Altrimenti
  (mese corrente incluso e tutti i futuri) → basis `planned`. Il mese in corso
  è quindi sempre trattato come "pianificato" (mostra il cumulato pianificato a
  fine mese).
- `matrix_metrics` ritorna per cella sia il valore sia un flag `basis`
  (`worked` | `planned`) per il colore.
- Colori cella:
  - basis `worked` ≤100% → indigo pieno (scala alpha come oggi).
  - basis `planned` ≤100% → tinta distinta (es. ciano/teal tenue o pattern
    tratteggiato) per "previsione".
  - >100% (qualsiasi basis) → rosso (sforamento).

**Item 6 — legenda carina**
- Sostituire il testo piatto
  ("Cella = avanzamento cumulativo a fine periodo …") con un **box legenda**
  strutturato:
  - swatch colore + label per: "Lavorato (cumulato)", "Pianificato (cumulato)",
    "Sforamento >100%".
  - una riga sintetica di spiegazione formula (cumulato/quotato).
  - stile coerente con le card (border, radius, padding, font-size piccolo,
    `var(--border)`/`var(--text-muted)`), leggibile in dark+light.
- Stringhe i18n: `sal.legend.title`, `sal.legend.worked`,
  `sal.legend.planned`, `sal.legend.overrun`, `sal.legend.formula`.

---

## 3. Endpoint — riepilogo modifiche API

| Endpoint | Modifica |
|---|---|
| `GET /finance/api/sal/projects` | + param `department_id`, `category_id`, `project_id`; + campi risposta `quoted_eur`, `accrued_eur`, `pct_eur`, `prev_year`, `next_year` (h e €-blended) |
| `GET /finance/api/sal/matrix` | logica cella passato/futuro + flag `basis` per cella |
| `GET /finance/api/sal/projects/{id}/detail` | invariata (drill-down reparto resta; eventuale aggiunta € speculare opzionale) |
| `POST /delivery-items/api/spec-schema` | + campo risposta `preferred_container_id` |

Permessi invariati (`view_finance` sui SAL, gate esistenti sui delivery-items).

---

## 4. Test

**pytest (`tests/`):**
- `sal_metrics`: `quoted_amount`/`accrued_amount`/`pct_eur`; `worked_hours_in_year`/
  `planned_hours_in_year` (bucket per anno, esclusione cancelled, solo done per
  worked); `matrix_metrics` past/future basis + flag; `blended_rate` edge
  (quoted_hours=0).
- `delivery_item_validation.preferred_container_for_codec`: ProRes→QuickTime,
  altre family→None, container assente→None.
- Filtri endpoint: `department_id`/`category_id`/`project_id` row-filter corretti.

**Smoke browser E2E (Playwright):**
- `/finance/sal`: toggle ore/budget, colonne anno, riga rossa su progetto
  sforato, filtri reparto/categoria/progetto, legenda renderizzata, matrix con
  celle passato/futuro colorate diversamente.
- `/planning/?view=deliverables`: select audio preset non tagliato; cambio codec
  ProRes → container QuickTime auto-set; item ProRes senza container risolto.
- Cambio lingua (en) → tutte le stringhe nuove tradotte.

---

## 5. Default decisi (registrati)
- Toggle budget **solo** nel tab Per progetto (matrix % è ratio unit-agnostic).
- Filtro categoria = row-filter (non ri-scala ore); reparto ri-scala via
  `by_department`.
- Confine passato/futuro = primo giorno del mese corrente (server).
- Colonne anno N±1 in budget = ore × blended_rate (stima, con tooltip).
- Auto-set container scatta su cambio codec; override utente permesso.

## 6. Fuori scope (esplicito)
- Attribuzione affidabile ore↔categoria sui booking (non disponibile nel modello).
- Toggle budget nel tab Temporale.
- Backfill container non-ProRes.
