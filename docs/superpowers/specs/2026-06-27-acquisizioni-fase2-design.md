# Acquisizioni — Fase 2: estrazione email + incrocio web (design)

**Data**: 2026-06-27
**Versione target**: v3.5.0-alpha.172.237+
**Stato**: approvato (design), pronto per implementation plan

## Contesto e obiettivo

Fase 2 del modulo Acquisizioni (Fase 1 = pipeline trattative + attività, già mergiata in `main` α.172.236). Obiettivo: il commerciale **incolla una conversazione email** nel copilot e l'AI propone, in modo confermabile, le informazioni rilevanti estratte — registrando la comunicazione, aggiornando contatti e cliente, avanzando la trattativa — e, su richiesta, **incrocia i dati con il web** (fonti configurabili) per arricchire cliente e progetto.

**Decisioni dal brainstorming**:
- **Entry point**: dentro il **copilot esistente** (drawer), non una pagina nuova. Sfrutta il context-detection già presente (se sei su una trattativa/cliente/progetto, l'estrazione si lega lì).
- **Estrazioni da email** (tutte e 4): (a) log attività con email salvata, (b) contatto dalla firma, (c) aggiornamento dati cliente, (d) avanzamento trattativa + prossimo passo.
- **Incrocio web**: **step esplicito su richiesta** ("🔎 Cerca sul web"), non automatico (controllo costo Tavily).
- **Modello estrazione**: **provider attivo del copilot** (coerente con "nel copilot"; nessuna promozione automatica).
- **Fonti web configurabili**: in **Impostazioni** si gestisce la lista dei siti/domini da cui raccogliere informazioni; lo step web li usa come `include_domains` Tavily.

## Infrastruttura esistente riusata
- `app/routers/ai.py`: copilot chat → estrae blocchi `action` → crea `AIAction` (status=`proposed`) → `POST /ai/api/actions/{id}/apply|reject`. Flusso propose→conferma completo.
- Capability registry `@ai_capability` + `ai_tools.py` (tool descriptor) + `ai_context.py` (build_context).
- Capability già presenti: `propose_activity`, `propose_contact`, `propose_acquisition`, `propose_acquisition_stage` (Fase 1); `propose_client` (CREA), `propose_project_metadata` (aggiorna progetto); `web_search` (Tavily, read-only, **egress-gated** via `egress_guard.web_search_allowed_current`).
- `app/services/web_search.py` `tavily_search(...)` supporta già `include_domains`.
- `app/services/client_enrichment.py` `enrich_client(...)` (web enrichment cliente, nativo Claude o Tavily).
- `Tenant` (models.py:605) ha già colonne JSON (es. `naming_conventions`) → pattern per `web_sources`.

## Gap da colmare (cosa è davvero nuovo)
1. **Affordance "📥 Incolla email"** + **"🔎 Cerca sul web"** nel drawer copilot + system prompt "email-aware".
2. **Capability `update_client`** (aggiorna campi di un cliente esistente; oggi `propose_client` solo crea).
3. **Capability `propose_client_work`** (voce filmografia da web) + **modifica a `web_search`** perché usi `tenant.web_sources` come `include_domains` (egress-gated invariato).
4. **`Tenant.web_sources`** (JSON lista domini) + UI Impostazioni per gestirla + seed default.

## Componenti

### 1. UI: box "Incolla email" nel drawer copilot
- Bottone "📥 Incolla email" nel drawer (`components/copilot.html`). Apre una textarea; al submit invia al copilot un messaggio che **avvolge** il testo incollato con un'istruzione di estrazione + il context corrente (es. `"Estrai le informazioni rilevanti da questa email e proponi le azioni. Contesto: trattativa #{id}.\n\n<email>"`).
- Riusa l'endpoint chat esistente (`POST /ai/api/chat`); nessun nuovo endpoint chat. La risposta passa per il normale rendering delle card AIAction.
- i18n 5 lingue per il bottone/placeholder.

### 2. System prompt "email-aware"
Estensione del system prompt copilot (`ai_assistant.py` / dove vive il prompt): quando il messaggio contiene una conversazione email, l'AI deve:
- identificare mittente/destinatario, contatti (firma), intento, prossimo passo, date;
- usare il context (trattativa/cliente/progetto) per collegare le proposte;
- proporre in **un turno** il sottoinsieme rilevante di: `propose_activity` (type=email, `direction` in/out inferita, `subject`, **`body`=email grezza**, `next_action_date`, `ai_extracted=True`), `propose_contact` (dalla firma), `update_client` (campi rivelati), `propose_acquisition_stage` + `next_action` (se l'intento implica un avanzamento);
- **non** cercare sul web in automatico; se utile, suggerire lo step esplicito "🔎 Cerca sul web".
- Regola anti-invenzione: non inventare P.IVA/recapiti non presenti nell'email.

### 3. Capability `update_client`
- Handler `@ai_capability("update_client")` → `_h_update_client(db, data)`: risolve `client_id` (PK) tenant-scoped; aggiorna SOLO i campi forniti e non vuoti (name/legal_form/contact_*/admin_email/vat_number/tax_code/sdi_code/pec/address/city/country/zip_code/province/website/industry/company_size/founded_year/notes). Ritorna `{updated, client_id, changed_fields, message}`. Raise ValueError se `client_id` mancante o cliente inesistente.
- Tool descriptor in `ai_tools.py` con `client_id` required + campi opzionali; description chiara ("aggiorna un cliente ESISTENTE; usa propose_client per crearne uno nuovo").
- Nessuna sovrascrittura silenziosa di campi non passati.

### 4. Step web esplicito = turno copilot (NON una mega-capability annidata)
Per evitare macchinari di "proposte annidate", lo step web riusa il flusso chat→action esistente:
- Il bottone "🔎 Cerca sul web" (nel drawer e/o come azione suggerita dopo l'estrazione) invia a `POST /ai/api/chat` un messaggio mirato: `"Cerca sul web informazioni sul cliente <nome> e sul progetto <titolo> usando le fonti configurate, poi proponi gli aggiornamenti."` + context (`client_id`/`project_id`).
- Il copilot (provider attivo) chiama la capability **`web_search`** esistente — **arricchita** perché passi `include_domains = tenant.web_sources` a `tavily_search` (oggi non li passa). Resta **egress-gated**: se `not egress_guard.web_search_allowed_current(db)` → messaggio "Ricerca web disabilitata dal Content Lockdown", nessuna chiamata esterna.
- Sulla base dei risultati, il copilot emette i normali blocchi `action` → il router crea `AIAction` proposed: `update_client` (dati azienda), `propose_project_metadata` (intel progetto), `propose_client_work` (voce filmografia). Niente nuovo percorso di materializzazione: sono card singole come tutte le altre.
- **`propose_client_work`** (nuova): handler `@ai_capability("propose_client_work")` → crea una voce `ClientWork` (filmografia) tenant-scoped con `ai_imported=True` + `sources_json` (URL fonti). Riusa il modello `ClientWork` esistente. Tool descriptor con `client_id`+`title` required.
- **Modifica a `web_search`**: leggere `tenant.web_sources` e passarlo come `include_domains` (lista vuota/NULL → nessuna restrizione, comportamento attuale). Resta read-only ed egress-gated.

### 5. Impostazioni: fonti web (`Tenant.web_sources`)
- Modello: `Tenant.web_sources: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)` — lista di domini (es. `["filmitalia.org","cinema.cultura.gov.it","imdb.com","mymovies.it"]`).
- Migrazione `scripts/migrate_web_sources.py` + auto-migrate al boot (ALTER ADD COLUMN). Seed default sui tenant esistenti (lista curata) se NULL.
- UI in `/settings` (tab esistente o nuova sezione "Fonti web / AI"): lista editabile di domini (aggiungi/rimuovi), salvataggio via endpoint `GET/POST /settings/api/web-sources`. Gate `manage_settings_global` (o `edit_settings`). i18n 5 lingue.
- Lo step web (`propose_web_enrichment`) legge `tenant.web_sources` e li passa come `include_domains`. Lista vuota → ricerca non ristretta (comportamento Tavily di default) con avviso.

## Flusso dati (email → proposte)
1. Utente clicca "📥 Incolla email", incolla, submit.
2. Drawer invia a `POST /ai/api/chat` il testo avvolto + context.
3. Copilot (provider attivo) risponde con blocchi `action` → router crea `AIAction` proposed (propose_activity/contact/update_client/acquisition_stage).
4. Drawer mostra le card; utente applica/rifiuta singolarmente.
5. (Opz.) Utente clicca "🔎 Cerca sul web" → messaggio mirato al copilot → capability `web_search` (egress ok) su `tenant.web_sources` (include_domains) → il copilot emette blocchi action → ulteriori card (update_client / propose_project_metadata / propose_client_work).

## Error handling
- Egress bloccato → step web no-op con messaggio chiaro (no chiamata esterna).
- Provider non configurato → messaggio "configura un provider in Impostazioni → AI".
- Email vuota/troppo corta → il copilot risponde senza azioni.
- `update_client`/`propose_client_work` con id mancante/cross-tenant → ValueError → card non creata.
- Nessuna sovrascrittura di campi cliente non presenti nell'email.

## Convenzioni / non-funzionali
- Tenant scope su ogni query e capability (`current_tenant_id()`); soft-delete dove applicabile.
- API form-based per gli endpoint settings; i POST copilot restano JSON come oggi.
- Egress: ogni uscita web passa da `egress_guard` (Content Lockdown TPN).
- i18n 5 lingue per ogni stringa UI nuova (bottone email, settings fonti web), stesso commit.
- Migrazione idempotente + auto-migrate boot per `Tenant.web_sources`.
- Cache-buster automatico via `app_version` per static toccati.
- TDD: capability (`update_client`, `propose_client_work`), `web_search` con `include_domains` da `web_sources`, settings endpoint, migrazione. Smoke browser: incolla email demo → card proposte → apply; settings fonti web; step web con egress on/off.
- Privacy: l'email grezza è salvata in `Activity.body` (record della comunicazione) — comportamento atteso, coerente con "tieni traccia delle comunicazioni".

## Fuori scope Fase 2 (→ Fase 3)
- Agenda piena + sync Google Calendar (OAuth) / ICS.
- Parsing automatico di allegati email (solo testo incollato in Fase 2).
- Ingest email automatico (IMAP/OAuth mailbox) — solo incolla manuale.

## Criteri di successo
1. Incolli un'email nel copilot → proposte: log attività (email salvata) + contatto + eventuali aggiornamenti cliente + prossimo passo/stadio, ciascuna confermabile.
2. `update_client` aggiorna solo i campi rivelati, senza toccare il resto.
3. "🔎 Cerca sul web" propone aggiornamenti da internet ristretti alle fonti configurate, e rispetta il Content Lockdown (no egress se bloccato).
4. Le fonti web sono gestibili in Impostazioni e usate come `include_domains`.
5. 0 regressioni test; smoke browser verde.
