# Design — Whitelist container→codec proattivo (derivato)

> Data: 2026-06-03
> Versione base: 3.5.0-alpha.172.183
> Stato: approvato (design dialogue con Matteo), pronto per writing-plans

## Problema

Oggi l'editor specs deliverable mostra TUTTI i video codec a prescindere dal container scelto. La coerenza è solo post-hoc (validazione + enforcement 422 di α.172.183). Si vuole **prevenire** la scelta di combinazioni incoerenti a livello ERROR filtrando proattivamente il dropdown dei video codec in base al container selezionato (es. J2K compare solo se il container è MXF).

## Contesto (da indagine)

- `Container.media_kind` ∈ {video, audio, image_seq, mixed, subtitle, ...} (`models.py:783`), popolato bene. `VideoCodec.family` (ProRes/JPEG2000/H.264/...) (`models.py:799`), popolato bene. 23 container, 33 video codec seedati.
- **Nessuna** tabella/FK container↔codec. Le regole di coerenza in `delivery_item_validation.py` codificano già i vincoli: R4 `J2K_REQUIRES_MXF` (ERROR), R8 `AUDIO_CONTAINER_NO_VCODEC` (WARNING), R3 ProRes→QuickTime (WARNING).
- Endpoint taxonomy `GET /delivery-taxonomy/api` → liste complete, nessun filtro. Endpoint `POST /delivery-items/api/spec-schema` (α.172.183) ritorna `{groups, findings}`, già chiamato da `dsmApplySpecSchema` al cambio container/codec/package.
- Editor: planning `dsmRenderStructured`/`dsmApplySpecSchema` (`planning.html:2400+`), select `dsm-s-container`/`dsm-s-vcodec`. Capitolato item editor `openItemEditor` (`delivery_templates.html`) — non toccato da α.172.183.
- Audio codec = track-level (AudioTrackSpec), preset-driven, NON vincolato al container nel modello → fuori scope.

## Decisioni (dal dialogo)

- **D1** — Approccio **B (derivato)**: nessuna tabella whitelist. Funzione pura che deriva i codec validi dalle regole ERROR + `media_kind`. Single source con `validate_delivery_item`, niente drift.
- **D2** — Filtro solo per vincoli **ERROR** (J2K↔MXF) + `media_kind` (audio→nessun video codec). I WARNING (ProRes→QuickTime) NON filtrano (restano selezionabili, già avvisati post-hoc). Coerente con α.172.183 (errori si bloccano/prevengono; warning si avvisano).
- **D3** — Direzione **container → codec** (il container è il driver). No reverse (codec→container).
- **D4** — Scope: **editor planning** soltanto. L'editor item del capitolato resta protetto dall'enforcement 422 di α.172.183; filtro proattivo lì = follow-up.

## Architettura

### §1 Funzione server (delivery_item_validation.py)
```python
def valid_video_codec_ids(db, container_id, codecs=None):
    """Ritorna la lista di video_codec.id ammessi per il container, derivata
    dalle regole ERROR. `None` = nessun filtro (mostra tutti).

    - container_id assente / container non trovato → None (no filtro).
    - Container.media_kind == 'audio' → []  (nessun video codec, R8).
    - Container NON-MXF (name senza 'mxf') → esclude i codec family JPEG2000/J2K
      (R4: J2K richiede MXF). Gli altri ammessi.
    - Container MXF / video / mixed / image_seq → tutti i codec video.
    `codecs` opzionale = lista VideoCodec già caricata (evita query); altrimenti
    interroga i codec attivi.
    """
```
Pura rispetto alla logica (usa db.get per il container + lista codec). Deriva dalle stesse stringhe-famiglia di R4/R8 (single source con le regole).

### §2 Esposizione via `spec-schema` (no nuovo endpoint)
La risposta di `POST /delivery-items/api/spec-schema` aggiunge una chiave:
```json
{ "groups": {...}, "findings": [...], "valid_video_codec_ids": [1,2,5,...] }
```
- `valid_video_codec_ids = null` quando non c'è filtro (container assente/sconosciuto).
- Calcolata con `valid_video_codec_ids(db, container_id)`.

### §3 Editor planning (`dsmApplySpecSchema`)
`dsmApplySpecSchema` (già legato al change di container/vcodec/package) usa `valid_video_codec_ids` per **ricostruire le opzioni** del `<select id="dsm-s-vcodec">`:
- Mantiene una cache della taxonomy completa dei video codec (già disponibile: `tax.video_codecs` / `_dsmTax`).
- Ricostruisce le `<option>` includendo solo gli id presenti in `valid_video_codec_ids` (più l'opzione vuota "— audio-only —").
- Se `valid_video_codec_ids == null` → mostra tutti.
- Se il codec attualmente selezionato NON è nella lista valida → azzera la selezione (`select.value = ""`); i findings/relevance si aggiornano di conseguenza (già gestito).
- Ricostruzione opzioni via `createElement`/`textContent` (no innerHTML con dati).

### §4 Scope
Solo `dsmRenderStructured`/`dsmApplySpecSchema` (planning). Capitolato item editor non toccato (protetto da 422 α.172.183). Follow-up annotato.

## Test
- **unit `valid_video_codec_ids`**: container `media_kind=audio` → `[]`; container non-MXF (es. QuickTime) → lista senza family J2K; container MXF → lista CON J2K; `container_id=None` → `None`.
- **endpoint `spec-schema`**: con container MXF → `valid_video_codec_ids` contiene l'id J2K; con QuickTime → NON lo contiene; senza container → `null`.
- **browser smoke** (controller): nel modal specs, container MXF → J2K nel dropdown codec; cambia a QuickTime → J2K sparisce; se J2K era selezionato → selezione azzerata.

## Non-goal (YAGNI)
- Tabella `ContainerCodecWhitelist` esplicita / editabile per-tenant (D1 — scartata: drift + manutenzione 33×23).
- Filtro reverse codec→container (D3).
- Filtro su WARNING (ProRes→QuickTime resta selezionabile, D2).
- Filtro proattivo nell'editor item del capitolato (D4 — follow-up; resta protetto da 422).
- Filtro audio codec per container (audio = track-level/preset, fuori scope).

## File toccati (stima)
- `app/services/delivery_item_validation.py` — `valid_video_codec_ids`.
- `app/routers/delivery_items.py` — aggiunta `valid_video_codec_ids` alla risposta `spec-schema`.
- `app/templates/pages/planning.html` — `dsmApplySpecSchema` ricostruisce le opzioni del codec select.
- `tests/test_spec_constraints.py` — unit + endpoint (estende il file esistente).
