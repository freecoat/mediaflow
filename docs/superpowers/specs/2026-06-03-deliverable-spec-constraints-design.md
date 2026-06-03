# Design — Editor specs deliverable vincolato al tipo file

> Data: 2026-06-03
> Versione base: 3.5.0-alpha.172.182
> Stato: approvato (design dialogue con Matteo), pronto per writing-plans

## Problema (3 osservazioni di Matteo)

1. **Obs 1 — sub-profilo non propagato**: nel picker quote alcune voci (es. Fremantle "QuickTime / H.264 High Profile / HD 1080p") mostrano un sotto-menu che sceglie un DeliveryItem specifico (variante). La scelta si salva su `QuoteLine.delivery_item_id` (e ora, dopo il fix α.172.181, su `JobDeliverable.delivery_item_id`), ma il modal specs del planning **non auto-carica** le specs da quel link — mostra vuoto e chiede di ri-scegliere l'item a mano.
2. **Obs 2 — specs incongruenti**: si possono assegnare specs incoerenti col tipo file (es. specs H.264 su un item ProRes). L'editor non vincola al tipo file; "vale per tutte le sezioni dell'item, a meno che non venga modificato anche il tipo di file".
3. **Obs 3 — campi non pertinenti**: campi irrilevanti restano visibili (audio → colorspace/resolution; QuickTime semplice → package). Vanno **oscurati o bloccati**.

## Contesto codice (da indagine)

- **`DeliveryItem`** (`app/models/models.py:927`) ha tutti i campi tecnici: `container_id`(FK→DeliveryContainer), `package_id`(FK→DeliveryPackage), `video_codec_id`(FK→VideoCodec), `resolution_id`, `frame_rate_id`, `video_bit_depth`, `chroma_subsampling`, `scan_type`, `color_space`, `color_primaries`, `hdr_format`, `aspect_ratio`, `subtitle_format`, `subtitle_languages`(JSON), `audio_config_preset_id`, `audio_config_code`, `audio_tracks`(1:N AudioTrackSpec), `tc_start`, `timeline_segments`(JSON).
- **`DeliveryContainer.media_kind`** ∈ {`video`,`audio`,`image_seq`,`mixed`} — discriminante chiave per la pertinenza dei campi. `op_pattern` per varianti MXF.
- **`VideoCodec.family`** (ProRes/DNxHR/JPEG2000/H.264/HEVC/XAVC) + `profile_flavor` (stringa, es. "4444 XQ","Main 10").
- **`delivery_item_validation.py`** — esiste già con ~9 regole di coerenza (R1 DCP→MXF+J2K; R2 IMF→MXF/OP1a; R3 ProRes→QuickTime; R4 J2K→MXF; R5 image_seq→no audio; R6 HDR→≥10bit+Rec.2020/P3; R7 UHD@fps estremo; R8 audio container→no video_codec; R9 container obbligatorio). Severità ERROR/WARNING. **Oggi produce solo messaggi, non blocca né guida l'editor.**
- **Editor specs planning**: modal `#modal-deliverable-specs` (`planning.html:796`), `dsmOpen(did)`, `dsmCapItemChange()` (`:2361`), `dsmRenderStructured(v, tax)` (`:2400`) — renderizza **tutti** i campi come select, **senza** display condizionato. Save: `PUT /jobs/api/deliverables/{id}` con `delivery_item_id`.
- **JobDeliverable** (`models.py:3340`): `delivery_item_id`(FK), `spec_json`(legacy 8-block), `variant_id`. Specs strutturate derivano dal DeliveryItem linkato.
- **MANCANTE**: nessun descrittore di pertinenza campi per tipo; nessun enforcement delle regole nell'editor/save; nessun auto-load delle specs da `delivery_item_id`; nessun whitelist container↔codec esplicito.

## Decisioni di design (dal dialogo)

