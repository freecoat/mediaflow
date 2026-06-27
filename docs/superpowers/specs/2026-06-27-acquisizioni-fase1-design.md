# Acquisizioni — Fase 1: Pipeline + Attività (design)

**Data**: 2026-06-27
**Versione target**: v3.5.0-alpha.172.236+
**Stato**: approvato (design), pronto per implementation plan

## Contesto e obiettivo

I commerciali devono tracciare le **trattative di acquisizione** (lead → commessa) in modo chiaro, condiviso e a basso sforzo, collegato a clienti, progetti e quotazioni, con visibilità su stato, potenziale economico e prossimi impegni — il tutto coadiuvato dal copilot.

Questa è la **Fase 1** di un percorso a 3 fasi (decomposizione concordata):

- **Fase 1 (questo doc)** — Pipeline trattative + log attività/comunicazioni + contatti multipli + mini-agenda + fix stato progetto. Capability AI `propose_*` come gancio backend.
- **Fase 2** — Incolla-email → AI estrae info rilevanti + incrocio web (Tavily/`client_enrichment.py`) → propone attività/contatti/aggiornamenti. UI dedicata.
- **Fase 3** — Agenda piena + sync Google Calendar (OAuth) / ICS.

### Infrastruttura esistente riusata
- `Project.status` (`prospect/quoting/active/completed/archived`) — sincronizzata dalla pipeline.
- `Quote.win_probability_pct` + `expected_close_date` + `quote_forecast.py` (`DEFAULT_WIN_PROBABILITY`) — pattern di pesatura, riusato concettualmente.
- `Client` (referente singolo + arricchimento AI) + `ClientWork` (filmografia) + `client_enrichment.py`.
- RBAC granulare (preset `admin/manager/producer/accounting/operator/viewer`), copilot capability registry `propose_*`.
- `projects.py` PUT accetta già `status` (il "non posso modificare lo stato" è un gap UI, non backend).

## Decisioni di design (dal brainstorming)

| Tema | Decisione |
|------|-----------|
| Entità trattativa | **Entità nuova `Acquisition`** (un lead può esistere prima di un Progetto e convertirsi). |
| Lead senza cliente | `prospect_name` testo libero; conversione crea/collega il `Client` reale e migra i contatti. |
| Stadi pipeline | `lead → qualified → quoting → negotiation → won → lost` (6). |
| Potenziale | **Pesato = `estimated_value` × `win_probability%`**. Probabilità default da stadio (lead 10, qualif 30, quota 50, negoz 70, vinta 100, persa 0), override manuale. |
| Per reparto | Tag reparti **multi** sulla trattativa (M:N). € resta a livello trattativa (no allocazione). Viste filtrano/raggruppano per reparto. |
| Layout pagina | **Ibrido Kanban ⇄ Tabella** (toggle, stesso dato; pattern già usato in SAL/planning). |
| Permessi | Nuovi granulari `view_acquisitions` / `manage_acquisitions`, **default-assegnati ai preset `manager`, `producer`, `accounting`** (= project owner + accounting manager). Assegnabili a qualunque ruolo via UI permessi. |
| Agenda F1 | Solo **mini-agenda** = lista prossimi impegni da `next_action_date`. Calendario vero = Fase 3. |

## Modello dati

### `Acquisition` (trattativa)
```
id, tenant_id
title                  str            # es. "Nuovo film Sorrentino"
client_id              FK clients?    # nullable → prospect non ancora cliente
prospect_name          str?           # usato se client_id NULL
project_id             FK projects?   # valorizzato quando si concretizza
stage                  Enum AcquisitionStage  # lead/qualified/quoting/negotiation/won/lost
estimated_value        Numeric(12,2)  # € stimato (default 0)
win_probability_pct    Float?         # override; se NULL usa default-da-stadio
expected_close_date    Date?
owner_user_id          FK users       # il commerciale responsabile
next_action            str?           # testo prossima azione
next_action_date       Date?          # alimenta la mini-agenda
source                 str?           # referral/inbound/evento/...
lost_reason            str?           # se stage=lost
is_active              bool=True      # soft-delete
created_by             FK users
created_at, updated_at
```
- Relazioni: `client`, `project`, `owner`, `departments` (M:N), `activities` (1:N), `contacts` (via client).
- `weighted_value` (proprietà calcolata) = `estimated_value × effective_probability/100`.
- `effective_probability` = `win_probability_pct` se valorizzato, altrimenti `DEFAULT_ACQ_PROBABILITY[stage]`.

