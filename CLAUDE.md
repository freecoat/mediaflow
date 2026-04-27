@.claude/recall-context.md

# MediaFlow — Contesto del progetto

> Questo file viene letto automaticamente da Claude Code all'avvio.
> Contiene la visione strategica, le decisioni architetturali e lo stato di avanzamento.
> Aggiornarlo quando si chiudono fasi importanti o si prendono decisioni di design.

---

## Cos'è MediaFlow

MediaFlow è una **piattaforma di gestione per case di post-produzione audiovisiva** con AI-assistente integrato come co-pilota. Non è un gestionale generico. Non è solo un CRM. È pensato come **hub di coordinamento umano-AI** per il lavoro di post-produzione, dalla quotazione iniziale fino al cost report finale.

L'utente principale è il proprietario del progetto: **Matteo Lepore**, manager con esperienza diretta nel settore, che parla italiano. Il prodotto sta nascendo per uso interno della sua azienda ma è progettato fin dall'inizio per essere **adattabile e portatile** verso altre case di post.

## Visione del prodotto

Il mercato post-produzione è intrinsecamente disordinato: centinaia di standard di consegna (Netflix, Amazon, Sky, RAI, A24, BBC, Vision, Medusa, Mubi…), specifiche tecniche in evoluzione continua, lavorazioni ibride umane+digitali. Un sistema rigido non regge.

MediaFlow si propone come **impalcatura flessibile su cui l'AI costruisce conoscenza specifica** attraverso interazione con l'utente e con fonti esterne (web, capitolati, email). Tre principi chiave:

1. **AI come co-pilota, non come feature**. Partecipa attivamente a quotazioni, planning, reporting, ma non è invasiva. Il sistema deve funzionare al 100% anche senza AI attiva.
2. **AI propone, utente dispone**. Ogni azione automatizzata passa da conferma umana esplicita ("AI Action + User Confirmation"). Tracciabilità completa.
3. **Listino generico modulare**. Il listino TPR Berlin è esempio iniziale, non standard. Ogni casa di post ha il suo, e il sistema si adatta.

## Decisioni architetturali confermate

- **Stack**: FastAPI + SQLAlchemy + Jinja2 templates + SQLite. Niente React SPA, niente build step. Distribuibile in cartella, eseguibile offline su Mac/Windows.
- **Multi-tenant SOFT da subito**. Tutte le entità di business hanno `tenant_id` (default=1). Multi-tenant HARD (onboarding, billing, separazione fisica) rimandato a Fase 7 opzionale.
- **AI Provider astratto**. Supporto Claude (Anthropic), GPT (OpenAI), Ollama (locale). NON lock-in su un solo vendor. I prompt sono indipendenti dal provider.
- **AI a due livelli**: deterministico leggero (regex, matching keyword) per cose ripetitive + LLM solo dove serve davvero. Riduce costi e latenza.
- **Reparti come entità centrale trasversale**. DI/Video, VFX, Audio, Commercial. Ogni risorsa e voce listino appartiene a un reparto. Reparto = unità di responsabilità finanziaria.
- **DeliveryTemplate strutturati a 8 blocchi JSON**: video_specs, audio_specs, text_specs, head_format, textless_format, naming_convention, archive_specs, metadata_requirements. Schema flessibile che regge tutti i capitolati analizzati (A24, Vision, NBCU TechOps).
- **Tono**: italiano, professionale, conciso. Risposte dirette, niente filler. Niente self-deprecation di Matteo: la sua expertise di dominio guida il prodotto.

## Stato di avanzamento

### ✅ Fase 1 completata (v2.1)
- Gerarchia Cliente → Progetto → Quotazioni → Job
- Listino con 3 livelli prezzo (List/Average/Low) + hardcosts
- Quotazioni A/B/C con sconto pacchetto, IVA, export PDF (ReportLab)
- Conversion Quote → Job con auto-creazione JobCostLines
- DAM per progetto, Resource booking, Cost Report con Quotato/Maturato/Stimato
- Auth JWT con ruoli (admin/manager/staff/viewer), bcrypt diretto, PyJWT
- Compatibilità Python 3.11/3.12/3.13/3.14
- **Testato e funzionante** sul Mac di Matteo (Python 3.14, no admin)

