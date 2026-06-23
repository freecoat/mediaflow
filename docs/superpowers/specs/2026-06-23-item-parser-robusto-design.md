# Design — Item-list parser robusto + auto-extract

> Data: 2026-06-23 · Versione target: v3.5.0-alpha.172.229
> Follow-up di α.172.228 (parser 8-blocchi robusto). Stesso root-cause, secondo parser.

## Problema

Il capitolato Paramount (DeliveryTemplate id 18) ha **0 `delivery_items`**, mentre gli altri
capitolati ne hanno 17-35. La "lista item" vive nella tabella `delivery_items`, popolata da
un parser DIVERSO (`delivery_items_parser.parse_delivery_items_v2`, flow 2-pass) tramite
l'endpoint `/delivery-templates/api/{tid}/items/ai-extract` + `materialize_items`.

Tre cause:
1. **`ai-extract` legge solo da `docs/capitolati_esempio/`** (corpus legacy, per
   `source_document_name`). I capitolati caricati dalla UI non sono lì → 404 → 0 item.
   Gli altri capitolati hanno item perché i loro file ERANO nel corpus.
2. **Modello debole**: i caller usano `get_provider_for_user() or get_provider()` =
   provider attivo del copilot (deepseek-flash), non il più forte configurato.
3. **`parse_delivery_items_v2` tronca a 30.000 char** (`MAX_CHARS`) + PASS1 `max_tokens=4000`
   (basso per molti item) → su documenti lunghi estrae 0/pochi item.

## Decisioni (confermate con Matteo)

- Trigger: **auto dopo il save** (best-effort, non blocca il save).
- Architettura PASS1: **single-pass 150k + chunk fallback** (mirror di α.172.228).
- Modello: **`pick_parse_provider`** (più forte configurato).
- Sorgente: legge dal **file persistito** (`source_document_path`, `data/capitolato_uploads/`)
  se presente; **fallback** al corpus legacy (`source_document_name` in `docs/capitolati_esempio/`).

## Componenti

### A. `parse_delivery_items_v2` robusto (`delivery_items_parser.py`)
- `MAX_CHARS = 30000` → `MAX_CHARS_SINGLE = 150_000`, `MAX_CHARS_HARD = 600_000`.
- PASS1: se `len(text) <= 150k` → singola chiamata (come oggi ma senza troncare a 30k).
  Se `> 150k` → `split_into_chunks` (riusa quello di `deliverables_parser`), PASS1 per chunk,
  **merge item** con `_merge_items_by_name` (dedupe per `name` normalizzato, primo vince;
  i `terms`/`categories` uniti). Hard cap 600k.
- PASS1 `max_tokens` 4000 → 8000.
- PASS2: invariato come logica, ma il `text` di riferimento nel prompt viene **cap a 150k**
  (evita prompt fuori scala su doc enormi). PASS2 resta singola chiamata sugli item già estratti.
- Ritorna in più `parse_meta: {chunked, n_chunks, truncated, n_items}` (diagnostica).

### B. Risoluzione sorgente unificata (`capitolato_storage.py`)
- Nuovo `resolve_capitolato_source(template) -> tuple[bytes, str] | None`:
  - se `template.source_document_path` esiste su disco → ritorna `(bytes, filename)` da lì;
  - elif `template.source_document_name` esiste in `docs/capitolati_esempio/` → ritorna da lì;
  - else None.
  Riusa il guard path-traversal di `read_capitolato_text` per il ramo persistito.

### C. Endpoint `ai-extract` (`delivery_items.py`)
- Usa `resolve_capitolato_source(tpl)` invece di leggere solo dal corpus (404 se None).
- Usa `pick_parse_provider` (forte) invece di `get_provider_for_user() or get_provider()`.
- Resta idempotente (`materialize_items` skip per name+template).

### D. Auto-extract dopo `/api/save` (`delivery_templates.py`)
- Dopo il commit del template, se `source_document_path` è valorizzato, esegue **best-effort**:
  `resolve_capitolato_source` → `pick_parse_provider` → `parse_delivery_items_v2` →
  `materialize_items`. Errori loggati, **non** rilanciati (il save è già committato).
- La risposta `/api/save` include `items_extracted` (int) e `items_warning` (str|null).

## Error handling
- Auto-extract best-effort: qualunque eccezione → log + `items_warning`, save resta valido.
- `ai-extract` manuale: 404 se nessun sorgente risolvibile; 503 se nessun provider.
- Doc oltre 600k → PASS1 troncato + flag truncated.

## Testing
- `_merge_items_by_name`: due chunk con item sovrapposti → dedupe per name.
- `parse_delivery_items_v2`: fixture <150k = 1 chiamata PASS1; >150k = ≥2 PASS1 + 1 PASS2 (provider mock).
- `resolve_capitolato_source`: persistito presente → da lì; assente ma corpus presente → corpus; nessuno → None.
- `ai-extract`: usa pick_parse_provider (mock) + sorgente persistito → materializza item.
- `/api/save` con source_document_path (mock parser) → risposta con `items_extracted`; parser che lancia → save 200 + `items_warning`.

## Fuori scope
- Riscrivere PASS2 in chunked (opera sugli item già estratti, non sul full text).
- UI dedicata oltre il conteggio in risposta (banner item già coperto dal warning generico).
- Backfill automatico dei capitolati legacy (Matteo può ri-salvare/ri-estrarre on-demand).

## File toccati
- `app/services/delivery_items_parser.py` — chunk PASS1 + merge + limiti + parse_meta.
- `app/services/capitolato_storage.py` — `resolve_capitolato_source`.
- `app/routers/delivery_items.py` — `ai-extract` (source resolve + strong provider).
- `app/routers/delivery_templates.py` — auto-extract best-effort dopo `/api/save`.
- `tests/` — nuovi test.
