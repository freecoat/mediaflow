# Design — Parser capitolati robusto

> Data: 2026-06-23 · Versione target: v3.5.0-alpha.172.228
> Trigger: import "Paramount Scripted Episode Delivery 2023" → parse errato.

## Problema

L'import di un capitolato Paramount (DeliveryTemplate id 18) ha prodotto un parse
inaffidabile. Due cause che si sommano:

1. **Troncamento a 30.000 caratteri** (`deliverables_parser.parse_delivery_template`,
   `MAX_CHARS = 30000`). ~10-12 pagine. Un capitolato Paramount Scripted Episode è
   ~40-60 pagine → l'AI ha visto solo l'inizio e **allucinato** il resto.
2. **Modello debole**: provider attivo = `deepseek` / `deepseek-v4-flash` (piccolo,
   incline ad allucinare), pur avendo Claude Sonnet 4.6 configurato e verificato.

Prove di allucinazione nel parse id 18:
- `audio_specs.channel_layout.16ch` elenca `M&E L, M&E R` **due volte** (layout impossibile).
- `config "5.1 Surround": "16 channels"` (confonde mix 5.1 con layout consegna 16ch).
- Note di resa: "not fully extracted", "specific pattern not provided in extract", "sidecar (likely)".
- `head_format: null`, `naming_convention` vuoto, `archive_specs` incompleto (sezioni mai lette).

Il documento sorgente non era persistito (`source_document_path = None`) → impossibile
ri-analizzare senza ri-caricare.

## Obiettivo

Rendere il parse capitolati affidabile su documenti lunghi, scegliendo automaticamente
il modello migliore disponibile, persistendo il sorgente e dando una via di ri-analisi.

## Decisioni (confermate con Matteo)

- Architettura lettura: **single-pass + fallback chunk** (no map-reduce sempre).
- Modello: il parser **ignora il provider attivo** e usa sempre il **più forte configurato**.
  Se l'unico configurato è debole e il doc è grande → warning per switchare a Claude.
- Sorgente: **salva il file originale** (binario).
- Orphan file: **cleanup subito** (sweep a ogni parse, non job schedulato).

## Componenti

### A. Selezione modello — `pick_parse_provider(user_id, db)`
Nuovo helper in `app/services/ai_provider.py`.

Classifica i `UserAISettings` configurati per idoneità al parsing in 3 tier:

| Tier | Provider/modello |
|------|------------------|
| **strong** | Claude Opus/Sonnet · OpenAI gpt-4o/o1/o3 · Gemini *Pro |
| **medium** | Claude Haiku · Gemini *Flash · gpt-4o-mini |
| **weak** | deepseek-*-flash · Ollama locale · Perplexity Sonar |

Ranking via tabella `_PARSE_MODEL_TIER` (match per substring su provider+model, default
= weak per modelli sconosciuti). Ritorna:

```python
ParseProviderChoice(provider, provider_key, model, tier)  # tier in {strong,medium,weak}
```

Sceglie il tier più alto disponibile; a parità, ordine deterministico (claude > openai >
gemini). Se nessun provider configurato → ritorna None.

Interfaccia: input `(user_id, db)`; dipende da `UserAISettings` + factory provider esistente
(`get_provider_for_user` riusato per istanziare il provider scelto, ma forzando il modello
del tier scelto). Testabile isolando la sola funzione di ranking
`rank_parse_models(list_of_settings) -> ParseProviderChoice|None`.

### B. Fix troncamento — `parse_delivery_template`
Refactor della funzione esistente (stessa firma + nuovo ritorno metadata).

- `MAX_CHARS_SINGLE = 150_000` (single pass, sta in context Sonnet 200k).
- Se `len(text) <= MAX_CHARS_SINGLE`: un solo `extract_json` (come oggi, no troncamento
  per ~95% dei capitolati).
- Se `len(text) > MAX_CHARS_SINGLE`: **chunk fallback**
  - `split_into_chunks(text, size=120_000, overlap=5_000)` — preferisce tagliare su
    confini di sezione (regex su righe tipo `^\d+(\.\d+)*\s`, fallback taglio netto).
  - parse di ogni chunk per gli 8 blocchi.
  - `merge_template_blocks(parts)` — per ogni blocco: il valore non-null/non-vuoto vince;
    se più chunk popolano lo stesso scalare in conflitto → tiene il primo + annota in
    `parse_meta.warnings`; liste (`resolution`, `fps`, `deliverables`) concat + dedup.
- Ritorna `dict` con i blocchi + chiave `parse_meta`:
  ```python
  parse_meta = {
    "model": "claude-sonnet-4-6", "tier": "strong",
    "chunked": bool, "n_chunks": int, "truncated": False,
    "ai_confidence": 0.0..1.0, "warnings": [str, ...],
  }
  ```
  `truncated` resta `True` solo se anche il chunking eccede un cap di sicurezza
  (`MAX_CHARS_HARD = 600_000`, oltre → tronca + warning esplicito).

`split_into_chunks` e `merge_template_blocks` sono funzioni pure separate (unit-testabili
senza AI).