### ✅ Fase 1-bis completata (v3.0)
- Modelli: `Tenant`, `Department`, `DeliveryTemplate`
- Campo `keywords` su PriceItem (lista per matching AI)
- Campo `department_id` su PriceItem e Resource
- ResourceType esteso: `person_internal`, `person_freelance`, `studio`, `equipment`, `software`, `vehicle` (mantenuto `person` per retrocompat)
- Resource: aggiunti `role`, `email`, `phone`, `internal_phone`
- Pagina `/departments` con CRUD completo via UI
- Pagina Risorse rivista con filtro reparto + tab per tipo + modal completo
- Pagina Listino rivista con filtro reparto + ricerca su keywords + modal con keywords editabili
- Listino di esempio (`LISTINO_ESEMPIO`, 76 voci) con descrizioni neutre, senza riferimenti a marchi (FilmMaster/Nucoda/Barco/Euphonix sostituiti)
- Script di migrazione non distruttivo `scripts/migrate_phase1bis.py` per database esistenti
- Script di setup nuovo `scripts/seed_demo.py` aggiornato con tenant + reparti + keywords
- Strumenti.bat e strumenti.sh aggiornati con voce migrazione 1-bis
- **Da testare** sul Mac di Matteo

### ✅ Fase 2 step A+B completata (v3.2.1, 26 aprile 2026)

**Step A — Configurazione AI per-utente (live, no restart)**
- Modello `UserAISettings` (user_id + provider + api_key cifrata Fernet + model + base_url + verified_at)
- Colonna `users.active_ai_provider` per scelta provider attivo
- Cifratura `cryptography.fernet` con chiave dedicata `AI_KEY_ENCRYPTION_KEY` in `.env` (separata da `SECRET_KEY` JWT, generata automaticamente dallo script di migrazione)
- 5 provider supportati: **Claude** (Opus 4.7 / Sonnet 4.6 / Haiku 4.5), **OpenAI** (GPT-4o / o1 / o3-mini), **Gemini** (2.0 Flash / Flash Thinking / 1.5 Pro), **Perplexity** (Sonar Pro / Sonar / Sonar Reasoning), **Ollama** (locale)
- Tab `🤖 AI` in `/settings` con card per provider, input api_key masked, dropdown modello, bottone Test connessione (ping minimale che valida auth), radio Provider attivo
- Endpoint: `GET/POST/DELETE /settings/api/ai*`

**Step B — Copilot context-aware con pattern "AI propone, utente dispone"**
- Pulsante 💬 fisso (FAB) in basso a destra, drawer 420px laterale destra, presente su tutte le pagine via `base.html` include `components/copilot.html`
- Context auto-detection da URL: `/projects/{id}`, `/quotes#{id}`, `/jobs/{id}`
- `build_context()` esteso: vista d'insieme DB (clienti/progetti/listino/quote/risorse/asset, categorie, reparti) + dettaglio entità in canvas
- AI risponde in markdown + opzionalmente blocchi ```` ```action ... ``` ```` JSON estratti server-side e salvati come `AIAction` status=`proposed`. Niente esecuzione senza conferma.
- 7 capability disponibili: `propose_client`, `propose_project`, `propose_project_metadata`, `propose_quote` (con `lines` opzionali → quote+righe in singolo Apply, auto-numero `Q-{anno}-NNN`, default date oggi/+30gg), `propose_quote_line`, `propose_price_item`, `web_search` (Tavily read-only)
- System prompt rinforzato: distinzione `id` (PK numerico) vs `code` (stringa), divieto di inventare date passate, una sola azione per turno se non concatenate logicamente
- Card di conferma nel drawer con bottoni Applica/Rifiuta. Storia conversazioni cliccabile.
- Endpoint nuovi: `POST /ai/api/actions/{id}/apply`, `POST /ai/api/actions/{id}/reject`
- Tabella `ai_actions` per audit completo: `proposed → applied | rejected | failed`

**Migrazione**: `scripts/migrate_ai_per_user.py` (opzione `[8]` su `strumenti.bat/sh`). Idempotente: crea tabelle, ALTER su users, genera `AI_KEY_ENCRYPTION_KEY` se mancante.

**Smoke test E2E**: `/health` 200 v3.2.1, /settings/api/ai 200 con 5 provider, save/test/activate/delete provider funzionanti, apply su `propose_client` e `propose_price_item` validi (Client.contact_email + PriceCategory autocreata). `propose_quote` con `lines` ritestato dopo fix auto-numero.

