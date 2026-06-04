# Multiselect righe quote — Elimina / Copia / Sposta

> Spec di design. 4 giugno 2026. Versione target: v3.5.0-alpha.172.185.

## Obiettivo

Selezione multipla delle righe (`QuoteLine`) nell'editor quotazioni con azioni bulk:

- **Elimina** le righe selezionate.
- **Copia** le righe verso un'altra quotazione (le righe restano nell'origine).
- **Sposta** le righe verso un'altra quotazione (le righe vengono rimosse dall'origine).

La destinazione può essere una quotazione **esistente** (picker) o una **nuova** quotazione creata al volo. Ambito destinazione: **qualsiasi quote del tenant** (nessun vincolo progetto/cliente), purché editabile.

## Contesto esistente (riuso)

- `POST /quotes/api/{quote_id}/lines-batch-delete` — batch delete robusto: hard-block 409 su booking attivi (quote non-approved), propagazione su Consuntivo phantom (quote approved). **Riusato as-is per "Elimina".**
- `_copy_quote_lines(src_lines, dest_quote_id, track_parent)` — clona `QuoteLine` preservando `section_label`/`delivery_item_id`/`is_optional`/`category_override`/ecc. **Riusato per "Copia/Sposta".**
- `_next_position(quote)`, `_next_sort_order(quote)`, `_recalc_quote_totals(quote)` (in `app/services/reverse_quote.py`).
- `_next_quote_number_progressive(db)` — numero auto.
- `MFAutocomplete` (helper JS globale) per il picker searchable.
- Pattern guardia editabilità: `status == draft and not is_phantom` = editabile.

## Backend

### Endpoint principale (nuovo)

`POST /quotes/api/{quote_id}/lines-transfer` — dependency `RequireEditQuotes`.

Form params:

| campo | tipo | note |
|-------|------|------|
| `line_ids` | str (CSV interi) | righe da trasferire, devono appartenere a `quote_id` |
| `mode` | str | `copy` \| `move` |
| `target` | str | `existing` \| `new` |
| `target_quote_id` | int (opzionale) | richiesto se `target=existing` |

Logica (transazione singola):

1. Carica source quote (`quote_id`), scope tenant. 404 se assente.
2. Parse `line_ids` → lista int. 400 se vuota / non interi. Carica le `QuoteLine` filtrando `quote_id == source.id` (scarta id estranei → 400 se nessuna valida).
3. Risolvi destinazione:
   - **existing**: carica `target_quote_id`, scope tenant. 404 se assente. Deve essere **editabile** (`status == draft and not is_phantom`) → altrimenti **409** "Destinazione non editabile (solo bozze). Crea prima una nuova versione.". 400 se `target_quote_id == quote_id` (stessa quote).
   - **new**: crea `Quote` draft: `number=_next_quote_number_progressive(db)`, `version=1`, `project_id`/`client_id` ereditati dal source, `title=f"Copia da {source.number}"`, `status=draft`, `tenant_id=current_tenant_id()`, date default (oggi / +30gg come da convenzione create_quote). `db.flush()` per avere id.
