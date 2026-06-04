# Duplica righe quote in-place — Implementation Plan

> Estensione di α.172.185 (multiselect). Target α.172.186.
> REQUIRED SUB-SKILL: subagent-driven-development.

**Goal:** Duplicare righe nella STESSA quote (per-riga ⧉ + bulk "Duplica"), con suffisso "(copia)", per crearne varianti da editare.

**Architecture:** Nuovo endpoint `POST /quotes/api/{id}/lines-duplicate` che riusa `_copy_quote_lines`. Per-riga inserisce sotto l'originale; bulk appende a fine categoria. UI: bottone ⧉ per riga + "Duplica" nella barra bulk. Editabilità gestita come "aggiungi voce".

**Tech:** FastAPI Form, SQLAlchemy, JS inline in quotes.html, pytest (chiamata diretta funzione + monkeypatch current_tenant_id).

---

### Task 1: Endpoint `lines-duplicate` (backend + test)

**Files:** Modify `app/routers/quotes.py`; Test `tests/test_quote_lines_duplicate.py` (nuovo).

Contratto: `POST /api/{quote_id}/lines-duplicate`, dep `RequireEditQuotes`.
Form: `line_ids` (CSV interi), `after` (bool, default False).
Logica (transazione singola, tenant-scope):
1. Carica source quote (tenant). 404 se assente.
2. Parse `line_ids` → 400 se vuoto/non-int. Carica le QuoteLine `quote_id==quote.id` (scarta estranei; 400 se nessuna).
3. Duplica via `_copy_quote_lines(selected, quote.id, track_parent=False)`. Per ogni copia: `description = (orig.description or "") + " (copia)"`.
4. **Posizionamento**:
   - Se `after and len(selected)==1`: copia subito sotto l'originale → `sort_order = orig.sort_order + 1`, `position = _next_position(quote)` (display; l'ordine reale è sort_order). NON serve reflow degli altri (gli altri distano +10).
   - Altrimenti (bulk): per ogni copia in ordine, `sort_order = _next_sort_order(quote)` progressivo, `position = _next_position(quote)`. Usa `quote.lines.append(nl)` per mantenere coerente la collection (lezione α.172.185: niente flush-per-riga su collection stale).
5. Ricalcola totali quote. Commit.
6. Response: `{ok: true, duplicated: N, quote_id}`.

Note implementative:
- `_copy_quote_lines` preserva `section_label`/`delivery_item_id`/`is_optional`/`category_override` → le copie restano nella stessa sezione/categoria. Bene.
- Per il caso `after`, dopo `dup.sort_order = orig.sort_order + 1`, fai comunque `quote.lines.append(dup)` per registrare nella collection; poi recalc.
- Verifica firma `_next_position(quote)`/`_next_sort_order(quote)` in `app/services/reverse_quote.py` (prendono il quote, leggono `quote.lines`).
- NON hard-bloccare su quote approvata a livello endpoint se `add_quote_line` non lo fa (verifica `add_quote_line` ~riga 1785 e mirror il suo comportamento). La gate UI (Task 2) usa `_ensureEditableQuoteOrVersion`.