**Patch v3.2.1 (sera 26 aprile 2026)**:
- `propose_quote` capability completata end-to-end: auto-`number`, default date, `lines` opzionali transazionali (singolo Apply crea quote + righe).
- `propose_project` capability aggiunta (richiede `code`+`title`+ `client_id`/`client_name`).
- `clients.py` migrato a `get_provider_for_user()` per-utente; tenant filter su tutte le by-id queries; `tenant_id=CURRENT_TENANT` impostato anche su `search-enrich`.
- `enrich_client()` accetta ora `provider` iniettato dal router.
- UI `/clients` modal "Nuovo cliente": secondo bottone "✨ Crea + popola con AI" che crea + arricchisce in un solo flusso (salvataggio anche se l'arricchimento fallisce).

### 🔜 Fase 2 step C+D — Knowledge Base capitolati (rimandato)
- F14: upload capitolato → `deliverables_parser` → preview → conferma utente → `DeliveryTemplate` salvato
- F15: test E2E sui 17 capitolati reali in `docs/capitolati_esempio/`
- Già scaffolded in `deliverables_parser.py`, va cablato in UI dedicata.

### 🔜 Fasi successive
- **Capability AI avanzate** (estensioni del primo push): popolazione DB cross-check web automatica, tool-use vero per ricerca→insert; integrazione email/Drive/Office (OAuth flow); accesso filesystem Asset Library; automazione portali consegne (passo-passo, per portale)
- **Fase 3**: arricchimento clienti/progetti via web (Tavily) — codice in `client_enrichment.py`, da cablare in UI con approval workflow
- **Fase 5**: import capitolato con matching automatico voci listino — `deliverables_parser.match_deliverables_to_pricelist` già esistente
- **Fase 6**: reporting AI-assisted con narrative reports in italiano
- **Fase 7**: multi-tenant HARD (opzionale, per commercializzazione)

## Capitolati di riferimento (`docs/capitolati_esempio/`)

17 documenti reali disponibili, copertura completa di mercato:

**Cinema theatrical / distribuzione**
- A24 Delivery Schedule — Queer (Guadagnino) — Dolby Vision/Atmos
- MUBI — Queer Exhibit C
- IRDA / PiperFilm — Allegato Materiali
- Vision Distribution — Allegato A (distribuzione italiana)
- Veterans Sales Agent Delivery Schedule

**TV broadcast italiana**
- RAI — Specifiche Tecniche Prodotti Televisivi 1.4
- Sky — Specifiche Tecniche SkyOriginal + SKY 5.1 Audio Requirements

**Streaming globale**
- Netflix Deliverables
- Amazon MGM Deliverables

**Distribuzione TV internazionale**
- BETA FILM Delivery Master
- FREMANTLE DCP Deliverables Supplemental
- NBCUniversal TechOps v2.8 + Metadata Template v1.3
- ContentArmor Tech Meta Cheat Sheet

Tutti confermano la struttura a 8 blocchi `DeliveryTemplate` (video/audio/text/head/textless/naming/archive/metadata).

## Convenzioni di codice

- **Lingua**: codice in inglese, commenti e UI in italiano. Email demo `@mediaflow.it`.
- **Modelli SQLAlchemy 2.0**: `Mapped[type]` + `mapped_column`. Niente ORM legacy.
- **Tenant filter**: ogni query nei router parte con `Filter(Tenant_id == CURRENT_TENANT)`. La costante `CURRENT_TENANT = 1` sta in cima a ogni router. Quando si farà multi-tenant hard, sarà sostituita da una dependency injection.
- **Form-based API**: i POST/PUT accettano `Form(...)` non JSON. Le chiamate dal frontend usano `FormData`. Non cambiare convenzione senza motivo.
- **Soft delete**: `is_active=False` invece di DELETE fisico (eccetto rare eccezioni come Department). I record cancellati sono recuperabili.
- **Migrazioni manuali**: niente Alembic per ora. `scripts/migrate_phase1bis.py` è il pattern: ALTER TABLE idempotenti via SQL grezzo + populate dati. Quando si aggiungono modelli/colonne, scrivere uno script di migrazione separato.
- **Python compatibility**: 3.11+ con priorità a 3.14. Niente `python-jose`, niente `passlib`, niente `WeasyPrint`. Usare `PyJWT`, `bcrypt` diretto, `ReportLab`.
- **Frontend**: niente framework. Vanilla JS in `static/js/global.js` con helper `api()`, `openModal()`, `closeModal()`, `toast()`. Stile dark con CSS variabili in `static/css/main.css` (palette indaco `#6272f5`).

## Come testare la Fase 1-bis

Sul Mac di Matteo:

1. **Database fresco** (preferito per test pulito):
   ```
   ./strumenti.sh → opzione 2 (resetta database)
   ```
   Crea da zero con `seed_demo.py`. Verifica: tenant default, 4 reparti, 76 voci con reparti+keywords, 3 progetti, 1 quotazione, 1 job.

2. **Migrazione su DB esistente**:
   ```
   ./strumenti.sh → opzione 6 (migra v2 → v3)
   ```
   Esegue ALTER TABLE non distruttivi, popola tenant/reparti/keywords. Tutti i dati esistenti preservati.

3. **Verifica UI**:
   - `/departments` — vedi 4 reparti, prova creazione/modifica/eliminazione
   - `/resources` — filtro reparto, tab tipo, modal con tutti i campi
   - `/pricelist` — filtro reparto, ricerca per keyword, badge reparto, edit keywords

## Domande aperte / decisioni da prendere

- **Per Fase 2**: chi paga le API AI? Modello "porta la tua API key" (gratis per Matteo, meno integrato) vs "API incluse" (Matteo paga). Decisione rinviata.
- **Per Fase 4**: priorità tra arricchimento clienti (Fase 3) e copilot/notifiche (Fase 4). Roadmap originale Fase 3 prima, ma Fase 4 dà demo più "wow".
- **Vendibilità**: desiderata futura ma non requisito attivo. Architettura multi-tenant soft sufficiente ora.

## Modelli AI di riferimento (Apr 2026)

- **Anthropic** — Opus 4.7 (top), **Sonnet 4.6 (default MediaFlow)**, Haiku 4.5 (rapido/economico)
- **OpenAI** — GPT-4o (default), o1, o3-mini per ragionamento
- **Ollama locale** — llama3.1:70b configurato di default, sostituibile

Default modificabile via UI Impostazioni AI (Fase 2 F13) — `.env` solo per fallback iniziale.

## Bug noti (snapshot 2026-04-25)

Risolti in questa sessione:
- ✅ `/resources/` 500 error per `TYPE_LABEL` undefined in Jinja → iniettato server-side da router
- ✅ `config.py` modello default `claude-sonnet-4-5` → `claude-sonnet-4-6`

Da verificare/sistemare:
- `/clients/` "stuck on loading" sul Mac di Matteo: probabilmente DB non migrato a Fase 1-bis. Eseguire `./strumenti.sh → opzione 6` su Mac.
- ✅ `app/routers/clients.py` ora filtra per `tenant_id` su tutte le query e usa `get_provider_for_user()` (sistemato in v3.2.1).

## File chiave da consultare

- `app/models/models.py` — Tutti i modelli ORM
- `scripts/seed_demo.py` — Setup demo + LISTINO_ESEMPIO + KEYWORDS_MAP + DEFAULT_DEPARTMENTS
- `scripts/migrate_phase1bis.py` — Pattern per migrazioni non distruttive
- `app/routers/departments.py` — Pattern CRUD pulito da copiare per nuove entità
- `app/templates/pages/departments.html` — Pattern UI CRUD da seguire
- `CHANGELOG.md` — Storia delle versioni e decisioni

## Comportamento atteso da Claude Code

- **Conciso**: Matteo ha settato `<userPreferences>` con preferenza per spiegazioni brevi. Risposte dirette, no preamboli.
- **Domandare prima di fare grandi cambi**: pattern "AI propone, utente dispone" vale anche tra Claude e Matteo.
- **Mai dare per scontato**: anche se Claude vede il codice, non assumere preferenze tecniche; chiedere quando non chiaro.
- **Test prima di affermare "funziona"**: scrivere → eseguire → verificare → solo dopo dichiarare completato.
- **Aggiornare questo file** quando si chiudono fasi importanti o si prendono decisioni architetturali significative.
- **Leggere `docs/STATO.md` a inizio sessione**: snapshot operativo con versione corrente, lavoro in corso, prossimo step concordato, bug aperti. È la fonte primaria per orientarsi quando si rientra. Va aggiornato a fine iterazione (versione + sezione "in corso" + sezione "prossimo step").
- **Git tenuto pulito**: il progetto è in git da v3.4.2. Commit a ogni versione finita (bump `main.py` + CHANGELOG + commit nello stesso giro). Niente force-push, niente skip hooks.

---

*Ultimo aggiornamento: 27 aprile 2026 sera tardi — v3.4.2: quick wins copilot (textarea + a capo, stop client-side, parser JSON tollera commenti `#`/`//`/`/* */`) + categoria libera per riga in quote (override) + export PDF/CSV/XLSX rispettano override. Aggiunti `docs/STATO.md` operativo e git inizializzato.*
