# Design — Naming convention nei capitolati + default tenant

> Data: 2026-06-03
> Versione base: 3.5.0-alpha.172.180
> Stato: approvato (design dialogue con Matteo), pronto per writing-plans
> Scope: **B** — cattura + display della naming convention. La **verifica QC sull'asset è BACKLOG** (non in questo spec).

## Problema

I capitolati (DeliveryTemplate) non riportano in modo utile la **naming convention** del file (se e quando specificata). Serve:
1. catturarla in forma **strutturata** a ogni nuovo capitolato ingestato — sia a livello capitolato sia **per ogni voce/item**;
2. avere una **naming convention aziendale di default** (per tenant) valida per tutti gli asset prodotti (video + audio), basata sulle convenzioni industry (DCP ISDCF, IMF, Netflix);
3. mostrarla/editarla nella UI.

La **verifica del filename dell'asset** contro la convenzione risolta è rinviata a un blocco QC successivo (vedi §Backlog).

## Contesto codice (stato attuale, da indagine)

- `DeliveryTemplate.naming_convention: Mapped[Optional[dict]]` (JSON) — `app/models/models.py:692`. È uno degli 8 blocchi JSON del capitolato. Esiste ma **quasi mai popolato**.
- `JobDeliverable.file_naming: Mapped[Optional[str]]` (String 500) — `models.py:3344`. Nome atteso del deliverable, oggi inserito a mano.
- `DeliverableSpec.naming_convention: Mapped[Optional[str]]` (Text) — `models.py:3557`. Override per-deliverable, legacy/raro.
- `DeliveryItem` — `models.py:927`. **Nessun** campo naming oggi.
- `app/services/naming_helper.py` — **completo**: 8 preset industry (ISDCF DCP, Netflix Archival/IMF, DPP/AS-11, ProRes master, Screener, LTO archive, Custom), vocabolario token + `build_token_dict()` (191-314) + `resolve_template(template, tokens) -> (output, missing_tokens)` (317). **Non cablato in UI.**
- Parser: `app/services/deliverables_parser.py:175,197` — il prompt include `naming_convention: {pattern, examples, special_chars_allowed, max_length, ...}` ma in pratica resta vuoto.
- UI capitolati: `app/templates/pages/delivery_templates.html:117,264,363` — blocco naming mostrato (read-only nel preview) + serializzato in FormData al save.
- QC: `app/services/qc_specs_compare.py` confronta **solo** tech specs (no filename). **Nessuna** verifica naming.
- Tenant: modello `Tenant` esiste (multi-tenant soft, `CURRENT_TENANT=1`).

## Decisioni di design (dal dialogo)

- **D1** — Scope = **B**: cattura + display ora; verifica QC = backlog.
- **D2** — Schema **strutturato a token** (opzione A), riusando il vocabolario di `naming_helper`. Con `raw_note` come fallback testuale per il "se e quando specificata".
- **D3** — Gerarchia a **3 livelli** con override a cascata: **item > capitolato > default tenant**.
- **D4** — **Default tenant** (azienda) in `/settings`, valido per tutti gli asset video+audio, seedato da DCP/IMF/Netflix. Pattern "AI propone, utente dispone": valori iniziali proposti, l'utente conferma/edita.
- **D5** — Estrazione naming **di default a ogni ingest**, sia capitolato sia ogni item. Se il capitolato non specifica → si lascia vuoto (a runtime si applica il default tenant); non si scrive un valore fittizio.
- **D6** — Default tenant articolato per **disciplina** (almeno `video` e `audio`), ciascuna una convenzione strutturata.

## Architettura

### §1 Gerarchia e risoluzione

Funzione pura nuova in un servizio dedicato (`app/services/naming_resolver.py`):
```python
def resolve_naming_convention(db, *, delivery_item=None, delivery_template=None,
                              discipline="video", tenant_id=CURRENT_TENANT) -> dict:
    """Ritorna la naming convention applicabile, risolta per cascata:
       item.naming_convention  ->  template.naming_convention  ->  tenant.naming_conventions[discipline]
    Ritorna sempre un dict naming-convention (mai None): l'ultimo fallback è il default tenant.
    Include `_source` ('item'|'capitolato'|'tenant_default') per la UI.
    """
```
La `discipline` (video/audio) deriva dal reparto/tipo del deliverable (riusa la logica reparto già esposta in α.172.180: `price_item.department_id` → AUDIO vs DI-VIDEO), con default `video`.

### §2 Modello dati

- **Tenant**: nuovo campo `naming_conventions: Mapped[Optional[dict]]` (JSON, nullable). Shape: `{ "video": <conv>, "audio": <conv> }` dove `<conv>` è lo schema §3. Nullable → se assente, seed al boot/migrazione.
- **DeliveryTemplate.naming_convention** (JSON, già esistente): riempito con lo schema §3 (singola `<conv>` o `{video,audio}` se il capitolato distingue — vedi §3 nota).
- **DeliveryItem**: nuovo campo `naming_convention: Mapped[Optional[dict]]` (JSON, nullable) — override per voce, schema §3. NULL = eredita da capitolato/tenant.
- `DeliverableSpec.naming_convention` (Text): resta, marcato legacy nel commento (non usato dalla nuova catena).

Migrazione `scripts/migrate_naming_convention.py` + auto-migrate al boot (`_auto_migrate_columns`): ALTER `tenants.naming_conventions`, `delivery_items.naming_convention`; seed `tenants.naming_conventions` dai default industry se NULL.

### §3 Schema strutturato `<conv>` (single source)