### `AcquisitionStage` (Enum)
`lead, qualified, quoting, negotiation, won, lost`. Mapper stadio → `Project.status` alla conversione (`won` → `active`; `lead/qualified` → `prospect`; `quoting/negotiation` → `quoting`).

### `acquisition_departments` (M:N)
`acquisition_id` FK · `department_id` FK · UNIQUE(acquisition_id, department_id). Tag reparti coinvolti, per filtri/raggruppamento.

### `Contact` (contatti multipli per cliente)
```
id, tenant_id
client_id              FK clients
name                   str
role                   str?
email                  str?
phone                  str?
notes                  Text?
is_primary             bool=False     # il primario è mirror su Client.contact_*
ai_extracted           bool=False     # proposto da AI (F2) e confermato
is_active              bool=True
created_at, updated_at
```
- Il referente principale resta denormalizzato su `Client.contact_*` (compat intestazione fattura). Settare `is_primary=True` sincronizza i campi `Client.contact_*`.

### `Activity` (log comunicazioni/attività)
```
id, tenant_id
acquisition_id         FK?            # link flessibile
client_id              FK?
project_id             FK?
contact_id             FK?
type                   Enum ActivityType  # email/call/meeting/note/task
direction              Enum?              # inbound/outbound (per email/call)
occurred_at            DateTime
subject                str
body                   Text?
next_action_date       Date?          # alimenta la mini-agenda
ai_extracted           bool=False
ai_source              Text?          # URL/raw sorgente (F2)
created_by             FK users
created_at
```
- Almeno uno tra `acquisition_id`/`client_id`/`project_id` valorizzato.
- Ordinamento timeline: `occurred_at` DESC.

## Servizio: `acquisition_service.py`
- `effective_probability(acq) -> float`
- `weighted_value(acq) -> Decimal`
- `pipeline_summary(tenant, filters) -> {by_stage, by_department, totals}` — KPI header (Σ pesato totale + per-reparto, n° aperte), no N+1.
- `upcoming_actions(tenant, user?, days) -> list` — mini-agenda da `Acquisition.next_action_date` + `Activity.next_action_date`.
- `convert_to_project(acq) -> Project` — crea/collega `Project` (status da stadio), migra `prospect_name`→`Client` se serve, idempotente.
- `apply_stage_change(acq, new_stage)` — aggiorna stadio + probabilità default + audit-log + (se collegato) sync `Project.status`.

Decimal per i valori monetari (coerente con `invoice_totals`).

## Endpoint (router `acquisitions.py`, form-based, tenant-scoped)
```
GET    /acquisitions                         # pagina (Jinja)
GET    /acquisitions/api/list                # filtri: stage, department_id, owner_id, client_id, state(open/won/lost)
GET    /acquisitions/api/summary             # KPI header (pipeline_summary)
GET    /acquisitions/api/agenda              # upcoming_actions
POST   /acquisitions/api                     # crea (manage_acquisitions)
GET    /acquisitions/api/{id}                # dettaglio (+ activities, quotes collegate, contatti)
PUT    /acquisitions/api/{id}                # update campi
POST   /acquisitions/api/{id}/stage          # cambio stadio (drag/dropdown)
POST   /acquisitions/api/{id}/convert        # converti in Progetto
DELETE /acquisitions/api/{id}                # soft-delete

GET    /acquisitions/api/{id}/activities     # timeline
POST   /acquisitions/api/{id}/activities     # quick-add attività
PUT    /activities/api/{id}                  # edit
DELETE /activities/api/{id}                  # soft-delete

GET    /clients/api/{id}/contacts            # lista contatti cliente
POST   /clients/api/{id}/contacts            # crea
PUT    /contacts/api/{id}                    # edit (is_primary → sync Client.contact_*)
DELETE /contacts/api/{id}                    # soft-delete
```
Gate: `view_acquisitions` (GET) / `manage_acquisitions` (mutator). Quotazioni collegate = quote del `project_id` (o del `client_id` se nessun progetto).

## UI: pagina `/acquisitions` (sezione Anagrafica nav)