4. **Copia**: `new_lines = _copy_quote_lines(selected_lines, target.id, track_parent=False)`. Per ciascuna riga sovrascrivi `position`/`sort_order` con valori progressivi su target (`_next_position`/`_next_sort_order`, incrementali). `db.add_all(new_lines)` + `db.flush()`. `_recalc_quote_totals(target)`.
5. **Se `mode == move`**:
   - Se source **non editabile** (approved/sent/phantom/rejected) → **422** "Spostamento non consentito da quote non editabile: usa Copia.". (L'immutabilità della quote approvata vieta la rimozione diretta; la propagazione phantom del batch-delete non è semantica di "sposta".)
   - Se source editabile → rimuovi le righe via helper condiviso `_remove_quote_lines(db, source, ids)` (vedi sotto): hard-block **409** se una riga ha booking attivi. Recalc totali source.
6. Se qualsiasi step fallisce → `db.rollback()` (copia inclusa). Altrimenti `db.commit()`.
7. Response: `{ok: true, mode, copied: N, target_quote_id, target_number, removed: M}` (`removed=0` su copy).

### Refactor DRY — `_remove_quote_lines`

Estrai dalla `batch_delete_quote_lines` il core di rimozione per il ramo **non-approved** (cascade JCL "pulite" + hard-block 409 su booking attivi) in una funzione modulo:

```
def _remove_quote_lines(db, quote, ids) -> int:
    # per ogni line: blocca 409 se booking attivi; elimina JCL collegate pulite;
    # elimina la line. Ritorna conteggio rimosse. NON gestisce propagazione phantom
    # (chiamata solo su quote editabili).
```

`batch_delete_quote_lines` continua a gestire il ramo approved (phantom) inline; il ramo non-approved delega a `_remove_quote_lines`. `lines-transfer` (move) usa **solo** `_remove_quote_lines` (source garantito editabile).

### Endpoint picker (nuovo)

`GET /quotes/api/transfer-targets?exclude={quote_id}` — dependency `RequireEditQuotes`.

Ritorna quote **editabili** del tenant (escludendo `exclude`):

```
[{ "id", "number", "title", "project_name", "client_name" }, ...]
```

Filtro: `tenant_id == current`, `status == draft`, `is_phantom == False`, `id != exclude`. Ordina per `number` desc. Nessun vincolo progetto/cliente ("qualsiasi quote").

## Frontend (`app/templates/pages/quotes.html`, JS inline)

### Selezione

- Aggiungi una cella checkbox a sinistra in ogni `tr.ql-row` (`data-line-id` già presente).
- Checkbox "select-all" nell'header di ogni sezione (seleziona/deseleziona le righe di quella sezione).
- Stato selezione in un `Set` JS (`_qlSelected`). Toggle aggiorna classe `.ql-row-selected` (evidenziazione).

### Barra bulk flottante

- Visibile solo con ≥1 selezionata. Mostra: `{n} selezionate · [Elimina] [Copia in…] [Sposta in…] [×]`.
- `[×]` = deseleziona tutto.
- **Elimina**: conferma → `POST lines-batch-delete` con `line_ids` CSV. Su successo: toast (con eventuale nota propagazione phantom dal response) + `reloadQuote()`.
- **Copia in… / Sposta in…**: aprono il modal trasferimento con `mode` preimpostato.
- **Sposta** disabilitato (tooltip "Solo da bozze") se la quote corrente non è editabile. **Copia** sempre abilitata.

### Modal "Trasferisci righe"

- Titolo dinamico ("Copia N righe" / "Sposta N righe").
- Radio: **Quote esistente** (default) / **Nuova quote**.
  - Esistente → campo picker searchable (MFAutocomplete) alimentato da `transfer-targets`; label `{number} — {title} · {client}`.
  - Nuova → testo informativo "Crea una nuova bozza (eredita progetto e cliente di origine)".
- Submit → `POST lines-transfer`. Disabilita il bottone durante la chiamata.
- Successo: toast con link alla destinazione (`{target_number}`); reload source (move rimuove le righe, copy le lascia); deseleziona.
- Errore 409/422 → toast con messaggio del server.

### Cache-buster

JS inline nel template → nessun bump `?v=` necessario.

## Test (pytest)

- `copy` → quote esistente editabile: righe presenti su entrambe, totali ricalcolati.
- `copy` → nuova quote: nuova bozza creata, eredita project/client, righe copiate.
- `move` da quote editabile → righe rimosse da source, presenti su target, totali aggiornati su entrambe.
- `move` da quote **approvata** → **422**, nessuna modifica.
- `move` con booking attivo su una riga → **409**, rollback totale (nessuna copia residua su target).
- Isolamento **tenant**: target di altro tenant → 404; righe di altro tenant ignorate.
- `target=existing` non editabile → **409**.
- `target_quote_id == quote_id` → **400**.
- Copia cross-project preserva `section_label` e `delivery_item_id`.
- `transfer-targets` ritorna solo draft non-phantom del tenant, esclude `exclude`.

## Non-goal (YAGNI)

- Niente scelta manuale di project/client per la "nuova quote" (eredita dal source).
- Niente trasferimento verso quote approvata (richiede new-version manuale a monte).
- Niente multidrag/riordino cross-sezione in questo giro.
- Nessuna modifica allo schema DB.

## Versioning

- Bump `main.py` → `3.5.0-alpha.172.185`.
- `CHANGELOG.md` + `docs/STATO.md` aggiornati a fine giro.
- Commit unico a feature completa + test verdi.