Test (`tests/test_quote_lines_duplicate.py`), riusa pattern `_seed_quote` + `_call(asyncio.run)` da `tests/test_quote_lines_transfer.py` (copia l'helper o importalo):
- `test_duplicate_single_after`: 1 riga, `after=True` → quote ha +1 riga, la copia ha `description` con " (copia)", `sort_order` tra origine e successiva (origine+1).
- `test_duplicate_bulk_append`: 3 righe `after=False` → +3 righe, tutte con suffisso, `sort_order`/`position` distinti (no collisione).
- `test_duplicate_preserves_section_and_link`: origine con `section_label`+`delivery_item_id` → copia li preserva.
- `test_duplicate_tenant_scope`: line_ids di altra quote/tenant ignorati (400 se nessuna valida).
- `test_duplicate_recalcs_totals`: totale quote aumenta del valore delle copie (escluse opzionali).

TDD: test prima (FAIL: no attr `lines_duplicate`), poi impl, poi PASS. Commit:
`feat(quotes): lines-duplicate (duplica righe in-place con suffisso copia)`

### Task 2: UI — ⧉ per riga + "Duplica" bulk

**Files:** Modify `app/templates/pages/quotes.html`.

Simboli reali (confermati α.172.185): `api('METHOD', url, fd)` posizionale; `currentQuoteId`/`currentQuote`; `reloadQuote()`; `renderLineRow(l)` (cella azioni ha i bottoni 🏷/○/📁/✕); `escapeHtml/toast/openModal/closeModal` globali; `_ensureEditableQuoteOrVersion(label)` (~3081) → ritorna l'id su cui agire (gestisce nuova versione su approvata) o `currentQuoteId`; barra bulk `qlRenderBulkBar()`; `_qlSelected` Set; `qlClearSel()`.

A) Per-riga: in `renderLineRow`, nella cella azioni (dove ci sono i bottoni), aggiungi PRIMA di ✕:
```html
<button class="btn btn-ghost btn-sm" onclick="duplicateLine(${l.id})" title="Duplica questa voce sotto">⧉</button>
```
JS:
```javascript
async function duplicateLine(lineId) {
  const targetId = await _ensureEditableQuoteOrVersion('duplicare una voce');
  if (!targetId) return;  // utente ha annullato / non editabile
  const fd = new FormData();
  fd.append('line_ids', String(lineId));
  fd.append('after', 'true');
  try {
    const r = await api('POST', `/quotes/api/${targetId}/lines-duplicate`, fd);
    toast(`Voce duplicata`, 'success');
    if (typeof reloadQuote === 'function') reloadQuote();
  } catch (e) { toast(e.message || 'Errore duplicazione', 'error'); }
}
```
NOTA: verifica il valore di ritorno reale di `_ensureEditableQuoteOrVersion` (leggi la funzione ~3081): se ritorna l'id quote su cui agire usa quello come `targetId`; se ritorna un booleano, adatta (usa `currentQuoteId` dopo l'ok). Mirror esatto di come lo usano `addLine`/`saveLineField`.

B) Bulk: in `qlRenderBulkBar()` aggiungi un bottone "Duplica" tra "Tutte" ed "Elimina":
```html
<button class="btn btn-secondary btn-sm" onclick="qlBulkDuplicate()">Duplica</button>
```
JS:
```javascript
async function qlBulkDuplicate() {
  const ids = [..._qlSelected];
  if (!ids.length) return;
  const targetId = await _ensureEditableQuoteOrVersion('duplicare le voci');
  if (!targetId) return;
  const fd = new FormData();
  fd.append('line_ids', ids.join(','));
  fd.append('after', 'false');
  try {
    const r = await api('POST', `/quotes/api/${targetId}/lines-duplicate`, fd);
    toast(`Duplicate ${r.duplicated} voci`, 'success');
    qlClearSel();
    if (typeof reloadQuote === 'function') reloadQuote();
  } catch (e) { toast(e.message || 'Errore duplicazione', 'error'); }
}
```

Verifica: grep simboli presenti (`duplicateLine`, `qlBulkDuplicate`, `lines-duplicate`, `⧉`); no redef global helpers; jinja parse ok. Smoke browser (Task 3).
Commit: `feat(quotes-ui): duplica righe in-place (⧉ per riga + bulk Duplica)`

### Task 3: smoke browser + bump + docs + export + push

- Restart server :8000 (lezione: template Jinja non si ricarica su OneDrive senza restart).
- Smoke browser (login admin/admin123, apri bozza Gomorra v3 id 16): ⧉ su una riga → compare copia sotto con " (copia)"; seleziona 2 righe → "Duplica" → +2 con suffisso; console pulita. Pulisci (annulla/elimina le copie di test o lascia: è la sua bozza — chiedi).
- `pytest -q` tutto verde.
- Bump `app/main.py` → 3.5.0-alpha.172.186; CHANGELOG; STATO.
- Export ZIP in docs/ (genera via `build_export_zip(db, app_version=...)` one-off, poi rimuovi lo script); commit.
- Push (sessione remota → policy push ogni commit).

---

## Self-review
- Endpoint duplica in-place, suffisso, posizionamento after/append → Task 1 ✓
- UI per-riga + bulk con gate editabilità → Task 2 ✓
- smoke+bump+docs+export+push → Task 3 ✓
- Rischio: ritorno reale di `_ensureEditableQuoteOrVersion` (verificare in Task 2). Numerazione collisione bulk → usa `quote.lines.append` (lezione α.185).
