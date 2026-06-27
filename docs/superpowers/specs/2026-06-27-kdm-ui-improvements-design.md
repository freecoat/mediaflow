# KDM — miglioramenti UI (design)

**Data**: 2026-06-27
**Versione target**: v3.5.0-alpha.172.238+
**Stato**: approvato (design), pronto per implementation plan

## Obiettivo
5 miglioramenti UI alla pagina KDM (`/kdm`): separare link e richieste, link editabili, select-all link, filtri link, multiselect Cinema/Server. Modifiche contenute in `app/templates/pages/kdm.html`, `app/static/js/kdm.js`, `app/routers/kdm.py` (+ i18n).

## Stato attuale (rilevato)
- Tab: Richieste · Archivio · Cinema/Server · CPL DCP.
- **Link**: pannello a toggle dentro la tab Richieste (`kdm-links-list`). Hanno già checkbox per-riga (`kdmLinkToggle`) + "Revoca selezionati" (`kdmBulkRevokeLinks`). Endpoint: `POST /api/links` (crea), `GET /api/links` (lista), `POST /api/links/{lid}/revoke`. **Manca**: PUT edit, select-all, filtri.
- **Richieste**: già multiselect + select-all + filtri + bulk-delete (pattern di riferimento: `kdmRowToggle`/`kdmToggleSelectAll`/`kdmUpdateBulkToolbar`/`kdmBulkDelete`, `kdmInitFilters`/`kdmFilteredRequests`).
- **Cinema/Server** (`kdmLoadFacilities`): solo add/edit/delete singolo. `delete_facility` = **soft-delete** (`is_active=False`), NON cascata server. Niente multiselect.
- Modello `KdmRequestLink`: `id, tenant_id, token, label, project_id?(FK projects), prefill_json(dict), expires_at?, revoked`. `CinemaFacility.servers` = `cascade="all, delete-orphan"` (solo su ORM delete vero, non sul soft-delete). `KdmRequest.target_facility_id` FK nullable.

## Le 5 modifiche

### 1. Tab "🔗 Link" dedicata
- Nuova tab tra Richieste e Archivio (`data-tab="links"`, pane `kdm-tab-links`, bottone `kdm-tab-btn-links`).
- **Spostare** nella nuova tab la barra genera-link e la lista link (oggi dentro Richieste). La tab Richieste resta con sola tabella richieste (rimuovere il toggle "Link attivi").
- `kdmSwitchTab('links')` → `kdmLoadLinks()`. La lista link si carica all'apertura tab (non più a toggle).
- i18n: `kdm.tab.links`.

### 2. Link editabili
- Nuovo `PUT /kdm/api/links/{lid}` (gate `manage_kdm`, tenant-scoped): aggiorna `label`, `project_id`, `expires_at` (da `duration_days` o data esplicita), `prefill_json` (title/cpl_uuid/notes). Link `revoked` → 409/400 "non modificabile". Ritorna il link aggiornato.
- UI: bottone "✎ Modifica" per riga link → modal che riusa i campi del form genera-link (nome, progetto, durata/scadenza, prefill). Salva via PUT, ricarica lista.
- i18n: `kdm.link.edit`, `kdm.link.edit_title`, `kdm.link.save`, `kdm.link.revoked_no_edit`.

### 3. Select-all link
- Checkbox header sulla lista link → `kdmLinkToggleSelectAll(cb)` (specchio di `kdmToggleSelectAll`): seleziona/deseleziona tutti i link **attualmente filtrati visibili**; aggiorna la toolbar "Revoca selezionati" (riusa `kdmBulkRevokeLinks`).
- i18n: `kdm.link.select_all`.

### 4. Filtri link (client-side)
- Barra filtri sopra la lista link (pattern `kdmFilteredRequests`): 
  - **Stato**: attivo / scaduto / revocato (da `revoked` + `is_expired`).
  - **Progetto**: select progetti.
  - **Cliente/Emittente**: derivato dal progetto del link (`project.client` / `project.broadcaster`). Link senza progetto → non matchano questi filtri.
  - **Ricerca testo**: su `label` + prefill `requested_title`.
  - **Finestra scadenza**: select (scade entro 7/30 gg / scaduti / senza scadenza).
- Backend: estendere la response di `GET /api/links` con `project_name`, `client_name`, `broadcaster`, `revoked`, `requested_title` (da prefill) per il filtro client-side.
- `kdmRenderLinks()` filtra `_kdmLinks` via `kdmFilteredLinks()` prima del render. Select-all opera sull'insieme filtrato.
- i18n: `kdm.link.filter.status/project/client/search/expiry` + opzioni.

### 5. Multiselect Cinema/Server
- Nella tab Cinema/Server: checkbox per-riga + checkbox select-all header + toolbar "Elimina selezionati" (specchio del pattern richieste: `kdmFacilityToggle`/`kdmFacilityToggleSelectAll`/`kdmFacilityBulkDelete`).
- Nuovo `POST /kdm/api/facilities/bulk-delete` (gate `manage_kdm`, tenant-scoped, Form `ids` CSV): per ogni facility soft-delete `is_active=False` **+ soft-delete dei suoi server** (`CinemaServer.is_active=False`). Idempotente; ignora id non trovati/altri tenant. Ritorna `{deleted, servers_deleted, requested}`.
- UI: dialog di conferma che avverte "N cinema e M server collegati saranno eliminati".
- i18n: `kdm.facility.select_all`, `kdm.facility.delete_selected`, `kdm.facility.confirm_bulk`.

## Convenzioni / non-funzionali
- Tutto tenant-scoped (`current_tenant_id()`), gate `manage_kdm` sui mutator.
- Soft-delete coerente con `delete_facility` esistente (no hard delete).
- i18n 5 lingue per ogni stringa nuova, `data-i18n` / `mfT`, stesso commit.
- No `JSON.stringify` in `onclick` (usa `data-*`/value). Reuse helper globali (`api`/`escapeHtml`/`toast`/`mfT`/`openModal`/`closeModal`).
- TDD sugli endpoint nuovi: `PUT /api/links/{id}` (aggiorna campi, blocca revocati, tenant scope) e `POST /api/facilities/bulk-delete` (soft-delete facility+server, idempotenza, tenant scope). Smoke browser su tutte le 5 modifiche.
- Cache-buster automatico via `app_version` per `kdm.js`/`kdm.html`.

## Fuori scope
- Hard-delete reale dei facility (resta soft-delete).
- Modifica del flusso form pubblico `/public/kdm/{token}`.
- Modifica della logica di matching CPL.

## Criteri di successo
1. Tab "Link" separata; Richieste mostra solo richieste.
2. "✎ Modifica" su un link aggiorna label/progetto/scadenza/prefill (revocati bloccati).
3. Select-all link spunta i link filtrati e pilota "Revoca selezionati".
4. I 5 filtri link restringono la lista; il cliente/emittente deriva dal progetto.
5. Cinema/Server: select-all + "Elimina selezionati" soft-elimina cinema + server con conferma.
6. 0 regressioni test; smoke browser verde (0 errori console, 0 chiavi i18n grezze).