```json
{
  "pattern": "{project_code}_{title}_{type}_{resolution}_{lang}_{date_iso}",
  "tokens": ["project_code","title","type","resolution","lang","date_iso"],
  "separator": "_",
  "allowed_chars": "A-Za-z0-9_-",
  "max_length": 120,
  "case": "upper",            // upper | lower | asis
  "extension": ".mov",
  "examples": ["GLO_MARE_PRORES_UHD_IT_20260603.mov"],
  "source": "tenant_default", // tenant_default | capitolato | item | manual
  "raw_note": "testo verbatim del capitolato quando non mappabile a token"
}
```
- I token ammessi sono quelli di `naming_helper.build_token_dict()` (vocabolario condiviso, single source). Validazione: `tokens` ⊆ vocabolario noto; token sconosciuti → ammessi ma segnalati in UI.
- `case`/`separator`/`allowed_chars`/`max_length`/`extension` sono regole strutturali (utili alla futura QC).
- `raw_note` è il fallback non-strutturato.
- Nota livello capitolato: un capitolato PUÒ avere naming diverso per video/audio. Schema flessibile: `DeliveryTemplate.naming_convention` può essere una singola `<conv>` o `{ "video": <conv>, "audio": <conv> }`. `resolve_naming_convention` gestisce entrambi (se dict-per-disciplina, seleziona per `discipline`; altrimenti usa la `<conv>` singola).

### §4 Estrazione (parser, default a ogni ingest)

- `deliverables_parser.py`: il prompt naming diventa **strutturato** (chiede `pattern`+`tokens`+`separator`+`case`+`extension`+`examples`+`raw_note`), mappando sui token noti di `naming_helper`. Estrazione **sempre tentata** per il capitolato e per ogni item.
- Post-parse: validazione shape JSON (token ⊆ vocabolario; `case` ∈ enum). Se il PDF non dà naming → campo lasciato vuoto (no valore fittizio); il `raw_note` cattura eventuale frase libera.
- Helper `normalize_naming_convention(raw: dict) -> dict` per ripulire/validare l'output AI prima del save.

### §5 UI Settings tenant (`/settings`)

Nuova sezione "Naming convention" (tab o card):
- Editor per disciplina **video** e **audio**: campo `pattern`, token picker (dal vocabolario `naming_helper`), `separator`/`case`/`allowed_chars`/`max_length`/`extension`, lista `examples`.
- **Anteprima live**: chiama `naming_helper.resolve_template(pattern, tokens_demo)` su token demo → mostra il filename risultante + token mancanti.
- Seed iniziale proposto (DCP/IMF/Netflix) editabile; salvataggio su `Tenant.naming_conventions`.
- Endpoint: `GET/PUT /settings/api/naming-conventions` (Form-based, tenant-scoped, gate RBAC come gli altri settings).

### §6 UI capitolato/item (`delivery_templates.html`)

- Blocco naming convention del capitolato: da read-only a **editabile** (stessi campi §5) + anteprima nome risolto.
- Per ogni **item**: naming override opzionale; se vuoto, badge "eredita da capitolato/tenant" + mostra la convenzione ereditata (via `resolve_naming_convention`).

### §7 Verifica QC asset — **BACKLOG (non in questo spec)**

Da fare in un blocco successivo: la QC confronta `Asset.filename` (asset legato al JobDeliverable) contro la naming risolta (`resolve_naming_convention`), usando le regole strutturali (pattern/regex derivata, `allowed_chars`, `max_length`, `case`, `extension`) + coerenza token. Richiede analisi/refactor del QC esistente (`qc_specs_compare.py`). Annotato in STATO + memoria.

## Test

- **Unit `resolve_naming_convention`**: cascata item>capitolato>tenant; dict-per-disciplina vs single conv; fallback tenant quando tutto vuoto; selezione discipline video/audio; `_source` corretto.
- **Unit `normalize_naming_convention`**: pulizia output AI (token ignoti, case invalido, max_length non-int) → shape valida.
- **Parser**: su un capitolato campione, estrae naming strutturato per capitolato + almeno un item; capitolato senza naming → vuoto (no fittizio) + eventuale raw_note.
- **Settings endpoint**: GET ritorna i default seedati; PUT salva e rilegge; tenant scope.
- **Migrazione**: idempotente (doppio run no-op); seed tenant default se NULL; boot su DB esistente non crasha.
- **Regressione**: capitolati esistenti senza naming → nessun errore, risoluzione cade sul default tenant.

## Non-goal (YAGNI)

- Verifica QC del filename asset (backlog esplicito §7).
- Rinominare/spostare fisicamente file asset.
- Migrare `DeliverableSpec.naming_convention` (Text legacy) — lasciato com'è.
- Generazione automatica del `JobDeliverable.file_naming` da template in massa (il wiring di `naming_helper` alla modale deliverable è fuori scope; eventuale follow-up).

## File toccati (stima)

- `app/models/models.py` — `Tenant.naming_conventions`, `DeliveryItem.naming_convention`
- `app/services/naming_resolver.py` — **nuovo** (`resolve_naming_convention`)
- `app/services/naming_helper.py` — eventuale export del vocabolario token + preset industry per il seed
- `app/services/deliverables_parser.py` — prompt naming strutturato + `normalize_naming_convention`
- `app/routers/settings.py` — endpoint naming-conventions + seed
- `app/routers/delivery_templates.py` — save naming strutturato capitolato/item
- `app/templates/pages/settings.html` — sezione naming convention tenant
- `app/templates/pages/delivery_templates.html` — naming editabile capitolato + override item
- `scripts/migrate_naming_convention.py` — **nuovo** + `main.py` auto-migrate
- `tests/` — nuovi file unit/integrazione