Toggle **Kanban ⇄ Tabella** (stesso dato, no refetch dove possibile):
- **Header KPI**: Σ potenziale pesato (totale + breakdown per-reparto), n° trattative aperte.
- **Filtri**: reparto · commerciale (owner) · cliente · stato (aperte/vinte/perse). Ordini deterministici (clienti alfabetico; reparti/stadi per sort_order).
- **Striscia mini-agenda**: prossimi impegni (`next_action_date`), cliccabili → trattativa.
- **Kanban**: 6 colonne (lead…lost), card trascinabili (drag = `POST /stage`; `won` → prompt converti in Progetto). Card: titolo · cliente/prospect · € · prob% · badge reparti · prossima azione · owner.
- **Tabella**: righe ordinabili/filtrabili, cambio stadio inline (dropdown).

### Pannello dettaglio (click trattativa)
- Header: titolo · cliente/prospect · stadio · owner · €×prob (pesato) · tag reparti · expected close.
- **Timeline attività** + quick-add (1 form compatto: tipo/data/contatto/oggetto/nota/prossima azione).
- **Quotazioni collegate** (stato + importo + prob) → link `/quotes`. "da emettere" = stadio quoting senza Quote → CTA.
- **Contatti del cliente** (add/edit inline; `is_primary` sincronizza il referente cliente).
- Azioni: **Converti in Progetto** · **Segna vinta/persa** (lost → chiede `lost_reason`).

## Fix incluso: modifica stato Progetto (bug segnalato)
Il backend `projects.py` PUT accetta già `status`. La Fase 1 **espone il controllo stato nella UI progetti** (selettore stato che salva) e lo sincronizza dalla pipeline (conversione/cambio stadio). Verifica in implementazione se il bug è "selettore assente" o "selettore non salva".

## AI: capability copilot (gancio F1)
Nel registry copilot (pattern `propose_*`, conferma utente):
- `propose_acquisition` (crea trattativa: title + client/prospect + stage + value)
- `propose_activity` (logga comunicazione su una trattativa/cliente/progetto)
- `propose_contact` (aggiunge contatto a cliente)
- `propose_acquisition_stage` (avanza/cambia stadio)

Così il copilot è utile da subito; l'estrazione email-paste + web (Fase 2) costruirà sopra queste capability. I provider legacy senza tool nativi vedono le trattative nel `build_context`.

## Convenzioni / non-funzionali
- Tenant scope su ogni query; `CURRENT_TENANT` in cima al router.
- Soft-delete (`is_active=False`); progressivi/unicità con `include_deleted=True` se servono.
- API form-based (`Form(...)`), `FormData` dal frontend.
- Migrazione `scripts/migrate_acquisitions.py` (ALTER/CREATE idempotenti) + `_auto_migrate_columns()`/create_all al boot per le tabelle nuove.
- Audit-log sui cambi stadio (riuso meccanismo esistente).
- i18n 5 lingue (`it/en/fr/de/es`) per ogni stringa nuova, stesso commit; `data-i18n` nei template.
- Ordini menu/colonne deterministici.
- Cache-buster automatico via `app_version` per static toccati.
- TDD: modello + `acquisition_service` (probabilità/pesato/summary/convert) + endpoint + capability. Smoke browser (kanban drag, tabella, dettaglio, mini-agenda, 0 errori console).

## Fuori scope Fase 1
- Incolla-email → AI estrazione + incrocio web → **Fase 2**.
- Agenda piena + Google Calendar/ICS → **Fase 3**.
- Allocazione € per reparto (resta a livello trattativa).
- Lead scoring automatico oltre la pesatura stadio×valore.

## Criteri di successo
1. Un commerciale crea una trattativa (anche prospect senza cliente) in pochi click.
2. La board mostra le trattative per stadio; il drag cambia stadio e aggiorna il potenziale.
3. KPI header mostra Σ pesato totale + per-reparto coerente con i filtri.
4. La timeline registra email/call/meeting/note con prossima azione; la mini-agenda li elenca.
5. Conversione trattativa→Progetto crea/collega il progetto e ne imposta lo stato.
6. Lo stato del Progetto è modificabile dalla UI.
7. Il copilot può creare/avanzare trattative e loggare attività su conferma.
8. 0 regressioni test; smoke browser verde.