### C. Persistenza sorgente + cleanup orphan
- Dir: `data/capitolato_uploads/` (creata lazy). Aggiunta a `.gitignore`.
- `POST /api/parse`: dopo estrazione testo, salva i byte in
  `data/capitolato_uploads/{uuid4}{ext}`; include `source_document_path` (relativo) e
  `source_document_name` nel payload preview.
- `POST /api/save`: accetta `source_document_path: Optional[str] = Form(None)` e lo
  memorizza su `DeliveryTemplate.source_document_path` (colonna già esistente).
- **Cleanup orphan** — funzione `sweep_capitolato_uploads(db, max_age_h=24)` chiamata
  all'inizio di `/api/parse`: elimina i file in `data/capitolato_uploads/` con mtime
  > 24h e il cui path **non** è referenziato da alcun `DeliveryTemplate.source_document_path`
  (query `include_deleted=True` per non cancellare sorgenti di template cestinati).
  Best-effort, errori loggati non bloccanti.

### D. Warning UI + Ri-analisi
- `/api/parse` espone `parse_meta.warnings`. Trigger warning quando:
  - tier scelto = `weak` E `len(text) > 30_000`, oppure
  - `ai_confidence < 0.5`, oppure
  - `truncated == True`.
- UI preview (`delivery_templates.html`): banner giallo se `parse_meta.warnings` non vuoto,
  con testo i18n e link a Impostazioni → AI.
- Nuovo endpoint `POST /api/{template_id}/reparse` (RequireEditSettings):
  ri-estrae testo dal `source_document_path` salvato, ri-esegue `parse_delivery_template`
  col provider forte, ritorna preview per conferma-sovrascrittura (NON salva da solo —
  riusa il flusso save esistente). 404 se `source_document_path` mancante/file assente.
- Bottone **"Ri-analizza"** sulla riga/scheda template (solo se `source_document_path`
  presente). i18n in 5 lingue (`dt.reparse`, `dt.parse_warning.*`).

### E. Migrazione
Nessuna colonna nuova (`source_document_path` già esiste). Solo:
- `.gitignore` += `data/capitolato_uploads/`.
- Nessun ALTER TABLE.

## Data flow

```
Upload PDF/docx ──> /api/parse
   │ extract_text_from_file
   │ sweep_capitolato_uploads (cleanup orphan >24h)
   │ save bytes -> data/capitolato_uploads/{uuid}.ext
   │ pick_parse_provider(user,db) -> strong provider
   │ parse_delivery_template(text, provider)
   │     len<=150k -> single pass
   │     len >150k -> chunk + merge
   └─> preview JSON { ...8 blocchi, parse_meta, source_document_path }
            │ (UI mostra warning se parse_meta.warnings)
            v
   /api/save (form + source_document_path) -> DeliveryTemplate

Ri-analisi:  /api/{id}/reparse -> legge source_document_path -> parse forte -> preview
```

## Error handling
- `pick_parse_provider` None → 503 "AI non configurata" (come oggi).
- File grande oltre `MAX_CHARS_HARD` → parse comunque + warning "documento troncato".
- `reparse` senza sorgente → 404 con messaggio chiaro.
- Cleanup/save file errori → log warning, non bloccano il parse.

## Testing
- `rank_parse_models`: deepseek+claude → sceglie claude(strong); solo deepseek → weak.
- `split_into_chunks`: doc 300k → 3 chunk con overlap; taglio su confine sezione.
- `merge_template_blocks`: blocchi parziali da 2 chunk → unione corretta; conflitto scalare → warning.
- `parse_delivery_template`: provider mock, fixture <150k = 1 chiamata; fixture >150k = n chiamate.
- Warning trigger: weak+doc grande → warnings non vuoto.
- Endpoint `/api/parse`: ritorna `parse_meta` + `source_document_path`; file salvato su disco.
- `sweep_capitolato_uploads`: file vecchio non-referenziato eliminato; referenziato preservato.
- Endpoint `/api/{id}/reparse`: senza sorgente → 404; con sorgente → preview.

## Fuori scope
- Map-reduce sempre-chunk (YAGNI: single-pass copre ~95%).
- Storage TPN/cifratura del file sorgente (capitolato = doc tecnico, non contenuto).
- UI selettore modello dedicato (il parser sceglie automaticamente il forte).
- Header `topbar_title` i18n (pre-esistente app-wide).

## File toccati
- `app/services/ai_provider.py` — `pick_parse_provider` / `rank_parse_models`.
- `app/services/deliverables_parser.py` — chunk + merge + parse_meta.
- `app/routers/delivery_templates.py` — `/api/parse` (save+sweep+meta), `/api/save`
  (source_document_path), nuovo `/api/{id}/reparse`.
- `app/templates/pages/delivery_templates.html` — banner warning + bottone Ri-analizza.
- `app/static/js/i18n.js` — chiavi `dt.reparse`, `dt.parse_warning.*` (5 lingue).
- `.gitignore` — `data/capitolato_uploads/`.
- `tests/` — nuovi test unit + endpoint.