- **D1** — Scope **A**: tutti e 3 in un giro.
- **D2** — Logica **server data-driven, single source** (estende `delivery_item_validation.py`). Niente regole hardcoded in JS.
- **D3** — Severità: campi non pertinenti **nascosti/disabilitati**; regole **ERROR** **bloccano il save** (planning); regole **WARNING** mostrate ma non bloccano. Il **tipo file (container/codec/package) è il driver**: cambiandolo i campi si adattano.
- **D4** — Enforcement ERROR: **planning blocca** (422); **capitolato/AI/import solo warn** (l'AI propone, l'utente sistema).
- **D5** — **YAGNI**: NO whitelist container↔codec esplicito per filtrare proattivamente i dropdown (manca la tabella; le 9 regole + block-on-save coprono l'incongruenza). Eventuale filtraggio proattivo = backlog.

## Architettura

### §1 Auto-populate specs da `delivery_item_id` (Obs 1)
In `planning.html`, `dsmOpen(did)`: dopo aver caricato il deliverable, se `deliverable.delivery_item_id` è valorizzato e non c'è già una selezione, **pre-seleziona** quell'item nel picker capitolato del modal e chiama il render strutturato su di esso (riusa `dsmCapItemChange`/`dsmRenderStructured`). Se `delivery_item_id` è NULL, comportamento attuale (scelta manuale). Nessun cambiamento server per questo punto — il dato c'è già nel serializer (`department`/specs già esposti; verificare che `delivery_item_id` sia nel payload del deliverable, altrimenti aggiungerlo al serializer).

### §2 Descrittore field-relevance (server)
Nuova funzione pura in `delivery_item_validation.py`:
```python
def field_relevance(*, media_kind: str | None, has_package: bool,
                    video_codec_family: str | None, has_audio: bool) -> dict:
    """Ritorna i gruppi di campi pertinenti per il tipo file.
    groups: dict[str, "show"|"hide"] per: video, audio, subtitle, package,
    color, timecode. Derivato da media_kind + presenza package/codec/audio."""
```
Regole:
- `media_kind == "audio"` → `video=hide`, `color=hide`; `audio=show`.
- `media_kind == "image_seq"` → `audio=hide`; `video=show`, `color=show`.
- `media_kind in ("video","mixed")` → `video=show`, `color=show`; `audio = show if has_audio else hide`.
- `has_package` falso → `package=hide`.
- `subtitle`/`timecode` → `show` di default (sempre potenzialmente rilevanti).
Default difensivo per `media_kind` None/ignoto → tutto `show` (non nascondere nulla se non sappiamo).

### §3 Coerenza (riuso regole) + classificazione severità
Confermare/normalizzare in `delivery_item_validation.py` una `validate_delivery_item(item_like) -> list[Finding]` dove `Finding = {code, severity ('error'|'warning'|'info'), message, field?}`. `item_like` accetta sia un ORM DeliveryItem sia un dict di campi (per validare un payload prima del save). Le 9 regole esistenti vanno mappate alle severità di D3 (R1/R3/R4/R9 → error; R2/R5/R6/R7/R8 → warning/info — confermare le severità reali nel codice esistente e allinearle).

### §4 Endpoint spec-schema + enforcement al save
- `POST /jobs/api/deliverables/spec-schema` (read-only, tenant-scoped): Form input `container_id`/`package_id`/`video_codec_id`/`has_audio` (tutti opzionali). Risolve `media_kind` (da container), `video_codec_family` (da codec), poi ritorna `{ groups: <field_relevance>, findings: <validate_delivery_item on the partial combo> }`. Usato dall'editor al cambio dei driver.
- **Save enforcement**: in `PUT /jobs/api/deliverables/{id}` (e dove si linka un `delivery_item_id`/si scrivono specs), eseguire `validate_delivery_item` sul risultato; se ci sono finding `error` → **HTTP 422** con la lista (l'editor li mostra). Solo per il path planning (D4).

### §5 UI editor (`dsmRenderStructured` + `dsmOpen`/`dsmCapItemChange`)
- Al render e al cambio di container/codec/package, l'editor chiama `POST /spec-schema` e applica `groups`: i gruppi `hide` → sezioni/campi nascosti (o `disabled`).
- Findings mostrati inline: `error` in rosso (blocca/disabilita save o gestisce 422), `warning` in giallo (non blocca).
- Container/codec/package come **driver** in cima al form; al loro cambio si ricalcola tutto.
- Usa `textContent` per dati; `innerHTML` solo clear/statico. Riusa helper globali.

### §6 Coverage (capitolato/AI/import) — solo warn (D4)
Le stesse `field_relevance`/`validate_delivery_item` possono essere richiamate in fase di save capitolato/parse AI per **mostrare warning** (non bloccare). In questo spec: applicare il blocco SOLO nel save planning; per capitolato/AI limitarsi a esporre i findings se già comodo (altrimenti backlog). Non introdurre blocchi nuovi fuori planning.

## Test
- **unit `field_relevance`**: audio→video/color hide; image_seq→audio hide; video+has_audio→audio show; no package→package hide; media_kind None→tutto show.
- **unit `validate_delivery_item`**: severità corretta per R1/R3/R4/R9 (error) e R2/R5/R6/R8 (warning); accetta dict e ORM.
- **endpoint spec-schema**: combo (container audio) → groups con video hide; combo (ProRes + MXF) → finding error R3/relativo.
- **save enforcement**: PUT deliverable con combo ERROR → 422 + findings; combo valida → 200; combo WARNING → 200 + warning nel payload.
- **auto-populate (smoke)**: deliverable con `delivery_item_id` → `dsmOpen` pre-popola le specs (browser smoke dal controller).

## Non-goal (YAGNI)
- Whitelist container↔codec esplicito / filtraggio proattivo dei dropdown (D5 — backlog).
- Blocco ERROR su capitolato/AI/import (D4 — solo warn lì).
- Nuove regole di coerenza oltre alle 9 esistenti (riuso; eventuali nuove = follow-up).
- Modello codec→profile gerarchico strutturato (resta `profile_flavor` stringa).

## File toccati (stima)
- `app/services/delivery_item_validation.py` — `field_relevance` + normalizzazione `validate_delivery_item` (dict|ORM, severità).
- `app/routers/jobs.py` — endpoint `spec-schema` + enforcement 422 nel save deliverable; verifica `delivery_item_id` nel serializer.
- `app/templates/pages/planning.html` — `dsmOpen` auto-populate + `dsmRenderStructured` field-gating + findings inline.
- `tests/` — nuovi unit + endpoint.
