# STATO — MediaFlow

> Snapshot operativo, aggiornato a fine iterazione.
> Claude lo legge a inizio sessione per orientarsi, e lo aggiorna a fine giro.
> CLAUDE.md = visione/architettura. STATO.md = "dove siamo adesso, cosa fare dopo".

---

## Versione corrente

**v3.5.0-alpha.172.173** — 2 giugno 2026 — Self-host Cloudflare Tunnel + asset metadata-only

### α.172.173 ✅ (self-host on-prem + principio asset)
`docker-compose.tunnel.yml` (claqo interno + cloudflared named via TUNNEL_TOKEN, no port-forward/CGNAT-ok) + `docs/SELF-HOST.md` (setup, Cloudflare Access, backup offsite). `.env` +TUNNEL_TOKEN. **Principio asset formalizzato**: SaaS = solo metadato+reference; binari sui server tenant (già implementato `fs-scan`/`fs-import` → Asset.file_path reference, no copia). Roadmap MAM/S3. Nessun cambio codice. 313 test.

**3 vie hosting pronte**: A) VPS+Caddy (`docker-compose.prod.yml`) · B) self-host ufficio Cloudflare Tunnel (`docker-compose.tunnel.yml`) · C) semplice/local-docker (`docker-compose.yml`). Tutte SQLite singola istanza. Setup reale (build immagine + tunnel/dominio) da fare sull'host quando Matteo decide.

**Prossimo**: Matteo sceglie ambiente (VPS vs ufficio) e procede al deploy reale; oppure altro lavoro app. Push commit .160→.173 (15) quando OK.

### α.172.172 — 2 giugno 2026 — Deploy VPS con Caddy (HTTPS) + cookie Secure

### α.172.172 ✅ (deploy VPS HTTPS + hardening cookie)
`docker-compose.prod.yml` (claqo interno + Caddy 80/443 TLS auto + header sicurezza) + `deploy/Caddyfile` + cookie `secure` condizionale prod (access_token/MFA/portal). DEPLOY.md flow A/B + roadmap. Login dev verificato (303, no-secure). 313 test.

**Linea hosting CONFERMATA (Matteo)**: VPS EU + **SQLite singola istanza**. Self-hosted sempre supportato. **Postgres = milestone con trigger** (2° tenant/database-is-locked/più worker/cliente enterprise) → comporta Float→Numeric + Alembic + retest. **Isolamento clienti sicurezza = deployment-per-tenant** (istanza Docker dedicata, già pronto). **DB-per-tenant in 1 istanza = Fase 7** (connection registry). Dominio = col rebrand (Claqo non confermato) → primo deploy IP/sottodominio. Accesso locale dev resta attivo (env-driven). React/Capacitor app rimandata post-hosting.

**Prossimo**: deploy reale su VPS (build immagine sull'host) quando Matteo sceglie provider/dominio; eventuale Postgres quando scatta un trigger.

### α.172.171 — 2 giugno 2026 — Fondazione hosting backend (Docker)

### α.172.171 ✅ (hosting backend — fondazione portabile)
Artefatti deploy: Dockerfile (3.13-slim, non-root, healthcheck, 1 worker SQLite, volume /data) + docker-compose (volume claqo_data) + docker-entrypoint.sh + bootstrap_admin.py (tenant+admin da ENV, idempotente, validato) + .dockerignore + .gitattributes (LF su .sh) + .env.production.example + docs/DEPLOY.md (Caddy HTTPS, backup, sicurezza). App invariata (config già env-driven). Docker non in ambiente dev → build da validare sull'host. 313 test.

**DECISIONI APERTE (Matteo) per proseguire hosting**:
- Provider: PaaS (Fly/Render/Railway, low-ops) vs VPS EU (Hetzner, sovranità+costo, manuale).
- DB: SQLite-su-volume (subito) vs Postgres ora (robusto multi-utente; porting Float→Numeric previsto).
- Dominio/regione (EU consigliata GDPR).
Poi: config provider-specifica (Caddyfile / fly.toml / render.yaml) + deploy reale + hardening auth pubblico.
**App React nativa: rimandata** (Matteo: prematura; prima hosting, poi valutare Capacitor vs React).

### α.172.170 — 2 giugno 2026 — Mobile Fase D: Copilot AI + Agenda settimanale

### α.172.170 ✅ (Mobile Fase D — chiusura iniziativa mobile A→D)
Copilot AI `/m/copilot` (chat + azioni Applica/Rifiuta + markdown-lite XSS-safe, verificato AI reale) + Agenda settimanale `/m/agenda` (my-bookings 7gg + nav settimana). Drawer Agenda + gruppo Assistente. 313 test, 0 errori console.
**Mobile completo Fasi A→D.** Backlog mobile residuo: deliverables read-only, cashflow sintetico, DAM+scan QR, ferie-richiesta, offline-sync vero, planning all-resources (ora agenda = solo mie).

**Prossimo**: test Matteo da telefono su tutto il mobile. Push commit .160→.170 (12) quando OK. Tunnel :9000 live.

### α.172.169 — 2 giugno 2026 — Mobile: Quote + timbra rapida + fix risposta assegnazioni

### α.172.169 ✅ (loop operativo mobile)
Quotazioni `/m/quote` (list+detail: totali/voci/valuta) + drawer + link da progetto detail. Timbra rapida one-tap ENTRATA/USCITA su Oggi. Fix `my-bookings` ritorna `response_status` (card assegnazioni mostra stato post-reload). 313 test, 0 errori console.

**Prossimo Mobile Fase D**: copilot AI mobile + planning lista settimanale. Backlog mobile: deliverables read-only, cashflow sintetico, DAM+scan QR, ferie richiesta. Push commit .160→.169 quando OK.

### α.172.168 — 2 giugno 2026 — Mobile Fase C (crea booking + cost report essenziale)

### α.172.168 ✅ (Mobile Fase C — azioni)
Creazione booking `/m/booking/new` (form tipo/job→JCL/risorsa/data/orari, gestisce force_single_type + 403 staff) + cost report essenziale `/m/finance/{job_id}` (KPI + voci costo + fatturazione). Entry point booking su Oggi+drawer. Righe Finance → detail. Verificato end-to-end (POST 200 + cleanup), 0 errori console.

**Prossimo Mobile Fase D**: copilot AI mobile + planning lista settimanale. Altre possibilità: timbra rapida da Oggi, dettaglio assegnazione+rispondi (c'è respond), notifiche azioni inline, deliverables view read-only, quote detail. Push commit .160→.168 quando OK.

### α.172.167 — 2 giugno 2026 — Mobile Fase B (consultazione business) + audit + mobile force-view

### α.172.165–167 ✅ (audit capitolati + force mobile + mobile Fase B)
- **.165** `scripts/audit_capitolati.py` read-only (TC/FK/enum/colore/segmenti). Fix Fremantle TC. 12 item UHD Rec.2020 PQ+SDR lasciati (RAI inaffidabile, scelta Matteo).
- **.166** middleware `mobile_force_view`: UA smartphone → 302 /m (escape cookie `prefer_desktop`, link drawer + `/prefer-desktop`/`/prefer-mobile`).
- **.167 MOBILE FASE B**: /m da punch-app a companion business. Progetti (list+detail), Clienti (list+detail, tap-to-call), Finance (KPI+job read-only), Cerca globale. Tile su Oggi + gruppo Business drawer + 🔍 topbar. Helper mobile.js + CSS. Dati via fetch endpoint JSON desktop (no nuovo backend). 0 errori console, viewport 390px verificato.

**Prossimo**: Mobile Fase C (azioni: rispondi assegnazioni già c'è; eventuale crea/modifica leggera) + Fase D (copilot/planning lista). Test Matteo da telefono. Push commit .160→.167 quando OK. Tunnel :9000 live (`/m`).

### α.172.164 — 2 giugno 2026 — Timecode SMPTE corretto + scan color primaries

### α.172.162–164 ✅ (tech specs: aspect/color tendine + TC SMPTE — remote-control Matteo)
- **.162** aspect_ratio → select (era input libero).
- **.163** color_space → select + nuovo campo `color_primaries` (gamut CICP). Schema+migrate+backend+2 editor.
- **.164 TIMECODE**: nuovo `app/services/timecode.py` SMPTE 12M (parse/validate/normalize + TC↔frame con **drop-frame** Heidelberger + coerce). Validazione su PUT template/item (tc_start/program_start/segmenti, fps-aware) → 422 se fuori range + zero-pad auto. `_clean_tc` estrattore scarta TC invalidi. **Fix dati Vision tpl12** (era 59:59:00:00 invalido → 00:59:59:00; black in 00:59:59:00 out 01:00:00:00). **Auto-mask** `.tc-mask`: ":" automatici digitando. **Scan primaries** `scripts/backfill_color_primaries.py`: 122/210 item derivati da color_space/hdr/res, 88 ambigui NULL. **313 test** (+16 TC). Smoke browser ok.

**Prossimo**: Matteo verifica TC Vision in UI + i 4 deliverable GLO da legare a mano (.161). Eventuale: transfer/matrix CICP espliciti (ora transfer da hdr_format). Push quando OK (commit .160→.164 non pushati). Tunnel :9000 live.

### α.172.161 — 1 giugno 2026 — Link deliverable ↔ item capitolato end-to-end

### α.172.161 ✅ (deliverable ↔ capitolato — remote-control Matteo)
Due problemi `/planning/?view=deliverables`: (1) deliverable orfani; (2) specs tecniche non visibili/selezionabili. **Causa radice**: catena capitolato→quote→job non persisteva il FK `DeliveryItem` (solo `price_item_id` + `detail` stringa) → `JobDeliverable.delivery_item_id` sempre NULL → modal specs (α.160) cadeva nel JSON vuoto.
- **Schema**: `quote_lines.delivery_item_id` FK + auto-migrate. Picker quote espone `items[]` + sotto-select per bucket multi-item (`delivery_item_map`); mono-item auto-link. Convert quote→job (3 spawn) propaga il FK.
- **Modal planning (approccio B)**: barra selettore capitolato sempre visibile (capitolato→item), preselezionata se linkato / scegli dai capitolati se no. PUT deliverable accetta `delivery_item_id` (str, ""/"0"=unlink). Bottone scollega.
- **Backfill** `scripts/backfill_deliverable_capitolato_link.py` (idempotente): GLO 7/11 auto-linkati, 4 manuali (2 no-capitolato + 2 multi-item ambigui).
- **Cleanup**: 24 orfani rimossi (12 dangling quote_line + 12 su job_id=2 inesistente). Snapshot salvato.
- **297/297** test (+7). Smoke browser E2E ok (preselect + link/unlink UI, 0 errori console).

**Prossimo**: Matteo lega a mano i 4 deliverable residui via selettore; testa picker quote (sotto-select item su bucket multi-item) creando una quote nuova. Push quando OK. Tunnel :9000 live (`inkjet-agreed-peripherals-tank.trycloudflare.com`).

### α.172.159 — 31 maggio 2026 — Mobile v2 Fase A (foundation look + drawer nav)

### α.172.159 ✅ (Mobile v2 Fase A — foundation, subagent-driven 3 task)
Espansione mobile (Matteo: v1 spartano+limitato → livello intermedio). Fase A = look + nav. Drawer laterale (☰, sostituisce tab bar) + design system v2 (`mobile.css` [frontend-design], dark ink-indigo, tokens+componenti+skeleton, 90 classi preservate) + 5 schermate con icone lucide. **290/290** test, E2E ok. **Iniziativa mobile-v2 in 4 fasi**: A look/nav ✅ · B consultazione entità (Agenda/Progetti/Quote/Clienti/Finance) · C azioni · D copilot/planning. Editor pesanti → desktop. Spec/piani in `docs/superpowers/` (2026-05-31-mobile-v2-faseA + mobile-pwa-staff).

**Prossimo**: restart server :9000 (tunnel) col nuovo look per test Matteo; poi Fase B. Restart :8000 di Matteo per currency/backlog/mobile backend.

### α.172.158 ✅ — Versione mobile PWA staff (vedi sotto)

### α.172.158 ✅ (MOBILE PWA staff — feature nuova, subagent-driven 10 task TDD)
Area `/m/*` dedicata (template lean `templates/mobile/`, riusa endpoint JSON esistenti). Scaffold (router mobile + base_mobile + tab bar + mobile.css/js) + PWA (manifest+sw+icone) + 5 schermate (Oggi/Timbra/Notifiche/Ferie/Assegnazioni) + endpoint `POST /planning/api/my-bookings/{id}/respond` (accetta/rifiuta, ownership 403, `BookingAssignment.response_status`+auto-migrate). Auth via middleware globale (no-auth→redirect login, verificato E2E). **288/288** test. E2E: /m/* 200, asset PWA 200, redirect no-auth ok.
Fuori scope: timeline drag, editing pesante, portale cliente, offline-sync (defer).

**Prossimo**: restart :8000 (auto-migrate Invoice/Project/booking_assignments) + test Matteo (currency+backlog+mobile). Mobile: aprire `/m` da telefono / installare PWA. Eventuale push.

### α.172.157 ✅ — Backlog Matteo 7 fix/feature (vedi sotto)

### α.172.157 ✅ (backlog Matteo — 3 agenti paralleli + 1)
Listino: duplica voce + categorie no-troncamento + fix cancellazione (root cause `loadAll active_only=false`). Copilot: dettaglio riga AI ora eredita da PriceItem.description (come picker) + nuova conversazione svuota chat precedente. Progetti: `episodes_count` + auto-migrate + copilot lo legge ovunque. Source-map lucide silenziato. **280/280** test (test_pricelist_backlog 10 + test_project_episodes 7 + test_ai_quote_line_detail 8). Backlog Matteo COMPLETO.

**Prossimo**: push tutti i commit (.147→.157) + ZIP quando Matteo OK; restart :8000 (currency backend + auto-migrate Invoice/Project).

### α.172.156 ✅ — Conversione valuta completa (vedi sotto)

### α.172.155–156 ✅ (CONVERSIONE VALUTA COMPLETA — feature grossa, subagent-driven 12 task TDD)
Modello **base-anchored**: importi DB in valuta base (EUR); conversione $/£/CHF **live indicativa** su quote + **congelata all'emissione** su fattura (tasso BCE del giorno, art.13 c.4 DPR 633/72). XML SDI sempre EUR. Verifica legale conforme. Spec+piano in `docs/superpowers/`.
- Nuovo `currency.py` (to_display/to_base/symbol/format_money/disclaimer/freeze_invoice_fx) + `fx.get_fx_rate_on` (BCE storico). Quote: `currency_block` payload + 422 tasso assente + riga prezzo→base (`from_listino`). UI: card valuta + `mfFormatMoney`. PDF quote+fattura convertiti + disclaimer. Invoice: 3 colonne nuove + auto-migrate + freeze a tutti i siti Invoice() + NC copia tasso. SDI verificato EUR. Settings EUR/USD/GBP/CHF. Migrazione precondizione eseguita.
- **255/255** test. E2E: quote USD → tasso live 0.859 → riga 1000 USD = 858.81 base. ✅
- **Restart :8000 necessario** (Matteo) per attivare backend + auto-migrate colonne Invoice.

**Backlog Matteo ancora aperto** (dopo valuta): listino (duplica voce, vista categorie troncata, cancellazione rotta), quote (dettaglio AI vuoto), progetti (n° episodi serie + copilot), copilot (nuova conv mostra chat precedente), source-map lucide. Vedi messaggio Matteo 31 mag.

**Prossimo**: push tutti i commit (.147→.156) + ZIP quando Matteo OK; restart :8000; poi backlog quick-fix.

### α.172.154 ✅ — conversione qty/prezzo trn su cambio unità (vedi sotto)

### α.172.154 ✅ (conversione qty/prezzo anche per trn — bug Matteo)
`saveLineField` (quotes.html, cambio unità inline riga salvata) era hardcoded day↔hr (`factor=HOURS_PER_DAY`) → trn non convertiva qty+prezzo. Generalizzato via `HOURS_PER_UNIT_JS`: factor=ore(old)/ore(new), qty*=factor, price/=factor, totale invariato. Copre day↔trn↔hr + legacy turno; non-temporali nessuna conversione. Solo template (hard refresh). NB: 2 conversioni JS distinte — `convertPriceOnUnitChange` (add-line, solo prezzo, già generalizzato .151) e `saveLineField` (inline riga salvata, qty+prezzo, .154).

**Prossimo**: push commit .147-.154 + ZIP quando Matteo OK.

### α.172.153 ✅ — label unità "trn 3h" (vedi sotto)

### α.172.153 ✅ (label "trn 3h" — richiesta Matteo)
4 dropdown ora `value="trn"` + label "trn 3h" (era value="turno"/"turno (3h)"). `trn` già canonico in tutto il backend; "turno" resta alias retrocompat (inline edit preseleziona trn anche su legacy "turno"). Solo template → hard refresh, no restart. Server :8000 ora gira .152 (riavviato da Matteo) → auto-reload serve .153 template; codice Python resta .152 fino a prossimo restart (irrilevante: trn già supportato in .151).

**Prossimo**: push commit .147-.153 + ZIP quando Matteo OK.

### α.172.152 ✅ — "turno" nei dropdown mancanti (vedi sotto)

### α.172.152 ✅ (turno nei dropdown rimasti — follow-up Matteo)
.151 aveva coperto solo pannello add-line (#al-unit) + pricelist (#it-unit). Aggiunti: /quotes select **inline edit riga** (L2252, JS-built) + `_lineNature` JS time-list + /job_detail `#ex-unit`. NB: template auto_reload in dev → opzioni visibili con hard refresh; logica turno=3h richiede **restart server** (l'istanza :8000 girava ancora α.172.72 — template freschi, Python vecchio).

**Prossimo**: restart server :8000 (carica backend .152) + push commit .147-.152 + ZIP quando Matteo OK.

### α.172.151 ✅ — nuova unità "turno" = 3 ore (vedi sotto)

### α.172.151 ✅ (unità "turno" = 3 ore — richiesta Matteo)
Generica (utile a Suono). Source of truth `cost_line_sync.HOURS_PER_UNIT` + `hours_per_unit()`: turno/turni/trn/shift=3.0. `_qty_from_hours`/`is_time_based_unit`/`_UNIT_TO_NATURE` derivano dalla mappa. Dedup conversioni: `reverse_quote` + `cost_report` (OT pending) ora usano `hours_per_unit()` (prima day/else hardcoded → turno=1h errato). UI: option "turno (3h)" in /pricelist+/quotes, badge+conversione prezzo JS (`HOURS_PER_UNIT_JS`). AI: enum/validazione/docs. Cleanup terminologico: copy "turno"(=8h giornata) → "giornata". 27 test → **217/217**. JS servito node --check OK.

**Prossimo**: push 6 commit (.146→.151 → in realtà .147-.151) + ZIP quando Matteo OK · test copilot Gomorra lato Matteo.

### α.172.150 ✅ (reparti + prezzi Deliveries — richiesta Matteo)
66 voci-bucket cat "Deliveries" (erano dept+prezzo None): AUDIO→Suono(3) 19 voci, VIDEO+SOTTOTITOLI+altro(KDM/ISO/Document)→DI(1) 47 voci. Prezzi 3 livelli (mastering/delivery fee, no grading/mix): DCP 2K 1200/4K 1800, IMF 1500, MXF HD 450/UHD 700, MP4 180, ProRes 422 350/422UHD 550/4444 750/XQ 900, ImgSeq 900, SD 250, Subtitle 120, KDM 80, ISO 150, Document 0; FullMix 600, stem 250, M&E 450, StemsBundle 700, OptAudio 350, DM&E 18/min. Script `scripts/migrate_deliveries_pricing.py` idempotente + 29 test. Snapshot pre-apply salvato. 190/190.

**Prossimo**: push 4 commit (.147-.150) + ZIP quando Matteo OK · test copilot Gomorra lato Matteo.

### α.172.149 ✅ (sweep datetime.utcnow → now_utc)
Chiuso debito `datetime.utcnow` ×111 (deprecato). Helper `app/services/clock.py` → `now_utc()` = `datetime.now(UTC).replace(tzinfo=None)` (naive, semantica identica, no cicli con models). 45 file (39 sweep + 6 alias locali), import via AST. 0 call-site residui (solo docstring clock.py). Warning 1362→15. **161/161**.
Debito #3 residuo (scelta Matteo/beta): rebuild UNIQUE composito DB esistente · `delivery_portals.py` orphan.

**Prossimo**: test copilot Gomorra lato Matteo (server suo, fix α.146 live) · eventuale push 3 commit (.147/.148/.149) · valutare delivery_portals da cablare.

### α.172.148 ✅ (test estensivi fasi 7-12 + regressione anomaly cascade)
Verifica E2E (API/curl, server :8770 su snapshot lavoro). **161/161** test (+3).
- **F7 pass-through OT** ✓ toggle weighted ON/OFF (PUT cost-report).
- **F10 anomaly reopen cascade** ✓ + 3 test regressione (`test_anomaly_reopen_cascade.py`): LossEntry hard-delete, OverheadCost soft-delete, reopen-open noop. Live N/A (0 anomalie sul DB).
- **F11 HARD-BLOCK** ✓ schedule Σpct>100% → 409 (110%); AP>budget → 409 (110.9%).
- **F9 filmografia** pagina 200; AI call = key Matteo (live).
- **Smoke 11 pagine**: zero 500. DB lavoro senza residui.
**Debito #3 ancora aperto**: `datetime.utcnow` ×111 (1362 warn deprecation — proposto helper `now_utc()` naive, DECISIONE Matteo) · rebuild UNIQUE composito DB esistente · `delivery_portals.py` orphan.

**Prossimo**: decisione utcnow sweep + test copilot Gomorra lato Matteo (server suo).

### α.172.147 ✅ (chiusura gap audit TPN/DAM P1)
5 gap P1 TPN/DAM (debito beta, fixati ora: sicurezza + basso rischio). **158/158** test (+12).
- **#1 metadata/delivery-info no-auth** (`dam.py`): i 2 GET filtravano solo tenant+exists → leak codec/res/durata+delivery di asset altrui. Ora `user_can_access_asset()`+log deny+`request:Request`.
- **#2 MFA upload/delete**: check `check_project_mfa_required` era solo download → esteso a upload+delete.
- **#3 secure-delete default**: `DELETE` ora `secure=1` (DOD 3-pass). `?secure=0` opt-out.
- **#4 watermark PDF**: nuovo `apply_watermark_pdf()` (PyMuPDF) su ogni pagina; branch PDF in `download_asset`, forzato non-admin. Video/DCP fuori scope (gated+loggati).
- **#5 uploaded_by spoof**: derivato da utente autenticato (era Form falsificabile); risolve TODO hardcoded `uploaded_by=1` in dam.html.
Test: `tests/test_dam_tpn_audit.py`. Debito residuo beta: rebuild UNIQUE composito (DB esistente), `datetime.utcnow` ×111 (deprecation, helper centralizzabile), `delivery_portals.py` orphan (feature roadmap).

**Prossimo**: test estensivi fasi 7-12 (pivot API/curl) + eventuali fix.

### α.172.146 ✅ (fix quote/picker capitolato + copilot — note analisi quotazioni Matteo)
**Picker/quote**: Bug1 detail riga eredita da PriceItem.description · Bug2 `template_bucket_options` detail ricco (specs+nomi+note, era solo note→vuoto) · Bug3a dedup per (voce+capitolato) non più solo price_item_id (voce da capitolato diverso ora aggiunta) · Bug3b `section_label`=broadcaster capitolato (Sky vs NBCU non confondibili). Verificato live su Fremantle/Vision (pid 58 in 2 righe etichettate distinte, 21/21 bucket con detail).
**Copilot hardening**: truncation max_tokens 2000/4000→8000 (blocchi propose_quote tagliati) · `_coerce_price` robusto + reject id-like + messaggio rinforzato (price_list confuso come PK) · `tavily_search` timeout+depth basic+errore visibile (web_search hang). Schema α.172.141 già ok, qui difesa server-side.
15 test nuovi → **146/146**. DB ripristinato da snapshot (quote PICKER TEST rimossa).

### α.172.145 ✅ (fix numerazione quote + test estensivo flusso finance)
**Bug** (trovato in test estensivo): nuova quote riusava base progressivo già attivo (`008-v1` mentre `008-v2` attivo) perché il contatore `NumberingConfig.current_seq` diverge dal max reale (versioning/snapshot non lo bumpano) + la check guardava solo la stringa esatta `-v1` (libera causa bin). Fix `_next_quote_number_progressive`: rileva collisione sul BASE tra quote attive → fallback scan autoritativo. 3 test → **132/132**.
**Flusso finance verificato E2E via API** (Playwright MCP instabile → pivot curl): A validazione P.IVA 422 + cliente ✓ · B progetto (esercita fix batch-B client_id) ✓ · C quote imponibile 3350→IVA 737→tot 4087 ✓ · D approva→job auto ✓ · E cost report Quotato 3350 ✓ · F acconto 1005→IVA 221.10→tot 1226.10 (Decimal HALF_UP ✓) · G SDI XML FatturaPA valido (SDI 7-char, TD01, importi coerenti) ✓. DB ripristinato da snapshot pre-test (entità TEST-AUDIT rimosse).

### α.172.144 ✅ (fix cosmetici audit UI)
3 finding P3 chiusi (verificati curl/browser): `/jobs` nudo → redirect a `/cost-report` (era 404 JSON); titolo tab `/projects/{id}` = `{code} · {title} — Claqo` (era generico); `/favicon.ico` → redirect 301 a icona SVG (era 404 ogni pagina). NON fixati per scelta: casing clienti AI (title-case romperebbe RAI/A24), identità MediaFlow/Claqo (rebrand). 129/129 test.

### α.172.143 ✅ (export/import capitolati ZIP + multiselect + audit UI)
- **Feature**: `GET /delivery-templates/api/export-zip?ids=` (ZIP multi-template + manifest) + `POST /api/import-zip` (conflict→`-IMP`, no overwrite). UI: colonna checkbox + select-all + topbar "📦 Esporta ZIP (n)"/"📥 Importa ZIP". NO DeliveryItem nello ZIP (FK taxonomy non portabili). 5 test → **129/129**. Verificato E2E + browser.
- **Audit UI Playwright** (19 pagine + flussi): **zero errori JS**. Fix: export double-fire→fetch+blob (1 req); login hint @Claqo.it→@mediaflow.it; /resources money IT (€ 1.800); emittente ellipsis+tooltip. Tutti verificati in browser.
- **Backlog audit (P3/cosmesi)**: /jobs bare 404 JSON, titolo tab project generico, favicon.ico probe 404, casing clienti AI-enrich, identità mista MediaFlow/Claqo (rebrand).
- **Decisione API leak**: Matteo OK a non ruotare ora (repo private, 1 collaboratore, $15 cap). **Reset completo key in fase beta** [[project_session_30mag2026_multiaudit]].

**Prossimo**: ripresa test estensivi (piano pre-audit) + eventuale browser-test di import-ZIP reale da parte di Matteo.

### α.172.142 ✅ (multiaudit fix batch A→E)
Esito audit multi-agent (8 dimensioni, finder+verifier adversarial). Single-tenant alpha → cross-tenant = debito beta, non exploit live; fixati ora perché economici.
- **A igiene segreti**: cancellato `.env.backup` (key in chiaro) + `.gitignore` pattern backup. ⚠️ **MATTEO: ruota ANTHROPIC + TAVILY key** (erano su disco).
- **B cross-tenant+gate**: 3 endpoint `cost_report` (weighted-revenue/reconcile-actuals/reconcile-all) → `RequireEditCostLines` + `scoped()`. `projects.create_project` valida `client_id` (fetch_or_404) + tenant_id esplicito. Modelli `Project/Job.code` + `Quote.number` → UNIQUE composito (tenant_id,..). 6 indici FK. `scripts/migrate_tenant_unique.py` (indici SAFE eseguiti; rebuild UNIQUE gated `--rebuild-unique`, prerequisito beta NON eseguito).
- **C auth**: `config.assert_production_security()` boot-guard fail-closed (prod + auth_required=False/secret debole/no ai_key → RuntimeError). No-op dev. In `main.lifespan`.
- **D finance**: invoice acconto float→Decimal HALF_UP (×2 path). SDI validator+xml accettano 6-char PA (era droppato a 0000000). `fx.convert` arrotonda. `quotes._resolve_item_unit_price` logga warning su price_list None (non più €0 silenzioso).
- **E test**: `tests/test_security_audit_fixes.py` 21 test. **124/124 pytest verde** (era 103).

**Debito documentato (post-60%)**: rebuild UNIQUE su DB esistente (beta), `datetime.utcnow()` ×110, gap TPN/DAM P1 (metadata no-auth-check, MFA upload/delete, secure-delete default, watermark non-image, uploaded_by spoof), orphan `delivery_portals.py` (feature roadmap da cablare).

**Prossimo**: test browser Matteo (3 endpoint cost_report con utente non-elevato → 403) + ripresa test estensivi (piano pre-audit).

### α.172.141 ✅ (fix schema tool AI: price_list non-id + unit enum)
Copilot si auto-confondeva creando voci listino: "price_list richiede il PK della price list?". Falso (price_list = prezzo numerico livello List, no FK). Root: `propose_price_item`/`propose_new_item_and_line` avevano `price_list` senza description + `unit` enum `["day","hour","flat"]` sbagliato (voci reali: `pc` 85×, `day`, `TB`, `hr`, `min`, `shot`, `allow`, `version`). Fix `ai_tools.py`: description esplicita su price_list + enum rimosso (stringa libera con esempi). Verificato load tools. **Restart server** (schema letto al boot provider).

### α.172.140 ✅ (3 richieste Matteo: UX copilot + quote)
**1 Auto-refresh post-azione AI (globale)**: `copilotApply` contratto `detail.handled` — pagine con refresh mirato (quotes/planning) settano `handled=true` (no reload, drawer aperto, dialogo continua); pagine senza listener → reload soft 700ms. Guard `moreWork` (no reload a metà batch multi-azione). **2 Validità quote default +14gg** in tutti i path (create_quote server fallback + `_h_propose_quote` AI + prefill UI + schema tool). **3 Numero quote auto da naming convention anche da /projects**: `create_quote.number` opzionale → `_next_quote_number_progressive()` se vuoto; project_detail prefilla via `/settings/api/numbering/quote/preview` (come /quotes). Verificato unit: autogen `Q-2026-009-v1`, +14gg. JS node-check + Jinja parse OK. **Test browser Matteo pendente** (item 1 reload + item 3 prefill).

### α.172.139 ✅ (hotfix: Copilot 500 su voci listino senza price_list)
Ogni messaggio Copilot con provider tool-use crashava 500 → frontend `JSON.parse: unexpected character at line 1 column 1` (plain-text `Internal Server Error` di Starlette, nessun exception handler custom in app/). Root cause: `ai_context.build_context()` formattava `€{it.price_list:.0f}` senza guardia None; le 66 voci-bucket della migrazione α.172.135 (211 DeliveryItem → 66 bucket) hanno `price_list=None` → `TypeError`. Prompt-indipendente (tutto il Copilot rotto, non solo "Crea Progetto"). Fix `ai_context.py:266`: `€n/d` per voci senza prezzo listino (non €0). Verificato repro diretto `build_system_prompt` → OK len=29080. **Test browser Matteo pendente.**

### α.172.138 ✅ (F3.2 booking file-type + F3.3 QC compare, pipeline F1+F2+F3 chiusa)
**F3.2**: booking modal planning mostra badge tipo file (package|container da spec_json) su ogni deliverable. Endpoint bookings/deliverables arricchito `file_type`+`delivery_item_name`. **F3.3 lazy bridge** (no Asset placeholder, scelta esplicita): `qc_specs_compare.build_expected()` (attese live da DeliveryItem: risoluzione/codec family/HDR/audio channel-count) + `compare_to_actual()` (report per-campo match/mismatch/unknown, codec fuzzy, audio multiset) + `run_deliverable_qc_compare()` salva in qc_report_json. Auto-run al link asset (non bloccante) + endpoint `POST /jobs/api/deliverables/{id}/qc-compare`. 6 test, 103/103. Smoke E2E OK (mismatch res+audio, match codec fuzzy).

**PIPELINE DELIVERABLES COMPLETA** (F1 listino bucket + F2 quote picker + F3 planning snapshot/booking/QC). Design in `docs/superpowers/specs/2026-05-29-deliverables-pipeline-design.md`. 4 commit locali NON pushati (53e4b1a, 42a833f + .138). **Prossimo**: push + ZIP export, poi test browser Matteo end-to-end (quote picker → convert job → planning badge → QC compare con file reale).

### α.172.137 ✅ (F3.1 pipeline, snapshot + smoke E2E)
`delivery_snapshot.snapshot_delivery_item()`: congela le specs risolte di un DeliveryItem (nomi taxonomy, video/audio_tracks/subtitle/timeline eredit./extra) in dict JSON. Wire in `jobs.py` create deliverable: `delivery_item_id` presente + no spec_json → auto-snapshot (decoupling capitolato, decisione 4). `DeliveryItem` aggiunto a `app/models/__init__`. Smoke E2E OK (spec_json 16 chiavi). 5 test nuovi, 97/97. **Prossimo: F3.2** booking modal mostra tipo file (container/package)+nome item del JobDeliverable collegato; **F3.3** asset bridge (conferma deliverable→nasce/collega Asset con specs "attese" da spec_json, QC confronta via `qc_expected_for_deliverable`).

### α.172.136 ✅ (F2 pipeline, quote picker + smoke E2E Playwright)
`delivery_bucket.template_bucket_options()`: voci-bucket distinte dai DeliveryItem del template (decisione 10) con prezzo+conteggio+note→detail. Endpoint `GET /quotes/api/template-buckets/{tid}` + `POST /quotes/api/{qid}/load-from-template-items` (aggiunge righe dal sottoinsieme spuntato, detail precompilato). UI `quotes.html`: bottone "🎯 Picker capitolato" + modal checkbox. Fix bug latente dropdown livello prezzo (`list_price`→`list`, 422 — anche vecchio `lt-level`). Smoke Playwright OK (Fremantle 21 bucket → add → righe corrette). 3 test nuovi, 92/92. **Prossimo: F3** (planning JobDeliverable snapshot in spec_json + Asset atteso + booking modal).

### α.172.135 ✅ (F1 pipeline Capitolato→Listino, TDD)
Service `app/services/delivery_bucket.py`: `compute_bucket()` riduce un DeliveryItem a voce-bucket GENERICA per media_kind (video=package|container+codec+res+HDR · audio=mix_type+channel da traccia primaria · sidecar=tipo container). `match_or_create_bucket()` trova-o-crea PriceItem in categoria "Deliveries", link via `suggested_price_item_id` riusato (decisione 9, no colonna nuova). Migrazione B `scripts/migrate_deliveries_buckets.py` (--dry): **211 DeliveryItem → 66 bucket** (riuso 3.2x), 13 voci legacy soft-deprecate, idempotente. 11 test nuovi, 89/89 green. Snapshot `db_snapshots/snapshot-3.5.0-alpha.172.135-pre-bucket-migration.db`. Design completo (decisioni 1-11) in `docs/superpowers/specs/2026-05-29-deliverables-pipeline-design.md`.

**Prossimo**: F2 quote picker a spunte (endpoint voci-bucket derivate dai DeliveryItem del template + UI → righe con `detail` per specs capitolato, migliora `load-from-template`). Poi F3 planning affinamento JobDeliverable + Asset atteso + booking modal.

### α.172.128 ✅ (feature subagent-driven) — Estrazione capitolati via vision: corpus popolato

### α.172.128 ✅ (feature subagent-driven, 8 task TDD + eval gate, branch feat/capitolato-head-extraction)
Pipeline estrazione TC/timeline/audio-config dai capitolati via **vision** (PyMuPDF PDF→immagini, risolve il limite pypdf sulle tabelle audio). `render_document_for_llm` + `extract_head_specs` (vocab canonico iniettato, legge tabella+legenda) + `reconcile_taxonomy_aliases` (M&E=IT mix=IT, guard anti-hallucination) + `apply_head_specs` (idempotente upsert). `ClaudeProvider.chat` auto-stream >16K (fix troncamento). Endpoint extract-head/apply-head + bottone UI preview/Applica + batch script.
**Corpus popolato**: 97 AudioConfigPreset su 11 broadcaster (RAI 28 con 8T07/16T09 verificati vs tabella+legenda, MUBI 16, Sky 15, NBCU 13, PIPERFILM 8…) + TC start + timeline. 78/78 pytest.

**Follow-up**: (1) aggiungere a mano suggested_taxonomy residue per template (`/settings/delivery-taxonomy`); (2) assegnazione audio_config_code→item via dropdown; (3) **update modelli DeepSeek** (v4-flash/v4-pro + pricing + retrocompat, da api-docs.deepseek.com) prossimo round — DeepSeek text-only, vision resta su Claude; (4) merge branch→main.

### α.172.127 ✅ — Timeline / TC start / Audio config sui delivery item

### α.172.127 ✅ (feature subagent-driven, 9 task TDD, branch feat/delivery-timeline-audioconfig)
Catturati in forma strutturata i dettagli tecnici dei capitolati prima persi: **TC start** (Vision 00:59:59:00), **timeline/testa** (barre+toni, slate, counter RAI, nero, rulli DCP via segmenti con kind/tc/reel/source), **codici audio d'emittente** (RAI 8T07/16T09 → tabella `AudioConfigPreset` legata al template che materializza le `AudioTrackSpec`). Default su template + override su item (`effective_timeline` con eredità). QC riceve `qc_expected`. Parser pass2 esteso. UI sezione "⏱ Timeline & TC" nel modal item. Migrazione idempotente + backfill TC pulito (regex, prosa scartata). 65/65 pytest. Spec+piano in `docs/superpowers/`.

**Follow-up**: re-parse LLM per-item (serve API key, bottone "🤖 Estrai items"); auto-checklist QC; AI capability propose_audio_config_preset. Da fare: merge branch→main + push. Restano punti #1 (test browser E2E) e #3 (AI match listino batch) della sessione precedente.

### α.172.126 ✅ — Container taxonomy non-AV: fix 21 falsi positivi MISSING_CONTAINER

### α.172.126 ✅ (punto #2 "Prossima sessione" chiuso)
8 nuovi Container preset (Subtitle EBU-STL/SRT/TTML-IMSC/SCC/WebVTT + KDM + ISO + Document) con `media_kind` dedicati. Backfill signal-driven riassegna i 20 item containerless (subtitle/KDM/ISO/doc). Validazione corpus 211 item: **22→2 issue** (i 2 residui sono finding veri: J2K_REQUIRES_MXF id=69, IMGSEQ_NO_AUDIO id=173). R9 invariato, scelta "taxonomy estesa" vs allentare la regola. File: `scripts/migrate_delivery_taxonomy.py`.

**Restano punti #1 (test browser E2E — lato Matteo) e #3 (AI match listino batch 211 item → suggested_price_item_id).**

### α.172.125 ✅
**Fix 500 su /delivery-templates** diagnosticato a fondo: NON era un bug di codice ma 10 server zombie su :8000 (OneDrive rompe il reload-watcher di uvicorn → restart manuali accumulano processi; SO_REUSEADDR Windows → un vecchio .116 rispondeva, template .124 → Jinja UndefinedError su `stats`/`show_inactive`). Fix: kill di tutti i python + relaunch pulito.
Inoltre: (1) rimosso `from pathlib import Path` locale nel lifespan che faceva crashare in silenzio 3 backfill JCL (Path diventava variabile locale per tutto lo scope); (2) `avvia_muto.bat` ora killa i listener su :8000 prima di avviare → niente più zombie.

### α.172.124 ✅
`GET /delivery-templates/api/list` default `is_active=True`. I 3 template soft-deleted (Gomorrah/NBCU id=10/11) non compaiono più nelle dropdown cascading job/quote/planning/project + Diff. Tabella admin invariata (server-rendered con `show_inactive`). Nessun fix frontend, nessuna migrazione DB.



### Tier 3 Bundle B+C+D ✅
**B (T3.4+T3.8)**: validation cross-tier su 9 regole + endpoint `validate` + endpoint `revalidate-ai` (re-mapping LLM FK preservando text). UI bottoni 🔎 Valida + 🤖 Rivalida AI nel modal item. Corpus reale 22/211 items con issue (21 MISSING_CONTAINER su subtitle/KDM/ISO).

**C (T3.6)**: AI ranking top 3 PriceItem candidati per linking `suggested_price_item_id`. Service con LLM + fallback heuristic overlap. UI bottone 🔍 Match listino + popup confidence color-coded cliccabile.

**D (T3.3+T3.5)**: endpoint `/delivery-items/api/search` con 4 filtri (q/package/resolution/hdr) + endpoint `/delivery-templates/api/diff` strutturato blocchi + items. UI 2 bottoni topbar (Cerca items + Diff template) con modal dedicati.

Tutti file modificati: `delivery_item_validation.py` + `delivery_item_pricelist_match.py` (nuovi services) + `delivery_items.py` (+4 endpoint) + `delivery_templates.html` (+5 funzioni JS, +3 modal). Nessuna migrazione DB.

### Tier 3 Bundle A ✅ (α.172.120, T3.1+T3.2+T3.7)
Stats panel + toolbar filtri + toggle inattivi + colonna Items.

### Soft-delete Gomorrah ✅
2 template istanze compilate (NBCU-UHD-HDR10-LONGFORM id=10 1 item, NBCU-LONGFORM-UHD-V1.3_TECHO id=11 2 items) marcati `is_active=False`. Description con nota "istanza compilata, vedi NBCU-LONGFORM-UHD generico". Items preservati per traceability.

**Corpus finale: 11 capitolati referenza attivi = 208 DeliveryItem attivi (+ EXAMPLE-THEATRICAL seed vuoto).**

### PIPERFILM parser fix ✅ (α.172.118)
- Root cause: output troncato a 16K + SDK Anthropic rifiuta non-streaming oltre 10 min.
- Fix: `ClaudeProvider.complete()` auto-stream se `max_tokens>16000` + bump pass2 32K.
- Risultato: **31 items PIPERFILM in 217s**. Batch 13/13 = **211 items totali** (208 attivi + 3 soft-deleted).

### Rename rapido delivery template ✅ (α.172.117)
Bottone `✏️` riga tabella `/delivery-templates` → 2 prompt (nome + code) → PUT con name/code → reload. Pattern data-attribute (no JSON.stringify in onclick). Backend `update_template()` già accettava i campi.

### Stato batch Tier 2.4 ✅ chiuso 13/13

Batch `scripts/batch_extract_items.py` parser v2: **13/13 OK = 211 DeliveryItem** + AudioTrackSpec ricchi. PIPERFILM recuperato α.172.118 (vedi sopra).

| # | Template | Items | Tempo |
|---|---|---:|---:|
| 1 | RAI-SDHDUHD-1.4 | 24 | 159s |
| 2 | GTM-DELIVERY | 3 | 39s |
| 3 | FREMANTLE-DCP-ITA-THEATRICAL | 35 | 192s |
| 4 | MUBI-FEATURE-DELIVERY | 25 | ~90s |
| 5 | NBCUNI-AUDIO-51 | 17 | ~60s |
| 6 | SKY-ITA-AV-DELIVERY | 7 | — |
| 7 | NBCU-TECHOPS-LONGFORM-2.8 | 10 | — |
| 8 | NBCU-LONGFORM-UHD | 7 | — |
| 9 | NBCU-UHD-HDR10-LONGFORM | 1 | 32s |
| 10 | NBCU-LONGFORM-UHD-V1.3_TECHO | 2 | 35s |
| 11 | VISION-DIST-IT | 29 | 177s |
| 12 | A24-QUEER-DELIVERY | 20 | 166s |
| 13 | **PIPERFILM-DELIVERY** | **31** | 217s (α.172.118) |

**PIPERFILM recuperato** α.172.118 con fix streaming + max_tokens 32K.

**NBCU-UHD-HDR10-LONGFORM 1 item**: sospetto sottoestrazione, verificare nel template sorgente se davvero ha solo 1 deliverable rispetto agli altri NBCU.

### Riepilogo Tier 1+2 chiuso

| Tier | Stato | Commit |
|---|---|---|
| 1 schema 11 modelli + seed 135 + parser 2-pass | ✅ | a96e9c8 |
| 2.1 router DeliveryItem | ✅ | c9f691e |
| 2.2 UI tabs Items in /delivery-templates | ✅ | c9f691e |
| 2.3 admin /settings/delivery-taxonomy + CRUD | ✅ | 9b2b1bf |
| 2.4 batch re-parse 13 templates | ✅ 13/13 = 211 items | α.172.118 |
| 2.5 JobDeliverable.delivery_item_id FK + UI cascading | ✅ | 9b2b1bf |

Tutti commit pushati su origin/main.

### Backlog originale Matteo /delivery-templates

1. ✅ Tech specs delivery dropdown → CHIUSO (taxonomy 135 record + UI tab Items + modal editor con dropdown α.172.114)
2. ✅ Parser batch 17 capitolati → CHIUSO α.172.111 (legacy JSON 8-block) + Tier 2.4 chiuso 13/13 = 211 items α.172.118
3. ✅ Rename template → CHIUSO α.172.117 (bottone ✏️ inline)
4. ✅ Modal dettaglio human-readable + edit no-JSON → CHIUSO α.172.112
5. ✅ Modal Aggiungi delivery cascading template→item → CHIUSO α.172.115/116

**Backlog originale 100% chiuso.**

### Prossima sessione

1. Test browser end-to-end (porta 8000 zombie Win — restart manuale `avvia_muto.bat`):
   - `/delivery-templates` → topbar (🔍 Cerca items, ⚖ Diff template), stats panel + filtri + toggle inattivi, rename ✏️
   - modal item editor → 🔎 Valida, 🤖 Rivalida AI, 🔍 Match listino
   - `/settings/delivery-taxonomy` → CRUD entity taxonomy
   - `/jobs/{id}` → modal Nuovo deliverable cascading
2. Affinamento MISSING_CONTAINER: troppo stringente per subtitle/KDM/ISO (21 falsi positivi). Opzioni: aggiungere container "subtitle text" / "encryption key" / "optical disc" alla taxonomy seed, OPPURE down severity a "warning" se subtitle_format/notes contengono pattern.
3. AI matching listino in batch su tutti i 211 items per pre-popolare `suggested_price_item_id` (ora vuoto su tutti). ~30-60 min Claude.

---

**v3.5.0-alpha.172.114** — 28 maggio 2026 — Tier 2.1+2.2: router DeliveryItem + UI tabs Items

Router REST per DeliveryItem + AudioTrackSpec con tenant_scope + permission gate. Endpoint `/delivery-taxonomy/api` per dropdown UI. Endpoint `/delivery-templates/api/{tid}/items/ai-extract` per re-parsing capitolato sorgente con materialize_items().

Modal dettaglio `/delivery-templates` riscritto a 3 tab: Specs blocchi (legacy) / Items (nuovo) / Voci listino. Pane Items con card summary visuale (📦 Package · 🎞 Container · 🎬 VideoCodec · 📐 Resolution · ⏱ FPS · 🔊 N tracks), bottone "🤖 Estrai items via AI" (≈30-90s Claude), bottone "+ Aggiungi item" manuale. Modal editor item con dropdown taxonomy. Modal editor audio track inline sovrapposto.

DB: 14 templates, 0 DeliveryItem (Tier 2.4 popolerà via re-parse batch).

### Prossima sessione — Tier 2 step rimanenti

3. Tier 2.3 — Admin UI taxonomy CRUD + import/export JSON cross-tenant
4. Tier 2.4 — Re-parse 13 templates esistenti con parser v2 (~25-30 min Claude)
5. Tier 2.5 — JobDeliverable.delivery_item_id FK + UI Nuovo Deliverable cascading

Per testare già Tier 2.2: apri https://parker-mining-ahead-infringement.trycloudflare.com/delivery-templates, clicca un template (es. MUBI id=5), tab "📦 Items (0)", bottone "🤖 Estrai items via AI" → attesa ~90s → 25 items appaiono.

### Backlog originale Matteo /delivery-templates

1. ✅ Tech sheet delivery: opzioni dropdown manuali → CHIUSO via taxonomy 135 record (Tier 1 α.172.113)
2. ✅ Batch parse 17 capitolati → CHIUSO α.172.111 (13 templates JSON 8-block legacy)
3. Capitolati: rename template → TODO Tier 2
4. ✅ Modal dettaglio human-readable + edit form (no JSON) → CHIUSO α.172.112
5. Modal Aggiungi delivery items (cascading template→item) → TODO Tier 2

---

**v3.5.0-alpha.172.112** — 28 maggio 2026 — Modal dettaglio template human-readable + edit form (no JSON)

Rifatto modal /delivery-templates da JSON raw a editor human-readable con 3 livelli: header editabile (code/name/broadcaster/version/description) + 8 blocchi capitolato con form dinamico per-tipo (string/number/bool/array/nested object ricorsivo) + bottoni add/edit/remove field. PUT salva tutto in singolo call.

---

**v3.5.0-alpha.172.111** — 28 maggio 2026 — Batch parse 17 capitolati: 13 templates salvati

Prima esecuzione completa del parsing AI sui 17 capitolati esempio. **13 DeliveryTemplate creati** (id 2-14, conf media 0.79). Broadcaster coperti: RAI, GTM, Fremantle, MUBI, Sky/NBCU, Sky Italia, NBCU TechOps (3 variants UHD/HDR10), Vision, A24, PiperFilm.

Root cause precedente A24/IRDA "JSON malformato": `max_tokens=4000` troncava risposta Claude. Fix `deliverables_parser.py`: 4000 → 8000. Capitolati grossi (60+ righe JSON) ora parsano OK.

Tool nuovo `scripts/batch_parse_capitolati.py` standalone (bypass HTTP, --dry, --user-id, progress per-file, collision suffix auto).

4 errori non recuperabili senza intervento aggiuntivo:
- 2 .txt 0-byte (placeholder vuoti in repo)
- BETA FILM PDF image-only (serve OCR)
- Veterans .doc legacy (serve antiword/libreoffice)

### Backlog UX delivery_templates rimanente

1. Tech sheet: aggiungere selezione manuale opzioni via lista (oltre input AI).
2. ✅ Capitolati: parsing iniziale sui 17 — CHIUSO α.172.111.
3. Capitolati: aggiungere rename template di consegna.
4. Modal dettaglio template: rifare human-readable + edit form (no JSON raw).
5. Modal "Aggiungi specifiche delivery a progetto": scelta file estrapolato + nome custom + modifica manuale + togli edit JSON + note.

### Prossima sessione

(4) modal dettaglio template human-readable + edit form (no JSON raw). Pre-requisito per (3) rename e (5) wizard delivery.

---

**v3.5.0-alpha.172.110** — 28 maggio 2026 — Fix parse-sample 503 cieco + /pricelist/api 404

Hotfix duplice sul flusso `/delivery-templates` parsing capitolato AI segnalato da Matteo.

- `BaseProvider.extract_json` salva diagnosi reale in `last_extract_diag` (stage `complete` vs `parse`, error msg, raw preview). Stop al silent-swallow exception.
- Endpoint `parse-sample` legge la diagnosi e propaga messaggio user-friendly specifico per cause (rate-limit/API key/model id/JSON malformato).
- Fix UI 404: `delivery_templates.html:416` `/pricelist/api` → `/pricelist/api/items`.
- Audit 17 capitolati esempio: 14 estraibili OK, 3 degenerati (2 .txt 0-byte + 1 PDF image-only); endpoint sample-files già filtra i 2 .txt vuoti.

### Backlog UX delivery_templates (richieste Matteo non ancora aperte)

1. Tech sheet: aggiungere selezione manuale opzioni via lista (oltre input AI).
2. Capitolati: parsing iniziale sui 17 capitolati esempio (batch).
3. Capitolati: aggiungere rename template di consegna.
4. Modal dettaglio template: rifare human-readable + edit form (no JSON raw).
5. Modal "Aggiungi specifiche delivery a progetto": scelta file estrapolato + nome custom delivery + modifica manuale specifiche + togli edit JSON + note.

### Prossima sessione

Apri (2) parse batch capitolati su corpus. Poi (4) modal template human-readable. Poi (5) wizard delivery enriched.

---

**v3.5.0-alpha.172.109** — 28 maggio 2026 — i18n round 3: scrutinio approfondito, audit 477→15

Lavoro su tre fronti per chiudere il gap i18n residuo: tool `i18n_audit.py` migliorato (filtri false positive CSS hex/JS template literal/expressions/data-* + AUTO_SWAP coverage check), dictionary `MF_I18N` espanso +43 entries 5 lingue per frasi contestuali lunghe (settings CCNL/SDI/branding, copilot drawer, quotes anchor/currency, finance NC TD04, pricelist €/Giorno/Ora, resources override, planning, project_detail, finance_reports, holidays, hr, overhead, physical_assets, platform_tenants, portal_project), annotazione `data-i18n` in 15 template + `copilot.js` con `mfT()` per JS strings.

Risultato finale audit: 477 → **15**. Dei 15 residui: 7 manuale.html (doc utente, scelta), 6 falsi positivi tool (espressioni JS, CSS inline), 2 esempi placeholder. **0 stringhe UI vere da tradurre**.

Coverage totale i18n: 575 chiavi `MF_I18N` + 80 `MF_I18N_AUTO_SWAP` = **655 stringhe** tradotte 5 lingue.

### Prossima sessione

Test browser Matteo: switch lingua su `/settings`, `/quotes` (modal acconto), `/finance` (toggle annullate), `/pricelist` (tabs giorno/ora), `/resources` (modal override), `/planning` (modal bulk Fatto), `/hr`, `/holidays`, `/overhead`, `/finance-reports`. Verifica AUTO_SWAP runtime + nuovi data-i18n esplicit.

Bundle L Stack 2 prossimo milestone (era pre-α.172.99) si riprende dopo eventuali fix i18n + altri spunti utente.

---

**v3.5.0-alpha.172.98** — 28 maggio 2026 — Bundle L Stack 2 milestone 1/3: QC event-sourced foundation

Chiuso il foundation di Stack 2 (Bundle L QC event-sourced). Models `QCEvent` append-only + `QCReport` projection + 13 event types + service 11 funzioni + router 13 endpoint REST + sostituzione path Bundle I `update_deliverable` → delega allo stream eventi. Coerenza UI Bundle I preservata via projection sync diretta a `JobDeliverable.qc_substatus`.

Smoke E2E API verificato end-to-end (start → log err → pass → reopen → start v2).

### Prossima sessione

**Stack 2 milestone 2/3 (α.172.99)** — UI rich modal QC:
- Modal QC submit con timeline events loggabili (timecode + grade + canale + descrizione)
- Tab "Storia QC" per QCEvent stream completo
- Bottoni 6 esiti: Pass / Fail / Conditional / Reopen / Sign-off / Note
- Integrazione con `/planning` HUB (Bundle J)
- vis-timeline alternativo per visualizzazione QC rounds

**Stack 2 milestone 3/3 (α.172.100)** — Tests + edge cases:
- `tests/test_qc_events.py`: immutability listener, projection sync correctness, backfill idempotency, reopen flow, sign-off flow, qc_number progression, payload schema esempi.
- Integration test Bundle I cascade (`qc_failed` → `cascade_qc_reject`).
- Edge: multi-asset stream, qc_number monotonicity invariante.

**Push pendente**: α.172.97 + α.172.98 entrambi locali, push origin/main dopo test browser Matteo domani.

### Sessione 28 maggio — riepilogo

[Stack 2 milestone 1/3 sopra. Tasks 12-16 chiusi: models, listener immutability, service, router, backfill+auto-migrate. Tutti smoke API verdi. Server live su :8000.]

---

**v3.5.0-alpha.172.97** — 27 maggio 2026 sera — Folder-view quote + 5 fix sessione 27 mag

Cantiere folder-view chiuso. Lista `/quotes/` ora raggruppa per `base_code` con stacked status cards, accordion expand/collapse, filtri stato preservati. Tutte le quote nuove nascono con suffix `-v1`. 4 fix tecnici verificati end-to-end inclusi nel bundle.

### Sessione 27 maggio sera — riepilogo

**Cantiere folder-view `/quotes/`**:
- backend: helpers `with_v1_suffix` + `split_version_suffix` in `app/services/numbering.py`. Auto-backfill `-v1` al boot via `_auto_backfill_quote_v1_suffix` (lifespan, idempotente, silent no-op se DB già pulito). List endpoint ritorna `base_code` + `version_number` aggiuntivi.
- frontend: `renderQuotesList` riscritto. Folder header indaco con chevron + stacked status cards. Single-version → render piatto come prima. Multi-version → accordion (stato persistente in `localStorage`). Filtri stato a livello version, folder visibile se ≥1 matcha. Auto-expand quando filter nasconde righe + nota "X versioni nascoste".
- preview numbering: `/settings/api/numbering/quote/preview` ora ritorna `Q-2026-NNN-v1` per allineamento UI ↔ server.

**Fix tecnici già verificati API (sessione pomeriggio + sera):**
1. `_booking_billable_hours` smart_split → sum-per-resource (CR Dailies 144h→288h)
2. `next_progressive_code` max scan (collision Q-vN)
3. Bin-prefix Quote.number cestino + restore collision
4. Lista versioni inline in card "Stato & azioni"

**Guard versioning** (fix bug emerso durante test sessione 27 mag):
- Backend `PUT /quotes/api/{id}/status`: 409 HARD-BLOCK se quote ha parent approved+Job → forza l'uso di migrate-job.
- UI editor: bottone "Approvata" disabilitato + "Approva + crea Job" nascosto quando parent ha Job. Hint giallo "Usa Migra Job" sotto.
- Bug reale incontrato: approva diretta v2 → Job 3 duplicato (111 deliverable spawn-per-unit). DB attuale ha 2 Job su Q-2026-005 — pulizia rimandata a decisione Matteo.

**Fix UI minori sessione sera tardi (richiesta Matteo):**
- z-index `.topbar` 50→100 → popover theme/lang sopra `.al-side` listino flottante.
- Nuovo font scale switcher in topbar (🔍): 6 step 100→150%, `body { zoom }`, persistenza localStorage.mf_font_scale.

**Stato DB anomalia da risolvere** (Job duplicato Filmone):
- Q-2026-005-v1 (id=2) approved → Job 2 (Filmone-J005), ATTIVO (1 booking + 12 deliverable).
- Q-2026-005-v2 (id=9) approved → Job 3 (Filmone-J006), INATTIVO (0 booking, 111 deliverable spawn-per-unit, 0 timbrature).
- Opzione futura: eliminare Job 3 + JCL/JD cascade + downgrade v2 a draft → poi migrate-job pulito. Defer a richiesta esplicita.

### Smoke test post-commit eseguiti

- `/health` → 200 v3.5.0-alpha.172.97
- `/quotes/api?include_superseded=true` → 5 record, tutti con `base_code` + `version_number` popolati
- `/settings/api/numbering/quote/preview` → `Q-2026-008-v1` ✓
- `/quotes/api/1/duplicate` → 200 `{number: "Q-2026-007-v1"}` ✓
- `/quotes/api/1/new-version` → 200 `{number: "Q-2026-004-v3", version: 3}` ✓
- Auto-backfill `-v1` standalone run: 0 rinominate (DB già pulito da sessione precedente). Idempotente confermato.

### Test pendenti browser Matteo

1. Apri `/quotes/` (refresh forzato Ctrl+Shift+R per cache-buster) → verifica:
   - folder `Q-2026-004` (3 vers) collapsed con stacked cards `[Approvata][Bozza]`
   - folder `Q-2026-005` single row `[Approvata]`
   - folder `Q-2026-007` single row `[Bozza]` (creata da smoke duplicate)
2. Click chevron / badge `📐 N vers.` → expand/collapse + persistenza dopo refresh.
3. Filtro stato "Approvata" → folder `Q-2026-004` auto-expand con solo v1 visibile + nota "2 versioni nascoste". Folder `Q-2026-007` nascosto.
4. Crea nuova quote dal modal → verifica numero `Q-2026-009-v1` (preview ora include suffix).
5. New-version da v3 → produce `Q-2026-004-v4`.
6. Cleanup: cestina le quote di test (id=7, id=8) generate dallo smoke API se non servono.

Tunnel cloudflared: da rilanciare se Matteo accede da remoto. Server in locale: `python run.py` (auto-restart al primo edit).

### Prossima sessione — Stack 2 Bundle L (QC event-sourced)

Roadmap Bundle L (vedi α.172.96 STATO):
- ✅ Stack 1 Foundation chiusa (24 task, 532 routes)
- ⏳ **Stack 2** — QCEvent + QCReport tables append-only, replay state, integration con `qc_cascade` esistente Bundle I.

Decisioni Stack 2 (memory `project_stack2_qc_event_sourced_decisions.md`):
- A=per-asset granularity, B=event types enumerati, C=snapshot denorm sync con eventi, D=alimenta Bundle I (event→qc_substatus derivato).

Pre-requisiti: brainstorm/design dialogue prima di scrivere codice (cantiere strutturale → vale pattern Maestro).

Login dev: `admin@mediaflow.it / admin123`.

---

**v3.5.0-alpha.172.96** — 27 maggio 2026 — Bundle L Stack 1 CLOSE: foundation completa

Foundation cantiere strutturale Bundle L (tech specs unified Asset↔Deliverable↔QC). Modelli `VariantSchemaVersion` + `DeliveryVariant` con JSON Schema v1 validato, estensioni `JobDeliverable.variant_id` + `Asset.tech_specs_json`, refactor `asset_metadata.py` in `tech_specs_extractor` service estensibile (plugin registry, ffprobe + pillow), script batch `parse_capitolati.py` (--dry-run su 17 corpus → 200 stub variants), script `import_parsed_variants.py` con JSON Schema validation, router/UI `/delivery-variants` listing minimal, backfill Jaccard JobDeliverable.variant_id, sidebar link "📦 Variants".

**Coverage Stack 1**: 17/17 task (3 milestone α.172.94 + α.172.95 + α.172.96). 24 test pytest verdi. 532 routes (+5 da α.172.93). Auto-migrate idempotente al boot per DB esistenti.

### Sessione 27 maggio 2026 — riepilogo

**18 commit** (di cui 17 Bundle L Stack 1 + 1 cleanup ZIP), tutti su `main`, **non pushati**.

| Step | Commit | Cosa |
|------|--------|------|
| pre | 6ae830b | chore cleanup 69 ZIP export legacy |
| Task 4 | 561d60e | Asset.tech_specs columns |
| Task 5 | 1a8ef6d | JSON Schema v1 + validation tests |
| Task 5 fix | 61eea44 | canonical draft-07 metaschema URL |
| Task 6 | 249b5eb | variant_schema service loader + validator |
| Task 7 | cf2f4e0 | tech_specs_extractor ABC + registry |
| Task 7 fix | 933f63b | registry pollution + logger + tool setdefault |
| α.172.94 | 6b255f5 | Milestone 1/3 bump |
| Task 8 | 337cef5 | FFProbeExtractor port + auto-load |
| Task 9 | fb9ab32 | PillowExtractor immagini |
| Task 10 | 984652b | asset_metadata.py = wrapper legacy |
| Task 11 | 1a68f69 | auto-migrate + seed schema v1 al boot |
| Task 12 | f6572f0 | parse_capitolati.py batch + dry-run smoke |
| α.172.95 | 912e004 | Milestone 2/3 bump |
| Task 13 | ce0d09a | import_parsed_variants.py con validation |
| Task 14 | f96e653 | router /delivery-variants CRUD |
| Task 15 | 809907c | UI delivery_variants.html listing |
| Task 16 | 184a4b4 | backfill JobDeliverable.variant_id Jaccard |
| α.172.96 | (TBD) | Milestone 3/3 bump + sidebar + STATO + CHANGELOG |

### Stato dati DB sviluppo

- **DB attuale**: 8 ALTER applicate al boot α.172.95 (`job_deliverables` +4 col, `assets` +4 col, +1 INDEX).
- **VariantSchemaVersion v1**: seeded da `schemas/variant_v1.json`.
- **DeliveryVariant**: 1 sola test variant (`test-imf-it` creata in smoke Task 14). 200 stub generate da parse_capitolati.py NON ancora importate (sono in `docs/superpowers/specs/capitolati-parsed/` come JSON, schema reale rifiuterà la maggior parte — gli stub Task 12 hanno solo `code/name/category`, mancano `container.format` ecc).
- **Backfill match**: 0 JobDeliverable assegnati (test variant non ha keyword overlap con deliverable storici).

### Prossima sessione — Stack 2

**Roadmap Bundle L** (vedi design spec):
- ✅ Stack 1 — Foundation (modelli + extractor + parser)
- ⏳ **Stack 2 — QC event-sourced** (QCEvent + QCReport tables, append-only history, replay state, integration con esistente qc_cascade Bundle I)
- Stack 3 — ingest_qc_excel + export_qc_report (parser xlsx FbF + PDF/HTML export)
- Stack 4 — UI planning variant-aware + asset modal sezioni tipizzate (rich form auto-gen da JSON Schema)
- Stack 5 — Capability AI runtime `extract_capitolato_to_variants` (production path non-dry-run di parse_capitolati.py)

**Pre-requisiti riapertura Stack 2**:
- Push origin/main dei 18 commit (confermare con Matteo).
- Test E2E manuale `/delivery-variants/` su browser (Matteo).
- Popolare 2 file capitolato 0-byte (Amazon MGM + Netflix `.txt`) se possibile.
- Considerare OCR fallback per PDF scannerizzati (Beta Film) — defer Stack 5 piu' ragionevole.

**Bug aperti Bundle L Stack 1**: nessuno noto. CR/Planning/DAM/Jobs invariati (back-compat preservata via wrapper asset_metadata.py + opt-in variant_id NULL).

---

**v3.5.0-alpha.172.93** — 26 maggio 2026 — Bundle K1+K2+K3 (test plan giro 1) + hotfix critico Bundle J 500

Sessione test 26 mag. Aperta con bug 500 su `/jobs/api/deliverables/list` (typo `j.name` su `Job.title`) → hotfix immediato. Poi 3 richieste UX di Matteo durante test:

**K1**: filtri Planning sidebar ora switchano tra "planning" e "deliverables" view. Stato "job" rinominato → "stato booking" (BookingState canonico), applicato client-side (era passato come QS al backend incompatibile). Aggiunti 2 filtri Hub: Stato deliverable (5) + QC sub-status (4). Label "Da/A" → "Target da/a" in deliverables view. `renderDeliverableHub` ora passa querystring server-side al backend + filtra client-side multi-id/date/search.

**K2**: LTO/HDD/CRU/Blu-Ray/DVD/tape/shuttle/USB-drive → auto-`DeliverableNature.physical` (era sempre `digital` default). Helper `_infer_deliverable_nature` in `quotes.py` applicato in spawn quote→job + rebind quote. Backfill al boot (`_auto_reclassify_physical_deliverables`): 2 deliverable esistenti riclassificati al primo restart (matched 3 price_items lean preset).

**K3**: Cost Report card "Lavorazioni" ora ha switch `[€ | h]` (persistente localStorage). Mode hours mostra Quotate/Maturate/Over-Under in ore (factor day×8 per time-based). Drill risorsa click in "Ore booking per fascia" ora apre **lavorazioni** (JCL aggregate) invece di solo job. Endpoint nuovo `/cost-report/api/resource/{id}/cost-lines`.

527 routes (+1: cost_lines drill). Schema DB invariato. Cantiere L (tech specs unified) backloggato — snodo critico tra planning e asset mgmt, da affrontare con macrostruttura prima del dettaglio (capitolato Netflix come riferimento + ingest `FbF_QC-Report_Template.xlsx`).

**v3.5.0-alpha.172.92** — 25 maggio 2026 (notte) — Bundle H3: Asset Library metadata ffprobe + delivery linked

Pannello "Dettaglio asset" in `/dam` ora mostra (read-only): badge `AssetStatus` (planned/uploaded/rejected/accepted), deliverable linkati con status + qc_substatus + link a `/planning`, specifiche tecniche file estratte via ffprobe (Container/Video/Audio dettagliato). Fallback Pillow per immagini se ffprobe assente. Modal `showAssetDetail` refactor a DOM API (no più innerHTML).

526 routes (+2: `/dam/api/assets/{id}/metadata` + `/dam/api/assets/{id}/delivery-info`). Schema DB invariato. ffprobe esterno, assente OK fallback gentile.

**Sessione 25 maggio CONCLUSA — 4 bundle (I+J+H2+H3)**. Test live + report a domani 26 maggio.

**v3.5.0-alpha.172.91** — 25 maggio 2026 (sera-notte) — Bundle H2: Jobs page deliverable section READ-ONLY

`/jobs/{id}` allineato a nuovo enum Bundle I (5 status + qc_substatus). Kanban 5 colonne (era 4 legacy). Click card apre modal tech specs VIEW-only (`#modal-jd-specs`). Editing dei status/specs si fa solo da Planning HUB (Bundle J): link permanente in footer kanban + bottone "✏ Modifica in /planning" nel modal.

524 routes invariato. Schema DB invariato. Solo aggiornamento template + JS.

**v3.5.0-alpha.172.90** — 25 maggio 2026 (sera) — Bundle J: Planning HUB Deliverable + AI propose_specs

Tab `📦 Deliverable` in /planning come HUB centrale tenant-wide. Kanban 5 colonne draggable + Lista alternativa. Click card apre modal tech specs 8 blocchi con pre-fill da DeliveryTemplate + bottone AI che adatta le specifiche al deliverable specifico (es. template UHD generico → DCP IT JPEG2000).

524 routes (+2: `/jobs/api/deliverables/list` tenant-wide + `/ai/api/deliverables/{id}/propose-specs`). Schema DB invariato.

**Bundle I (α.172.89)** chiuso poco prima: stati nested Deliverable (5 main + qc_substatus) + cascade QC reject + auto-bump booking→deliverable + upload QC report PDF + AI propose_qc_report_summary. 2 colonne nuove (qc_substatus + assets.status) + 2 indici.

## Maratona 25 maggio 2026 — riepilogo bundle chiusi

- **α.172.76 — Bundle E**: log azioni permanente (`action_log.js`, Ctrl+Shift+L), verbose toggle, ring buffer 500 eventi localStorage, export JSON. Hook automatici in `toast()`/`toastBlock()`/`api()`. Settings tab Diagnostica.
- **α.172.77 — Bundle B**: smart_split AI con fallback policy default tenant (`_resolve_policy_for_resource` invece di check su `resource.working_hours_policy_id`). Fix booking AI single-slot 9-18 invece di 9-13+14-18.
- **α.172.78 — Bundle A**: `propose_bulk_split_booking` + `propose_bulk_delete_booking` (helper `_resolve_bookings_for_bulk` shared); fix `/pricelist/api` 404 → `/pricelist/api/items`; fix `itemsDS is not defined` esponendo `window._tlItemsDS` in renderTimeline.
- **α.172.79 — Bundle C**: auto-refresh timeline post-Apply AI (listener `mf:ai-action-applied` in planning.html mappa action_type → tlIncrementalRefresh/Remove), milestone align primo tentativo, sidebar nav ellipsis.
- **α.172.80 — Bundle D**: AI chat naming. PATCH `/api/conversations/{id}/title`, DELETE `/api/conversations/{id}`. Auto-title `<Project> · <msg40>`. UI rename + delete con icon button.
- **α.172.81 — Bundle F (P0)**: capitolato parse 500 → fix (provider per-utente iniettato nei 3 parser); smart_split manuale su edit booking (rimosso `!editingId`); milestone className `tl-milestone-group`; Ctrl+Z timeline capture phase; stato quote badge colorato in detail editor.
- **α.172.82 — F7+F8+F9**: AI quote naming convention (`gen_doc_code` invece di hardcode), milestone def-fix flex center, modalità progetti parent rows compact. **Regression timeline risorse**.
- **α.172.83 — Hotfix**: revert F8 milestone CSS + scope F9 `[data-group-by="project"]`.
- **α.172.84 — FLAT project mode**: rimosso `nestedGroups` da `tlBuildGroupsByProject`. Project header inline prefix nel label job.
- **α.172.85**: fix `AttributeError Client.code` (Client.name sanitizzato) + `run_in_threadpool` per AI parse (no event loop block).
- **α.172.86**: split parse + match capitolato in due endpoint per evitare cloudflare 524. Nuovo `POST /ai/api/deliverables/match` chiamato in background da UI Step 2.
- **α.172.87 — Bundle G1+G2**: DeepSeek AI provider (deepseek-chat V3 + deepseek-reasoner R1). Unit select width fix (min-width 70px, width:auto).
- **α.172.88 — Bundle H1**: anomaly warning booking single-type pairing. Helper `_classify_assignments_pairing` in planning.py + 422 SINGLE_TYPE_WARNING + auto-intercept in api() global.js con confirm + retry force_single_type=true.

## Prossima sessione

**Server**: lancia normale `python run.py`.

**Status Bundle I (α.172.89)**:
- ✅ Modelli (DeliverableStatus 5 valori, QCSubstatus, AssetStatus, NotificationKind.deliverable_qc_rejected)
- ✅ Migrazione legacy conservativa + auto-migrate al boot
- ✅ Service qc_cascade.py
- ✅ Endpoint update_deliverable esteso + nuovo close + nuovo qc-report upload
- ✅ Hook booking→deliverable auto-bump in_progress
- ✅ UI badge nested + 5 azioni stato + sub-badge QC
- ✅ AI capability propose_qc_report_summary + endpoint dedicato
- ⏳ Test live Matteo: serve smoke su DB esistente con deliverable legacy

**Test plan I post-restart server**:
1. Boot e verifica console log `[auto-migrate-bundle-i]` — mappa enum legacy (se DB ha già status legacy)
2. Apri /cost-report di un progetto con deliverable
3. Verifica badge stato attuale + sub-badge QC se applicabile
4. Click ▶ su deliverable planned → verifica passa a in_progress
5. Click 🔍 → manda a QC
6. Upload PDF QC test (qualsiasi PDF leggibile) — verifica toast "🤖 QC AI: PASS/REJECT"
7. Click ✗ Reject → verifica cascade: asset principale status='rejected' (via /dam), spawn placeholder visibile, notifica in /notifications
8. Click 🔒 su deliverable delivered → verifica chiusura + 409 se ritento update
9. Booking linkato a deliverable in_progress → cambia execution_status a in_progress → verifica deliverable auto-bump

**Bundle backlog (ordine concordato post-I)**:

0. **K — CR cleanup + ore toggle** (RIMANDATA, sostituita da I in α.172.89)
   - K1 rimuovi modalità "Stima vs Quotato" obsoleta (=Maturato vs Quotato)
   - K2 toggle "Cassa €" ↔ "Ore" su colonne JCL (qty_quoted/qty_actual/qty_planned già in DB)

1. **I — Stati nested Deliverable + cascade QC reject** ✅ FATTA in α.172.89

2. **J — Planning HUB deliverable** ✅ FATTA in α.172.90

4. **H2 — Jobs page click→modal READ-ONLY** ✅ FATTA in α.172.91

5. **H3 — Asset Library status delivery + metadata** ✅ FATTA in α.172.92
   - Asset detail mostra delivery linked status (read-only)
   - Metadata tecnici letti da file (ffprobe/mediainfo/exif)
   - NO modal edit. Asset rejected via cascade I3
   - Asset rejected → nuovo asset placeholder linked stesso deliverable (forza re-pass manuale possibile)

## Bug ancora aperti

- **Booking #54/#105/#106 ridondanti** sul JCL Dailies workflow (Filmetto): 3 booking/data invece di 2. Frutto di test iterativi. Da pulire via `propose_bulk_delete_booking` + ricreare con `propose_recurring_bookings(smart_split=true)`.
- **CR Filmetto 24300 vs quote 16200**: matematicamente corretto (54 day computed da 108 booking × 4h max human). Si normalizza dopo cleanup booking.
- **H1.bis backlog**: AI capability `_h_propose_booking` e `_h_propose_recurring_bookings` non check single-type anomaly. Da aggiungere.

## Test stato

Test sessione 25 mag pomeriggio:
- ✅ E log azioni Ctrl+Shift+L
- ✅ B smart_split AI con pausa pranzo
- ✅ A bulk_split/delete (testato live), 404 pricelist fix, itemsDS fix
- ✅ C auto-refresh timeline AI, milestone (post hotfix α.172.83), sidebar ellipsis
- ✅ D AI chat rename/delete + auto-title
- ✅ F1 capitolato (post-fix run_in_threadpool + split parse/match α.172.86)
- ✅ F2 smart_split manuale edit (post rimozione !editingId)
- ✅ F3 milestone className post-hotfix
- ✅ F4 stato quote badge
- ✅ F5 Ctrl+Z timeline capture
- ✅ F7 naming convention AI capitolato (post fix Client.code)
- ✅ G1 DeepSeek provider
- ✅ G2 unit width
- ✅ H1 anomaly warning

## Prossima sessione (chiusura 25 mag mattina, riapertura remoto via tunnel)

**Test trafila AI copilot** (post-restart server):
- Booking esistente multi-risorsa → "ri-splitta saltando pausa pranzo" → verifica replace-all + envelope + recompute CR.
- Booking con WHP cambiata → `propose_split_booking(id)` senza override → nuovi segmenti.
- Booking con `new_start/new_end` → estensione + split.
- Conflict edge: range che invade booking di altra risorsa.
- Slice-lock: split su booking in JCLBilledSlice → ValueError leggibile.
- Single-resource senza policy → fallback monolitico.

**Fase 5 a seguire** (capitolato → quote auto):
- `deliverables_parser.match_deliverables_to_pricelist` già esiste, da cablare in UI.
- 17 capitolati reali in `docs/capitolati_esempio/` come corpus test.
- Flusso target: upload capitolato → parser → preview deliverable + match listino → conferma utente → genera quote A/B/C.

**Direttiva durevole** (memo `feedback_copilot_more_capabilities.md`): ogni mutator endpoint deve avere capability `propose_*` corrispondente nel registry AI. Da applicare a ogni nuova feature.

**v3.5.0-alpha.172.74** — 25 maggio 2026 — propose_recurring_bookings: smart_split + overtime warning

Estensione α.172.73 dopo richiesta Matteo (dialogo "9-18 con pausa pranzo" → AI creava 9h monolitici invece di 8h reali con pausa).

- Capability `propose_recurring_bookings` accetta `smart_split: bool`. Riusa `working_hours.split_booking_smart` esistente. 1 booking/giorno + N assignments (mattina+pomeriggio con pausa). CR calcola ore reali al netto pausa.
- Fallback: risorsa senza policy → slot monolitico (preserva intento utente)
- Response include `daily_hours_effective`, `lunch_break_minutes`, `smart_split_applied` + opzionale `overtime_warning` se ore effettive > 8h
- System prompt rule 6: AI CHIEDE SEMPRE pausa pranzo anche se non citata (orari ampi > 6h o attraversano 12:30-14:30). Cita overtime_warning all'utente per conferma esplicita prima di proseguire.

516 routes invariato. Schema DB invariato.

**v3.5.0-alpha.172.73** — 25 maggio 2026 — AI Copilot 2 nuove capability (recurring date range + bulk status change)

Bug reali emersi su test mattutino "36 giorni dailies a ritroso da 30 mag, Luca Bianchi + Conforming 1, prima metà già done":
- AI ha calcolato 6 apr → 30 mag = 38 giorni invece di 36 (sbagliava festività edge case), dovendo cancellare a posteriori
- AI ha dichiarato "cambio stato done in blocco non disponibile via AI" → l'utente costretto a marcarli a mano dalla timeline

**Fix A** — `compute_recurring_date_range` (readonly): input `anchor_date + working_days_count + direction (forward|backward) + rule + skip_holidays` → ritorna start/until esatti + lista festività attraversate. Sostituisce calcolo mentale dell'AI.

**Fix B** — `propose_bulk_booking_status_change` (mutation): cambia stato (tentative/confirmed/in_progress/done/not_done) di N booking via `booking_ids[]` OR `filter{job_id|project_id|resource_id, date_from, date_to, current_state}`. Skip granulare slice locked / JCL in_batch / already_target. `not_done` richiede `note`. Recompute maturato automatico se done. Audit log BookingChange.

System prompt rule 6 estesa: "USA SEMPRE compute_recurring_date_range quando l'utente dà N giornate / a ritroso / N settimane" + "NON dire mai 'cambio stato non disponibile via AI', USA propose_bulk_booking_status_change".

516 routes (+2 capability). Schema DB invariato. Pronto per smoke test su scenario "36 dailies a ritroso".

**v3.5.0-alpha.172.72** — 24-25 maggio 2026 — Test maratona FASE 1-4 + 20+ patch + Brand Claqo pack

22 commit (24 mag): test FASE 0-4 chiusi + bug fixes acconto/SDI/UI + rebrand Claqo (mascot copilot da brand-pack ufficiale, app icon variant-B/C, tema Claqo Dark+Light), feat aggiunte: milestone timeline gruppo dedicato + modal CRUD, camera specs matrix 26 modelli filter live, scheda tecnica dropdown human-readable, filtri fatture annullate/NC, projects row-clickable + scadenza/quote-ref, post-emit no-cancel → NC TD04 auto-num, sede tenant strutturata + IscrizioneREA in XML SDI, AI parse capitolati 503.

**v3.5.0-alpha.172.53** — 24 maggio 2026 — Hard reset acconto + cap cross-AP preset + HARD-BLOCK sotto-copertura

Test FASE 1 plan 24 mag chiuso. 3 fix mirati su modal "Gestisci acconto":
- Reset HARD (cancella allocations JCL+Deliverable)
- Preset auto sottraggono altri AP attivi dal cap JCL
- Confirma 409 se Σ alloc < AP.amount + bug flush risolto α.172.53

13 commit 23 mag α.172.34 → α.172.50. Sprint 1-6 audit chiuso 100% + 7 fix post-audit + DB ripulito + UX modal acconto migliorata.

Sintesi post-audit fix:
- α.172.42 cashflow Fandango outstanding includeva cancelled (-€57.528 fantasma)
- α.172.42 cascade NC→AdvancePayment draft anche da update_invoice_status cancelled
- α.172.42 modal "Nuovo cliente" 7 campi fiscali SDI mancanti aggiunti
- α.172.43 UX modal Emit acconto: banner verde/rosso + Emit disabilitato se 0 alloc
- α.172.44-45 filmografia AI schema esteso (cast/funding/release/festival) + wire-up backend + UI import
- α.172.46-47-49 3 livelli HARD-BLOCK Σ acconti: budget progetto + schedule quote + cross-AP JCL
- α.172.48 toastBlock 12s rosso visibile per warning 409 + auto-trigger su detail.message
- α.172.50 endpoint reset draft→pending + UI bottone + banner spiegativo modal allocazione

DB: clienti+progetti+quote freschi (purge totale business 23 mag sera). Anagrafiche tecniche preservate. Matteo ha creato 1 quote + 2 acconti pre-chiusura sera.

514 routes (+1 reset endpoint).

## Lavoro in corso

α.172.73 chiuso (mattino 25 mag) — 2 capability AI nuove pronte per test live via copilot. **Riapertura test plan 24 mag da FASE 5 SDI compliance** (FASE 1-4 chiuse da α.172.72).

## Prossimo step

**Test plan dettagliato in memoria** `project_test_plan_24mag2026.md` — restano FASE 5-12 da fare insieme:

- FASE 5-6: Compliance SDI + XML download FatturaPA
- FASE 7: Pass-through OT toggle weighted_revenue
- FASE 8: Cashflow Fandango (skip se DB purgato)
- FASE 9: Filmografia AI dettagliata (cast/finanziamenti/festival)
- FASE 10: Anomaly reopen cascade
- FASE 11: 3 block visivi toastBlock (schedule/AP/cross-JCL)
- FASE 12: Issue aperti (Deliverable in acconto, rendering filmografia)

**Smoke test α.172.74 da fare prima del FASE 5**:
- Copilot: "Per Filmetto Test aggiungi 36 giorni di dailies a ritroso dal 30 maggio, Luca Bianchi + Conforming 1, 9-18". Verificare che AI:
  1. Chiami `compute_recurring_date_range(anchor=2026-05-30, n=36, backward, skip_holidays=true)` → ottiene start 9 apr (skipped 1 mag)
  2. CHIEDA esplicitamente "orario continuato o con pausa pranzo?" (anche se Matteo nel test cita "con pausa pranzo", verificare che AI rispetti la rule anche se utente non cita)
  3. Su conferma pausa: chiami `propose_recurring_bookings(smart_split=true, ...)` → 36 booking creati, ogni booking con 2 assignments × 2 risorse = 4 totali (9-13 + 14-18 per Luca + Conforming1)
  4. Su orario continuato senza pausa: response avrà `overtime_warning` (9h > 8h) → AI lo cita all'utente
- Copilot: "Marca done i primi 18 booking della serie dailies di Filmetto Test". Verificare che AI chiami `propose_bulk_booking_status_change` con filter `{job_id, date_to, current_state: confirmed}` e new_state=done.

Backlog Sprint 7 (post-test):
- FK ondelete table-rebuild SQLite (rischio)
- Trasmissione SDI auto (firma digitale richiesta)
- UI bottone "Genera XML SDI" in /finance tab
- Allocazione acconto su JobDeliverable (modal duale JCL+Deliverable)
- Rendering UI schede filmografia esteso (synopsis/cast_crew/funding visibili)

## Bug aperti

Stato audit complessivo (TUTTI CHIUSI):
- ✅ BLOCCO 1 (tenant scope) — α.172.35
- ✅ BLOCCO 2 (slice-lock quote-side) — α.172.36
- ✅ BLOCCO 3 (UI 404 endpoint) — α.172.36
- ✅ BLOCCO 4 (finance + Decimal hotspot) — α.172.37+38
- ✅ BLOCCO 5 (UI antipattern) — α.172.39
- ✅ BLOCCO 6 parte 1 (DB integrity + IT tax foundation) — α.172.40
- ✅ BLOCCO 6 parte 2 (SDI compliance + FatturaPA XML) — α.172.41

Da 131 finding totali audit → tutti i P0+P1 critici chiusi o documentati. Restano backlog cleanup (table rebuild rischiosi, UI lower-risk residui, integrazione SDI live).

## Versione precedente

**v3.5.0-alpha.172.40** — 23 maggio 2026 — Sprint 5 Audit: DB integrity + IT tax foundation (BLOCCO 6 parte 1)

Chiude BLOCCO 6 parte sicura — 6 sub-fix integrity DB + foundation compliance italiana:

- **5.A immutability event listener** JCLBilledSlice (defense-in-depth, qualsiasi ORM write su slice billed = ValueError eccetto storno via NC TD04)
- **5.B 4 modelli `tenant_id` → ForeignKey** (Holiday/Notification/ProjectTechSheet/TechSheetFieldOption)
- **5.C Tag + FXRate tenant_id** + UNIQUE composito + auto-migrate
- **5.D INDEX su 14 FK hot-path** (projects/quotes/jobs/JCL/invoices/quote_lines/invoice_lines)
- **5.E `italian_tax.py`** foundation: validate P.IVA Luhn mod-10, CF, SDI 7-char, IBAN IT mod-97, enum RF01-RF19/TD01-TD28/N1-N7.x, mapping kind→TD, `invoice_sdi_compliance_check` pre-emit
- **5.F JSON validators** `@validates` su Role.permissions, WHP.overtime_brackets, Tenant.asset_numbering_config

Smoke test italian_tax: P.IVA RAI, IBAN reale, CF, enum tutti OK.

512 routes invariato.

## Lavoro in corso

Sprint 5 chiuso. **Sprint 6 (FINALE)** = BLOCCO 6 parte rischiosa + FatturaPA XML + wire-up validators + UI backlog. Bump previsti α.172.41+.

## Prossimo step

1. **italian_tax wire-up router**: clients.py POST/PUT vat_number → `validate_partita_iva` → 422 se invalido. Same per Supplier, Tenant, Invoice snapshots.
2. **FatturaPA XML builder**: `app/services/sdi_xml.py` nuovo + endpoint `GET /finance/api/invoices/{id}/sdi-xml`. Skill `sdi-xml-builder` come riferimento implementation.
3. **`invoice_sdi_compliance_check` HARD-BLOCK** in `billing.emit_invoice` (pre-DB-commit): se errors → 422 con lista.
4. **FK `ondelete`**: rebuild table SQLite per Project/Job/Tenant/Client FK. RISCHIO ALTO — fare con backup + script di migration dedicato.
5. **Backlog UI 4.E**: pricelist `${i.name}/${i.description}`, cost_report opzioni, dam upload `${f.name}`, planning title attrs, finance options.
6. **Old UNIQUE legacy rebuild**: Tag.name + Invoice.number + Asset filename, table-rebuild per dropare UNIQUE globale e attivare composito.

## Bug aperti

Stato audit:
- ✅ BLOCCO 1 (tenant scope) — α.172.35
- ✅ BLOCCO 2 (slice-lock quote-side) — α.172.36
- ✅ BLOCCO 3 (UI 404 endpoint) — α.172.36
- ✅ BLOCCO 4 (finance + Decimal hotspot) — α.172.37+38
- ✅ BLOCCO 5 (UI antipattern) — α.172.39
- ✅ BLOCCO 6 parte 1 (DB integrity + IT tax foundation) — α.172.40
- 🔜 BLOCCO 6 parte 2 (FatturaPA XML + wire-up + FK ondelete) — Sprint 6

## Versione precedente

**v3.5.0-alpha.172.39** — 23 maggio 2026 — Sprint 4 Audit: UI antipattern cleanup (BLOCCO 5)

Chiude BLOCCO 5 — 6 categorie antipattern UI/JS:

- **4.A helper shadow rimossi**: pricelist fmtCurrency, hr fmtDate, fs_scan fmtSize → uso global.js. fmtSize esteso GB+.
- **4.B JSON.stringify in onclick**: 4 spot (dam/notifications/cost_report/finance) → data-attr + cache map.
- **4.C setSelection wrapper bypass**: 8 spot planning.html → `_tlSetSel()` per fire event.
- **4.D stack:true light-mode**: planning.html legge localStorage.mf_tl_light per disabilitare stack su dataset grossi.
- **4.E escapeHtml innerHTML top 4 hotspots**: dashboard/projects/project_detail/clients. Backlog (lower-risk) → Sprint 5.
- **4.F cache-buster automatico**: `app_version` Jinja global + 11 static refs `?v={{ app_version }}`. Bump versione = invalida tutti gli static.

512 routes invariato.

## Lavoro in corso

Sprint 4 chiuso. **Sprint 5 next**: BLOCCO 6 — DB integrity (FK ondelete, immutability event listener, soft-delete + UNIQUE bypass) + IT compliance (P.IVA/CF/SDI/natura validators + FatturaPA XML builder). Bump previsti α.172.40 → α.172.50.

## Prossimo step

1. FK `ondelete` esplicito su tutti FK Project/Job/Tenant/Client
2. SQLAlchemy event listener `before_update` su `JCLBilledSlice` (immutability model-level)
3. `tenant_id` → ForeignKey su 4 modelli bare Integer (Holiday/Notification/ProjectTechSheet/TechSheetFieldOption)
4. `tenant_id` su Tag + FXRate (leak reali)
5. `index=True` su 22 FK hot-path
6. JSON validators su `role.permissions`, `tenant.asset_numbering_config`, `working_hours_policy.overtime_brackets`
7. **`app/services/italian_tax.py`**: validator P.IVA (11+Luhn-mod-11), CF (16/11), SDI (7 char), enum N1-N7, enum RF01-RF19, mappa TD02 per advance
8. **`app/services/sdi_xml.py`**: nuovo, FatturaPA XML builder via `sdi-xml-builder` skill
9. Endpoint `/finance/api/invoices/{id}/sdi-xml`
10. Backlog UI 4.E lower-risk: pricelist/cost_report/dam/planning title

## Bug aperti

Stato audit:
- ✅ BLOCCO 1 (tenant scope) — α.172.35
- ✅ BLOCCO 2 (slice-lock quote-side) — α.172.36
- ✅ BLOCCO 3 (UI 404 endpoint) — α.172.36
- ✅ BLOCCO 4 (finance + Decimal hotspot) — α.172.37+α.172.38
- ✅ BLOCCO 5 (UI antipattern) — α.172.39
- 🔜 BLOCCO 6 (DB integrity + IT compliance) — Sprint 5

## Versione precedente

**v3.5.0-alpha.172.38** — 23 maggio 2026 — Sprint 3.5: Decimal in invoice_totals hotspot

Mini-sprint chiusura BLOCCO 4. Decisione **opzione C**: SQLite stores REAL nativo, scale MediaFlow non soffre Float precision. Migrazione full ~70 campi rinviata a porting Postgres.

Sprint 3.5 minimale = `Decimal` solo nell'hotspot di aggregazione critica:
- Nuovo `app/services/money.py` con `to_decimal/money_round/money_to_float` (HALF_UP fiscale, NON banker's HALF_EVEN)
- `invoice_totals.compute_invoice_totals_from_lines` refactored Decimal interno, float boundary
- Garantisce Σ(round(x, 2)) ≡ round(Σ(x), 2) anche su 200+ righe

512 routes invariato. 4 test smoke passati (single rate / multi-aliquota / 200 righe penny / empty).

## Lavoro in corso

Sprint 3.5 chiuso. **Sprint 4 next**: BLOCCO 5 UI antipattern.

## Prossimo step

(same as Sprint 4 plan)

## Versione precedente

**v3.5.0-alpha.172.37** — 23 maggio 2026 — Sprint 3 Audit: finance domain invariants (BLOCCO 4)

Chiude BLOCCO 4 — 5 bug finance critici:

- **3.A weighted_revenue ora funziona**: `cost_line_sync.recompute_cost_line_actual` applica `_booking_hours_weighted` (CCNL brackets + multiplier holiday/sunday/overtime/night) quando `Job.weighted_revenue=True`. Pre-α.172.37 il flag era dead code — pass-through OT al cliente non-funzionante.
- **3.B anomaly reopen cascade**: cancella `LossEntry` (hard) / soft-delete `OverheadCost` collegati al reopen → previene P&L double-count su re-handle.
- **3.C overtime brackets single source of truth**: `overtime.py` importa helper di `booking_cost.py` per CCNL scaglioni. Pre-α.172.37 HR (buste paga) vs CR (cost report) divergenti.
- **3.D IVA per-riga**: nuovo `app/services/invoice_totals.py` (`compute_invoice_totals_from_lines` + `apply_totals_to_invoice` + `by_rate` per FatturaPA `<DatiRiepilogo>`). 3 callsite aggiornati (emit_invoice + compose_invoice_from_batches + add_invoice_line, anche fix `subtotal=None` TypeError).
- **3.E Invoice.tenant_id denormalizzato**: nuova colonna + `UniqueConstraint(tenant_id, number)`. Auto-migrate ALTER TABLE + backfill da `Client.tenant_id` + UNIQUE INDEX composto + INDEX su tenant_id. 7 callsite `Invoice(...)` impostano `tenant_id=current_tenant_id()`. `tenant_guard._INDIRECT_VIA_CLIENT` ora vuoto (Invoice scope diretto). Legacy `UNIQUE(number)` sopravvive fino a rebuild table (Sprint 5 roadmap).

512 routes (invariato). Auto-migrate idempotente al primo boot post-pull.

## Lavoro in corso

Sprint 3 chiuso. **Sprint 4 next**: BLOCCO 5 UI antipattern (JSON.stringify in onclick, escapeHtml innerHTML, setSelection wrapper bypass, CSRF). Bump previsti α.172.38 → α.172.42.

## Prossimo step

1. Helper redefiniti rimuovi (pricelist fmtCurrency, hr fmtDate, fs_scan fmtSize)
2. 4 onclick JSON.stringify → data-* attributes (dam, notifications, cost_report, finance)
3. 9 `setSelection()` → `_tlSetSel()` wrapper in planning.html
4. `mf_tl_light` flag su stack:true (planning.html:1770)
5. escapeHtml sistematico in 25+ template innerHTML
6. Cache-buster `?v=` automatico via hash file (helper Jinja)

## Bug aperti

Stato audit:
- ✅ BLOCCO 1 (tenant scope) — α.172.35
- ✅ BLOCCO 2 (slice-lock quote-side) — α.172.36
- ✅ BLOCCO 3 (UI 404 endpoint) — α.172.36
- ✅ BLOCCO 4 (finance: weighted_revenue + anomaly + overtime brackets + IVA + Invoice.number) — α.172.37
- 🔜 BLOCCO 5 (UI antipattern) — Sprint 4
- 🔜 BLOCCO 6 (DB integrity + IT compliance + Float→Numeric Sprint 3.5) — Sprint 5

## Versione precedente

**v3.5.0-alpha.172.36** — 23 maggio 2026 — Sprint 2 Audit: slice-lock simmetrico + UI 404

Chiude **BLOCCO 2** (immutability JCL violata quote-side) + **BLOCCO 3** (3 endpoint UI 404 silenti).

**Slice-lock simmetrico**: esteso `app/services/billing_slice_guard.py` con API JCL-driven (`find_any_active_slice_for_jcl`, `jcl_lock_message`, `assert_jcl_lock_safe`). 4 callsite quote-side patchati:
- `update_quote_line` sync JCL (era leak: rinomina/riprezza silenzioso post-billing)
- `delete_quote_line` cascade (era leak: slice orfane)
- `batch_delete_quote_lines` (era leak: idem batch)
- `migrate_job` versioning re-bind (era leak: ribind silenzioso)

Tutti tornano 409 con payload `{message, lock: {slice_id, period_start, period_end, invoice_number, billed_amount}}` consumabile dalla modale di rettifica UI.

**UI 404 fix** (cross-ref audit):
- `project_detail.html:1283-1285` deliverable templates → `/delivery-templates/api/list`
- `job_detail.html:1011` resources dropdown → `/resources/api`

512 routes (invariato). Smoke OK.

## Lavoro in corso

Sprint 2 chiuso. **Sprint 3 next** dell'audit: BLOCCO 4 finance — `weighted_revenue` dead code in `cost_line_sync.py` + Float→Numeric migration + IVA per-riga + `Invoice.number` UNIQUE per-tenant.

## Prossimo step

1. **Weighted_revenue**: branch `_booking_hours_weighted` in `cost_line_sync.recompute_cost_line_actual:320-401` (helper già scritto a riga 194)
2. **Invoice.number multi-tenant**: migration `UniqueConstraint("tenant_id", "number")` + script
3. **Anomaly reopen**: soft-delete `LossEntry`/`OverheadCost` collegato al reopen
4. **Overtime brackets**: unificare in `overtime.py:222` chiamando helper di `booking_cost.py`
5. **IVA per-riga**: refactor `billing.py:1142,1362` calcola vat_amount per `InvoiceLine`
6. **Float→Numeric** migration: Quote/Invoice prima, JCL dopo, Resource rate ultimo

## Bug aperti

Stato audit:
- ✅ BLOCCO 1 (tenant scope leak) — α.172.35
- ✅ BLOCCO 2 (slice-lock quote-side) — α.172.36
- ✅ BLOCCO 3 (UI 404 endpoint) — α.172.36
- 🔜 BLOCCO 4 (weighted_revenue + Float→Numeric + IVA per-riga + Invoice.number) — Sprint 3
- 🔜 BLOCCO 5 (UI JSON.stringify + setSelection wrapper + escapeHtml + CSRF) — Sprint 4
- 🔜 BLOCCO 6 (FK ondelete + JCLBilledSlice immutability model-level + validators IT + FatturaPA XML) — Sprint 5

## Versione precedente

**v3.5.0-alpha.172.35** — 23 maggio 2026 — Sprint 1 Audit: tenant scope guard

Chiude **BLOCCO 1** dell'audit multi-agent (5 agent paralleli, 131 finding, 37 P0): cross-tenant data leak su pattern by-ID lookup e page-render. 23 query patchate via helper riusabile.

**Nuovo `app/services/tenant_guard.py`**: `scoped(query, Model)` + `fetch_or_404(db, Model, id)` + `fetch_invoice_or_404(db, id)`. Gestisce indirezione Invoice via Client. Fallisce LOUD se Model nuovo senza strategia di scope (no leak silente futuro).

**Nuovo permesso RBAC `edit_cost_lines`** in categoria Finanza. Assegnato a admin/manager/producer/accounting.

**Endpoint deprecati rimossi** (avevano bug + duplicati):
- `POST /planning/api/clients` (era v3.4.x deprecated)
- `POST /planning/api/jobs` (era v3.4.8 deprecated)

**Router toccati** (23 fix):
- planning.py: 4 query (page-render Job/Quote, job_progress, coverage, get_job, list_jobs baseline)
- finance.py: 9 query (page-render Invoice, list_timesheets baseline, 5 Invoice by-ID + payment, list_floating_jobs, list_discrepancies, rimosso hardcoded tenant=1 fallback)
- jobs.py: 4 query (3 JCL by-ID + Job in naming-tokens)
- cost_report.py: 2 (gate + JCL by-ID update)

App boota 512 routes (-2 da deprecati). Smoke import OK.

## Lavoro in corso

Sprint 1 chiuso. **Sprint 2 next** dell'audit: slice-lock simmetrico quote-side (BLOCCO 2 audit) + 3 endpoint UI 404 (BLOCCO 3). Bump previsti α.172.36 → α.172.40.

## Prossimo step

1. **Slice-lock symmetric**: estrarre `assert_slice_lock_safe()` da planning.py → service condiviso. Applicare a `quotes.py:1645,3105,1840,2028` con HARD-BLOCK 409.
2. **FK ondelete safety** su `jcl_billed_slices.job_cost_line_id` (model-level event listener `before_update`).
3. **Fix 3 endpoint 404 UI**: project_detail.html:1283-1285 → `/delivery-templates/api/list`, job_detail.html:1011 → `/resources/api`.

## Bug aperti

Audit multi-agent (`23 mag 2026`): 131 finding, 37 P0. Stato:
- ✅ BLOCCO 1 (tenant scope leak) — chiuso α.172.35
- 🔜 BLOCCO 2 (slice-lock quote-side) — Sprint 2
- 🔜 BLOCCO 3 (UI 404 endpoint mancanti) — Sprint 2
- 🔜 BLOCCO 4 (weighted_revenue dead, Float→Numeric, IVA per-riga, Invoice.number multi-tenant) — Sprint 3
- 🔜 BLOCCO 5 (UI JSON.stringify onclick, setSelection bypass, escapeHtml innerHTML, CSRF) — Sprint 4
- 🔜 BLOCCO 6 (FK ondelete, JCLBilledSlice model-level immutability, P.IVA/CF/SDI validators, FatturaPA XML) — Sprint 5

## Versione precedente

**v3.5.0-alpha.172.34** — 22 maggio 2026 — Dropdown campi scheda tecnica + seed Netflix

A della lista complessi: pannello admin /settings → "Scheda tecnica" per gestire opzioni dei campi tecnici (codec, sample_rate, formato editorial, ecc). Editor pubblico scheda tecnica usa `<select>` strict quando campo ha opzioni. Bottone "🎬 Seed Netflix" popola con ~250 valori da Netflix Delivery Specifications (40 field paths). Endpoint pubblico no-auth gated da edit_token.

LISTA COMPLESSI COMPLETATA. Restano test intensivi su tutto α.172.x.

## Versione precedente

**v3.5.0-alpha.172.33** — 22 maggio 2026 — Refactor holidays scope → policy CCNL

C della lista complessi: festività legate alle policy CCNL invece di per-resource/location. Pulizia architettura. Resolver via `effective_policy_id` (override OR default). Backward-compat legacy fields preservati ma ignorati. Link "Calendario festività" sotto /settings → Orari lavorativi.

Resta complesso: A (dropdown scheda tecnica + seed Netflix, α.172.34).

## Versione precedente

**v3.5.0-alpha.172.32** — 22 maggio 2026 — Multi-preset WorkingHoursPolicy UI + accrual override

B della lista complessi: orari lavorativi salvabili come preset multipli (CCNL diversi per post-prod), richiamabili per resource. UI in `/settings → Orari lavorativi` con selector + bottoni Nuovo/Duplica/Set Default/Elimina. Card resource estesa con override accrual ferie/ROL/permessi + location tag (per festività locali). Endpoint CRUD completi + HARD-BLOCK delete se policy in uso.

Restano complessi: C holidays in policy (α.172.33), A dropdown scheda tecnica (α.172.34).

## Versione precedente

**v3.5.0-alpha.172.31** — 22 maggio 2026 — Acconto HARD-BLOCK JCL + NC approved init + cascade

3 fix workflow finanziario:
- HARD-BLOCK emit acconto senza JCL allocations (422 con messaggio guida)
- NC nasce in stato `approved` (nuovo enum value), invio separato via mark-sent
- Cascade NC su Acconto → AdvancePayment torna `draft` (riusabile per riedit + riemit)

Rinviato α.172.31.1: #1 preset selector in quote modal acconto (solo UI helper, scope minore).

## Versione precedente

**v3.5.0-alpha.172.30** — 22 maggio 2026 — Bug fix: edit assenze approvate + cashflow dropdown

2 fix puntuali (subset della lista facili di Matteo): PUT endpoint unavailability con permission gate (staff=pending+own / admin=qualsiasi) + UI bottone ✏️ + reuse modal-punch via marker `unav:N`. Cashflow loadFilters difensivo (Array.isArray cast + console log) per dropdown vuoti.

**Rinviato α.172.31+**: #1-#4 (Acconto config quote + HARD-BLOCK JCL + NC approved-init + NC→Acconto cascade) + B (UI multi-preset WHP) + C (refactor holidays scope policy) + A (dropdown campi scheda tecnica con pannello admin + seed Netflix).

## Versione precedente

**v3.5.0-alpha.172.29** — 22 maggio 2026 — Assenze a ore + festività custom + AI CCNL params

Bundle 2 feature richieste:
1. **Permesso ROL / Malattia / Ferie / Recupero ore — anche a ore** (15min granularità). Integrate nel modal `/hr` timbratura via dropdown optgroup. Dispatch backend a `/planning/api/unavailabilities` con start_time/end_time. Service `compute_leave_balance` calcola saldo dinamico (maturate pro-rata − consumate approved). UI: card 📊 Saldo ferie/ROL/permessi/malattia con filtro risorsa.
2. **Calendario festività custom** tenant-scoped con scope per-resource/location. Pagina `/hr/holidays` CRUD + import CSV. Nazionali italiane (holidays.IT) attive di default + custom locali / aziendali / override / exclude. Refactor 2 callsite AI per usare festività effective.

Bonus:
- 2 nuove AI capability: `propose_ccnl_params` (aggiorna WorkingHoursPolicy con dati CCNL via AI) + `propose_holiday_set` (bulk insert festività).
- WorkingHoursPolicy accrual fields: ferie/anno, ROL/mese, permessi/mese (override per-resource opzionale).

## Versione precedente

**v3.5.0-alpha.172.28** — 22 maggio 2026 — Scheda tecnica progetto: link pubblico EDITABILE

Aggiunto link `/public/tech-sheet/{edit_token}/edit` complementare al readonly esistente. Editor compilabile senza login con identità tracciata (nome+email obbligatori), salvataggio granulare per sezione, polling concorrenza 30s con banner. UI gestione in `/projects/{id}` (modal "🔓 Link modificabile" + lista log modifiche pubbliche). Default scadenza 30gg.

## (versione precedente)

**v3.5.0-alpha.172.27** — 21 maggio 2026 — AI Copilot polish + bulk delete + timeline incrementale

11 commit α.172.17→α.172.27 pushati. Sessione lunga via tunnel cloudflared (test live in browser).

**Highlight versioni**:
- **α.172.17** Booking AI multi-risorsa (`resource_ids[]`) + HARD-BLOCK `job_cost_line_id` server-side + search Consegne modal
- **α.172.18** Quote approvata immutabile (`_assert_quote_mutable`) + cascade JobDeliverable in delete/migrate/batch_delete
- **α.172.19** Backfill `unit_nature` legacy + auto-fix silent al boot + consolidate volume/forfait + delete orphan
- **α.172.20** Bulk delete assignment: endpoint `POST /api/booking-assignments/bulk-delete` + bottone toolbar planning
- **α.172.21** Timeline planning refresh incrementale (`tlIncrementalRefresh/Remove/RemoveAssignments` su `itemsDS`) — 7 callsite refactored
- **α.172.22-.23** Fix DB import Win/OneDrive: `engine.dispose()` + in-place rewrite + retry backoff
- **α.172.24** AI linguaggio umano (vietato `JCL`/`propose_*` nelle risposte) + sezione LAVORAZIONI DEI JOB nel context
- **α.172.25** Fix AI: deriva `job_id` da `job_cost_line_id`
- **α.172.26** AI skip festività italiane (`holidays.IT`) + fix flex display lista Consegne
- **α.172.27** Tool readonly `check_recurring_booking_collisions` anticipa festività/ferie/conflict

**DB stato**: 23 Deliverable totali (era 123), backfill + cleanup orfani applicato. Export ZIP `mediaflow-export-3.5.0-alpha.172.27-20260521-190332.zip` (281 KB).

## Prossimo step — Sessione 22+ maggio (definita da Matteo)

1. **Sconti in CR**: audit di come line/category/package discount propagano da Quote a CR. Verifica `total_quoted` lavorazioni vs `subtotal_after_cat`. Memory `project_backlog_sconti_quote_cr_fatturazione`.
2. **Deep test CR Deliverables + Assets**: dopo restructure α.172, verificare CR su voci non-time. Branch `deliverable_qty` (N row 1 cad) vs volume/forfait (1 row aggregato) — verifica accrued/billed corretti.
3. **MAM (Media & Asset Management) — implementazione iniziale**: link DAM/PhysicalAsset → Deliverable conferma. Memory `project_dam_physical_assets`.
4. **Funzioni in/out + spedizioni**: PhysicalAsset logistics 360° (esisteva in α.66.10+), approfondimento workflow DDT + QR + scan + numerazione.

**Setup tunnel per dev remoto** (opzionale): `tools/cloudflared.exe tunnel --url http://localhost:8000 --no-autoupdate` → URL temporaneo HTTPS per browse via tunnel senza push/pull. Persiste finché processo vivo.

## (versione precedente)

**v3.5.0-alpha.172.9** — 21 maggio 2026 — Restructure 2026-05-20 Sprint 5/5 COMPLETE (migration UX). 485 routes.

## (versione precedente)

**v3.5.0-alpha.172.8** — 21 maggio 2026 — Sprint 4 Restructure COMPLETE (T1→T5)

UI editor quote + CR detail + booking modal + job kanban + listino editor. 480 routes.

## (versione precedente)

**v3.5.0-alpha.172.4** — 21 maggio 2026 — Sprint 4 T1 editor quote split (separazione tab Lavorazioni/Consegne)

## (versione precedente)

**v3.5.0-alpha.172.3** — 20 maggio 2026 — Sprint 3 Restructure: endpoint + Bug 1 fix

5 endpoint nuovi (hard-delete admin, confirm-delivery, booking↔deliverable M:N, ingest MHL/CSV LTO) + fix Bug 1 allocation acconto (PUT advance-schedules accetta allocations, materialize considera Deliverable). RBAC nuovi keys: hard_delete_project, view/edit/confirm_deliverables.

## (versione precedente)

**v3.5.0-alpha.172.2** — 20 maggio 2026 — Sprint 2 Restructure: service layer

Sprint 2 di 5. Service core rifatto per supportare separazione JCL/Deliverable.

**Servizi modificati**:
- `cost_line_sync.py`: branch binary RIMOSSO (root cause Bug 2). JCL solo time-based. JCL non-time legacy azzerate con warning.
- `deliverable_cost_sync.py` NUOVO: cost split equo booking → N deliverable. Revenue manuale via quantity_delivered.
- `reverse_quote.py`: branching unit, spawn JobDeliverable per voci non-time. Phantom Z esteso.
- `project_purge.py` NUOVO: hard-delete cascade 17-step FK-safe admin-only.
- `routers/quotes.py:_create_job_from_quote`: branching JCL/Deliverable per unit al convert quote→job.

**Smoke test**:
- JCL legacy non-time azzerate ✓ (12 JCL P1-P4)
- Recompute Deliverable cost split: P1/P2 cost da booking done, P3/P4 = 0 (booking confirmed non in_progress) ✓
- Hard-delete cascade su P4 (con acconti + bookings + Deliverable + invoices): 25+50+3+16+2+2+8+3+1+1+1 record cancellati senza FK violation ✓
- Idempotenza re-seed + re-migrate confermata

## Prossimo step — Sprint 3 Endpoint

1. `DELETE /admin/projects/{id}/hard-delete` con `RequireAdmin` + confirm_token
2. `POST /jobs/{id}/deliverables/{did}/confirm-delivery` (+ optional asset_id)
3. `POST /bookings/{id}/link-deliverable` (M:N add)
4. `POST /ingest/yoyotta-mhl` (upload MHL → parse → spawn PhysicalAsset + auto-link Deliverable)
5. `POST /ingest/csv-lto` (CSV alternativo)

## (versione precedente)

**v3.5.0-alpha.172.1** — 20 maggio 2026 — Sprint 1 Restructure: schema + migration + backfill

Sprint 1 di 5 della ristrutturazione architetturale (vedi `docs/RESTRUCTURE_2026_05_20.md`).

**Schema nuovo**:
- 7 modelli nuovi: BookingDeliverable, DeliverableAsset, DeliverableSpec, DeliverableBilledSlice, AdvancePaymentDeliverableAllocation, VFXShot, PricelistUnit
- 2 enum nuovi: DeliverableUnitNature, DeliverableBillingStatus
- JobDeliverable esteso (+16 colonne) — quantity/billing/conferma
- Quote: subtotal_gross_jcl + subtotal_gross_deliverable
- PriceItem: unit_nature

**Migration `scripts/migrate_restructure_phase1.py`** idempotente:
- Test su DB seed_5projects: 32 JCL → 12 JobDeliverable autospawnati (1 row per qty), 12 booking pivot, 44 PriceItem backfilled, 11 PricelistUnit seedate
- Quote split: 29450 JCL + 1850 Deliverable = 31300 ✓
- Rerun idempotency confermata

**Auto-migrate boot** in lifespan (anti-crash su pull senza migration).

## Prossimo step — Sprint 2 Service layer

1. `cost_line_sync.py`: rimuovere branch binary (linee 386-393). JCL solo time-based → fix strutturale Bug 2 maturato fantasma.
2. Nuovo `deliverable_cost_sync.py`: cost split equo booking → N deliverable linkati. Maturato manuale.
3. Estendere `reverse_quote.py` per phantom deliverable (non solo JCL).
4. Hook hard-delete in nuovo `project_purge.py`.

## (versione precedente)

**v3.5.0-alpha.172** — 20 maggio 2026 — Design doc restructure JCL→CR→Fatt→Cashflow + tool seed 5 progetti test

Sessione 20 mag — **no code changes**, solo doc strategici + tooling per test.

**Doc strategico `docs/RESTRUCTURE_2026_05_20.md`** committato. Ristrutturazione architetturale concordata punto-per-punto con Matteo:
- Separazione netta lavorazioni (JCL, solo time-based hr/day) vs consegne (JobDeliverable, qty/volume/manual).
- Booking↔Deliverable M:N. PhysicalAsset 1:1 progetto. Phantom Z esteso.
- Hard-delete progetto admin-only cascade FULL (test-only).
- Sprint plan 5 fasi (schema → service → endpoint → UI → migration UX).
- Decisioni finali: AdvancePaymentDeliverableAllocation separata, sconti spalmati DENTRO sezione, cashflow horizon configurabile default 90gg con sub-categorie separabili, migration autospawn.

**Tool `scripts/seed_5projects.py`** per test DB pulito: 5 progetti DI+AUDIO compressi 1 mese, mix stati maturato (100%/50%/quote-only), 2 con acconti 30% completi.

**Bug aperti registrati** (memory `project_bug_acconti_2026_05_20`):
- Bug 1 allocation acconto su JCL sbagliate (PUT manca `allocations` + fill_sequential ignora pct + idempotency block re-materialize)
- Bug 2 maturato fantasma su unit non-time-based (regola binary in `cost_line_sync.py:386-393`)
- Entrambi risolti strutturalmente nel restructure.

## Prossimo step

1. Quando Matteo è su Mac fisico: inspect DB remoto per Bug 1 (verifica residue AP_alloc + versioning quote)
2. Decisione: hotfix Bug 1+2 in versione corrente PRIMA di Sprint 1 restructure, o saltare hotfix e partire diretti restructure
3. Eventuale audit sconti quote→CR→Fatt completare prima di Sprint 1 (memory `project_backlog_sconti_quote_cr_fatturazione`)

## (versione precedente)

**v3.5.0-alpha.171.9** — 19 maggio 2026 — Sprint 1+2+3 chiusi: CR data integrity + Phantom redesign + filtri planning + timeline scroll

Maratona 19 mag pomeriggio/sera, 9 commit pushati (α.171 → α.171.9). Chiusi tutti i 3 sprint backlog α.171:

**Sprint 1 CR (α.171)**: CR-2 ore billable (`_booking_billable_hours` max umana || max non-umana), CR-1 binario non-time (`actual=expected=quoted` per lump/pc/shot/...), CR-1 time-based 0 booking → 0. Script `recompute_all_jcl.py` per backfill.

**Sprint 2 Phantom redesign (α.171.1-.6, .8, .9)**: 8 step di redesign quotazione consuntivo.
- Step 1: enum `PhantomStatus` + colonne `phantom_status`/`merged_into_quote_id` + migration + unique partial index 1-per-progetto
- Step 2: rename UI "Phantom" → "Quotazione a Consuntivo", pre-check no quote attiva
- Step 3: endpoint `promote-phantom` + `merge-into/{target}`
- Step 4: voci Consuntivo `quantity=0`, auto-attach a Consuntivo esistente
- Step 5 (UI): doppia conferma modifica quote approved + auto-versioning (saveQuoteMeta MVP)
- Step 6: delete voce quote approved → propagazione CR su Consuntivo (vs hard-block)
- Step 7: badge CR `📌 CONSUNTIVO` per phantom_status
- Step 8: AI capability `propose_promote_phantom` + `propose_merge_phantom` + system prompt

**Sprint 3 filtri planning (α.171.7, .9)**:
- TL-1: filtro reparto chip-multi `fa-multi` (era `<select multiple>`)
- TL-3: `/api/bookings` accetta `job_cost_line_id` CSV
- TL-4: vista "Per progetto" rispetta tutti i filtri sidebar
- TL-5: ricerca testuale `q` LIKE su notes/JCL.description/PriceItem.name/Job.code|title/Resource.name|role
- TL-2+TL-6: timeline natural growth + sticky axis CSS (page-scroll invece di widget-scroll)

**Setup post-pull Mac**:
```
git pull
python scripts/migrate_phantom_redesign.py
python scripts/recompute_all_jcl.py
```

**Test backlog**: vedi memory [[test_checklist_alpha171]] — 24 step T1-T24 + 7 regressioni R1-R7.

## (versione precedente)

**v3.5.0-alpha.171** — 19 maggio 2026 — Sprint 1 CR data integrity: ore double-count + voci stima fantasma

Sprint 1 backlog α.171+ (P0 CR data integrity). Backlog completo in memory [[project_backlog_alpha171]].

**CR-2 ore double-count**: nuovo helper `_booking_billable_hours` (max umana || max non-umana). Cost-side somma per-assignment invariato. `HUMAN_RESOURCE_TYPES = {person_internal, person_freelance, person}`.

**CR-1 stima fantasma**: distinzione time-based vs binario.
- Time-based (hr/day): 0 booking → expected=0 (era=quoted)
- Non-time (lump/pc/shot/...): actual=expected=quoted SEMPRE (binario, costi interni dagli assignment)

Smoke logic: T1 Carlo+Sala 8+8 → billable 8 ✓ T2 2 persone+sala 4+6+8 → 6 ✓ T3 2 sale 8+4 → 8 ✓ T4 solo Carlo 8 → 8 ✓.

Prossimo: Sprint 2 — Phantom quote redesign completo ([[project_phantom_quote_redesign]] 8 sub-feature).

Sprint 1 done. Sprint 2-3-4 in coda.

## (versione precedente)

**v3.5.0-alpha.170** — 19 maggio 2026 — Timeline polish (multi-dept + altezza + scroll + click dettagli) + cashflow filtri + anomalie fallback

9 bug aperti da Matteo post α.169 (4 timeline + 2 anomalie + 3 cashflow).

**Timeline**:
- `groupHeightMode: 'fixed'` → `'auto'` (riga 74px non tornava a 39px dopo zoom-out)
- `min/max` range espliciti ±5 anni (scroll orizzontale "si interrompe e non scorre oltre")
- Click singolo su label risorsa → popover esteso (tipo/cost type/email/phone/interno; pre-α.170 solo ruolo/reparto)
- Filtro reparto `<select multiple size=4>` (CSV → backend `_parse_id_list`)

**Anomalie**:
- Filtri cliente/progetto con fallback `OR (col = X, job_id IN subquery)` per record storici con campo NULL
- `/v2/summary` accetta gli stessi filtri della lista (chip si aggiornano)
- Auto-detect alla prima apertura tab nella sessione (`ensureAnomDetectOnFirstOpen`)

**Cashflow**:
- `/by-department` accetta `client_id`/`project_id` (split per reparto era invariato anche con filtri attivi)
- CSS form-input: `height:32px` clippava bottom (descender g/q tagliati) → `min-height:34px + line-height:20px + padding:6px 10px + box-sizing:border-box`
- Bottone "🔄 Aggiorna" + focus/blur listener su `cf-year` (select nativo non emette `change` su same-value)

Smoke:
- planning.html con `RESOURCES_SEED` esteso (6 nuovi campi serializzati) ✓
- `<select multiple>` reparto + CSV roundtrip ✓
- `/finance/api/anomalies/v2?client_id=X` con OR fallback ✓
- `/finance/api/cashflow/{year}/by-department?client_id=X` filtra ✓

## (versione precedente)

**v3.5.0-alpha.169** — 18 maggio 2026 — Timeline sticky axis + refresh CR + anomalie filtri+€-over + invoice qty fix

4 bug aperti da Matteo post α.168.

**Timeline sticky axis**: ripristinato `height+maxHeight=viewport` (α.168 rimosso → axis usciva dal viewport con page-scroll). Scroll INTERNO al widget. CSS `.vis-panel.vis-top z-index:5` reinforced. Toolbar pagina sempre sopra. Counter `N/M risorse` mantenuto.

**Cost Report refresh**: bottone `🔄 Aggiorna` in toolbar dettaglio. Riusa `loadReport(currentJobId)`. Preserva scrollY.

**Anomalie filtri cliente+progetto**: gap UI (backend OK da α.89). Aggiunti 2 dropdown popolati da `/clients/api` + `/projects/api`. Variabili `_anClient`/`_anProject` + handler `onAnomClientChange/onAnomProjectChange`.

**Anomalie sforamento monetario + extra forzato**: `detect_sforamento` esteso (qty | total_accrued > total_quoted | Σ billed > total_quoted). `detect_over_budget` accetta JCL extra con quantity=0 ma billed>0. `emit_invoice` auto-trigger `detect_all` (non blocking).

**Fattura quantity**: `InvoiceLine.quantity = total_approved / unit_price` (era `jcl.quantity_actual`, inflato). Applicato a emit_invoice, compose_invoice, closing_invoice + slice billed_quantity sync.

Smoke:
- detect_sforamento +12 nuove (JCL #18 Production Management €2087 ora visibile) ✓
- detect_over_budget +31 nuove (JCL #66 [EXTRA] Production €426 ora visibile) ✓
- inv_qty recompute coerente con total ✓

Backlog α.170+:
- F29 round 6 i18n granulare modal/form
- Multi-select additional_department_ids in modal listino
- CR dept breakdown ripartizione voci trasversali
- AI capability `propose_advance_allocation` (preset selector)
- OAuth integrazione completa
- Portali consegne plugin reali

## (versione precedente)

**v3.5.0-alpha.168** — 18 maggio 2026 — Vasi comunicanti billing + auto-numero fattura + timeline natural-scroll

4 bug aperti da Matteo dopo testing α.167.

**Bug 1 (timeline 33/40)**: con 40 risorse il cap α.167 (`>100 + Light ON`) NON triggera. Root cause: `maxHeight=tlComputeHeight` clippava la timeline alla viewport → user scroll interno (non scopriva risorse Commercial in fondo). Fix: rimosso `maxHeight`, sostituito `height` con `minHeight` = viewport → timeline cresce naturale, pagina scrolla. Badge diagnostico `N/M risorse` in toolbar.

**Bug 2 (CR post-acconto trasmissibile) + Bug 4 (batch parziale = quotato)**: riarchitettura semantica "vasi comunicanti" (Quote=capienza, CR fill da ore, Billing svuota fino a saturazione).

Formula: `already_filled = slice + APA × paid_ratio` · `billable_now = max(0, accrued − already_filled)` · saturata se `billable_now ≤ 0 AND already_filled > 0`.

- `_transmit_core`: candidates filtrate su `billable_now > 0`. Stati ammessi: `[not_billed, billed, paid]` (porzione over di JCL chiuse trasmissibile).
- `total_proposed=total_approved=billable_now` (era `quoted` per UNDER, inflato; o `accrued` totale, doppia fatturazione).
- JCL `billed/paid` non cambiano status su batch over (supplemento, non chiude).
- `preview_transmission` espone `billable_now`, `already_filled`, `saturated_excluded`.
- `cost_report.py`: payload JCL aggiunge `billable_now`, `transmittable`, `saturated`.
- UI cost_report modal Trasmetti: colonna "Maturato" = billable_now + badge `💧 Già coperto €X`. Banner esclusioni include saturate.

**Bug 3 (numero fattura sempre manuale)**: `_next_invoice_number_for_advance` esisteva solo per acconti. Rinominata `_next_invoice_number` (generica). I 4 endpoint emit/create invoice (create_invoice, emit_invoice, compose_invoice_from_batches, emit_closing_invoice) ora `invoice_number: Optional` + fallback auto `{anno}-{NNNNN}`. Override manuale conservato. UI: 4 modal con placeholder "auto" + label senza obbligo.

Smoke:
- `_next_invoice_number(db, 2026)` → `2026-00114` ✓
- `preview_transmission(p=23)` → 12 candidate, `total_proposed=24845` (era 92770 con quoted-default) ✓
- `_transmit_core` batch 53 con proposed=billable_now ✓ cleaned
- `job_cost_report` JCL marcata `saturated=True` quando accrued=0 + already_filled>0 ✓

## (versione precedente)

**v3.5.0-alpha.167** — 18 maggio 2026 — Timeline limite risorse → Light mode + snapshot cost_rate per stabilità storica

2 bug aperti da Matteo dopo testing α.166:

**Bug 1** Timeline planning: risorse Commercial invisibili senza filtro (α.84 auto-limit a 100). Filtro accorpato a Light mode (🪶 toggle in toolbar). Light ON = limite. Light OFF = tutte le risorse sempre visibili. localStorage `tl_show_all_resources` deprecato.

**Bug 2** Cambio tariffa Resource non aggiornava costo CR. Confermato: per design no retroattivo (cashflow + match SupplierInvoice preservato). Implementato via snapshot pattern:
- `BookingAssignment.cost_rate_snap: Optional[float]` (auto-migrate)
- Listener `booking_assignment_listener.py`: before_insert popola da Resource.internal_cost_hourly. before_update refresh solo se resource_id cambia.
- `cost_line_sync` prefer snapshot, fallback live (back-compat assignment pre-α.167)
- UI Resource modal: avviso giallo "modifiche impattano solo nuovi booking"

Smoke verificato: insert assignment freelance 52€/h → cost_rate_snap=52.0. Swap resource → 123.80€.

## (versione precedente)

**v3.5.0-alpha.166** — 18 maggio 2026 — Riarchitettura acconti: semantica chiara, 4 preset, fattura itemizzata

Root cause aperto da Matteo (cost report Time mostrava Color grading 16.247,80 invece di 11.377,48 atteso): `AdvancePaymentAllocation.pct` aveva semantica ambigua. Modello dichiarava "% di JCL coperta", codice scriveva `amount = AP × pct`. Default pct=1.0 per ogni allocation → N×AP allocato per N JCL, valori incoerenti.

Bundle:
- Modelli: `amount` autoritativo, `pct` derivato (listener auto-sync), `sort_order` nuovo per preset fill_sequential
- Materialize: preset `fill_sequential` default (riempi 100% sequenziale, ultima parziale)
- UI modal: 4 preset (Fill 100% sequenziale / Proporzionale / Pro-rata su residuo / Manuale) + drag handle riordino + input EUR + summary live
- Endpoint nuovo `/finance/api/advances/{id}/preview-preset` per calcolo allocazioni preview
- `allocations_set` accetta sia EUR sia "%" (pct di JCL.quoted) — validazione amount ≤ quoted, Σ ≤ AP
- Cost report OU usa `billed_total` (slice + advance_paid_coverage) → "fill" quando acconto pagato copre voce
- Paid ratio = paid/total (entrambi lordi) invece di paid/AP (mix lordo/netto)
- Fattura acconto itemizzata: N InvoiceLine, una per JCL coperta; residuo → riga "Acconto generale"
- Schedule: pct ⊕ amount_fixed mutual exclusion (400 se entrambi >0)
- 2 migration script: `migrate_advance_alloc_semantics.py` (ricalcolo alloc + fix schedule) e `migrate_advance_invoice_itemize.py` (drop+ricrea InvoiceLine fatture pre-α.166)

Verifica DB sviluppo (Time):
- AP #3 Color: 16.247,80 → 10.431,42 ✓; Production+Title coperti 100% → OU=0 fill ✓
- Invoice #119 itemizzata: 3 lines (10.810 + 5.838,25 + 10.431,42), subtotal invariato

Backlog α.167+:
- F29 round 6: data-i18n granulare modal/form per campo
- Render JS dinamici via mfT() (toast/badge runtime)
- Pluralizzazione + locale-aware date/numeri Intl API
- Multi-select additional_department_ids in modal listino
- CR dept breakdown ripartizione trasversali
- AI capability `propose_advance_allocation` (preset selector)
- OAuth integrazione completa (UI Integrazioni + servizi)
- Portali consegne plugin reali

## (versione precedente)

**v3.5.0-alpha.165** — 17 maggio 2026 notte — i18n sweep header tabelle lista

Audit traduzioni: 110+ chiavi col.* IT/EN/FR/DE, 22 template `<th>` con data-i18n.

## (versione precedente)

**v3.5.0-alpha.164** — 17 maggio 2026 notte — UI listino: dropdown Reparto + checkbox Voce trasversale

UI granulare backend α.163. Modal voce listino con:
- Dropdown Reparto (da /departments/api)
- Checkbox "Voce trasversale" + tooltip

JS: _loadDepts cache + _populateDeptSelect + openNewItem/editItem/saveItem aggiornati.
Backend: GET item espone cross_dept + additional_department_ids. PUT accetta dept=0 → NULL.

## (versione precedente)

**v3.5.0-alpha.163** — 17 maggio 2026 notte — Voci listino trasversali (cross_dept)

Caso Production Management: voce non assegnabile a risorsa via booking (filtro reparto rigido). Soluzione strutturale: price_item.cross_dept=True bypassa filtro.

Modello esteso: cross_dept Boolean + additional_department_ids JSON.
Auto-migrate ALTER + backfill (dept_id NULL → cross_dept=1).
Booking _dept_match: bypass se cross_dept. Planning response: cost_line_cross_dept.
API listino POST/PUT accettano cross_dept.

Versioni intermedie α.161-162:
- α.161 (1e9822e): Colonna Fatturato include acconto pagato (billed_total)
- α.162 (5d8e027): Timeline planning zoomKey:ctrlKey (fix conflitto zoom+scroll wheel)

Backlog α.164:
- UI pricelist modal checkbox "Voce trasversale"
- CR dept breakdown ripartizione voci trasversali
- Multi-dept allocation (additional_department_ids)

## (versione precedente)

**v3.5.0-alpha.160** — 17 maggio 2026 notte — JCL advance_paid_coverage

Fix: pre-α.160 badge "Coperto da acconto" su JCL mostrava allocazione indipendente da pagamento. Acconto NON pagato → mostrava coverage piena fuorviante.

Backend job_cost_report:
- advance_paid_coverage_by_jcl = Σ alloc × (invoice.amount_paid / AP.amount)
- Response JCL include `advance_paid_coverage` campo nuovo

UI:
- Badge `💰 €X · ✓ €Y` (X allocato totale, Y pagato effettivo)
- Tooltip esplicativo + colore verde se paid > 0

Semantica:
- advance_coverage = allocato (ledger)
- advance_paid_coverage = incassato effettivo

## (versione precedente)

**v3.5.0-alpha.159** — 17 maggio 2026 notte — Acconti UX: summary % + Invoice project + CR Pagato/Scomputato

3 fix:
- Modal Gestisci: summary live "N voci · quotato selezionato €X = Y% del progetto"
- Lista fatture: fix acconti project-level (no job_id) ora mostrano progetto. Filter project_id supporta OR via job O diretto.
- CR card Acconti: 4 stat-card (was 3) — distinguono "Pagato (cassa)" da "Scomputato in fatture SAL" (uso contabile ledger).

Semantica: Pagato ≠ Scomputato. Pagato = incassato (cassa). Scomputato = ledger consumato in fatture batch successive.

Backlog α.160:
- Modal Emit preview allocazioni
- CR include fatture project-level (no job)
- Warning over-billing

## (versione precedente)

**v3.5.0-alpha.158** — 17 maggio 2026 notte — Acconti: gestione allocazioni completa

Bug pre-α.158: modal Gestisci mostrava solo allocations esistenti, no add/remove possibile.

Fix:
- Endpoint nuovo `GET /finance/api/advances/{id}/jcls-available` ritorna TUTTE JCL progetto + flag allocated/pct/amount
- `confirm_advance_payment` accetta `allocations_set` CSV "jcl_id:pct,..." sostituzione totale
- UI modal Gestisci: picker JCL completo raggruppato per Job, checkbox + pct input

Verificato: AP.project_id + Invoice.project_id propagation OK in tutti i flow.

468 routes.

Backlog α.159:
- UI modal emit con preview allocazioni
- CR include Invoice project-level
- Warning over-billing

## (versione precedente)

**v3.5.0-alpha.157** — 17 maggio 2026 sera tarda — Cost report OU usa max(accrued, billed)

Fix logico Matteo: OU pre-α.157 usava solo `total_accrued`, ignorando billed_locked > accrued (over-billing). Ora `effective_accrued = max(accrued, billed)` → OU finanziario corretto.

Smoke Vento Aperto Ep. 3 Re-recording: OU_now -37'874 ✓ (era -52'920 fuorviante).

3 punti fix: list_cost_reports, job_cost_report summary, JCL response.

Backlog α.158:
- Colonna "Maturato JCL" + "Effective" esplicite in CR
- Warning UI over-billing (billed >> accrued)
- F29 round 6 granulare

## (versione precedente)

**v3.5.0-alpha.156** — 17 maggio 2026 sera tarda — Dashboard layout + i18n sidebar admin + quotes superseded + CR tooltip

4 fix post-test Matteo:
- Dashboard: row 3 Job+Scadenze (operativo), row 5 Margine reparto+P&L (finanza).
- i18n sidebar Amministrazione (4 voci) + Logout footer (data-i18n aggiunto, chiavi già esistenti).
- `GET /quotes/api` default nasconde superseded (`superseded_by_id IS NULL`), `?include_superseded=true` per drill storico.
- CR tooltip estesi su Fatturato/Maturato post/Over-Under/Margine reale: chiarisce billed_locked (slice immutable) vs total_accrued (work effettivo). Caso "Vento Aperto Ep. 3" = over-billing storico simile Shadow Stagione 3 α.134.

Backlog α.157:
- Colonna "Maturato JCL" esplicito in CR dettaglio
- F29 round 6 granulare modal/form

## (versione precedente)

**v3.5.0-alpha.155** — 17 maggio 2026 sera tarda — Automazione portali consegne foundation

2 modelli nuovi:
- `DeliveryPortal` (config broadcaster, plugin_key, auth_config_enc Fernet)
- `DeliveryUpload` (tracking upload, status workflow pending→uploading→done|failed)

Plugin architecture `app/services/delivery_portals.py`:
- 2 plugin built-in: manual (tracking solo) + generic_http (POST + bearer)
- Plugin futuri: netflix_aspera, amazon_s3, sky_signiant, a24_box
- `execute_upload()` stateful idempotente

Smoke: 2 tabelle create + 2 plugin registrati.

Backlog α.156+:
- Router CRUD portali
- UI tab "Portali consegne" /settings
- UI upload trigger da page deliverables
- Plugin broadcaster-specific reali
- Background queue async

## (versione precedente)

**v3.5.0-alpha.154** — 17 maggio 2026 sera — Parse batch capitolati pendenti

Endpoint `POST /delivery-templates/api/parse-batch-pending?auto_save=true|false`.
Itera corpus 17 file, skippa già parsati, AI parse + auto-save opzionale.
Idempotente. Response: processed[], skipped[], errors[], summary.

Backlog α.155+:
- UI bottone batch parse + progress
- Automazione portali consegne
- UI Integrazioni OAuth

## (versione precedente)

**v3.5.0-alpha.153** — 17 maggio 2026 sera — Cross-currency cost-report aggregati

Cost report list endpoint esteso con `quote_currency`, `quote_fx_rate_to_base`, `base_currency`, `total_quoted_base`, `total_accrued_base`. Pre-fetch tenant.default_currency.

Permette aggregati Σ cross-quote in valuta base (essenziale per dashboard).

Backlog α.154+:
- UI usare *_base per Σ
- Cashflow cross-currency
- Test parse 14 capitolati restanti
- Automazione portali consegne
- UI tab Integrazioni /settings OAuth

## (versione precedente)

**v3.5.0-alpha.152** — 17 maggio 2026 sera — OAuth scaffold: Google + Microsoft

Foundation OAuth 2 Authorization Code flow.

**Modello**: `UserOAuthToken` (user_id, provider, access_token, refresh_token_enc Fernet, expires_at, scopes, account_email).

**Servizio**: `app/services/oauth_providers.py` con dict PROVIDERS + flow start/exchange/userinfo + DB helpers + refresh token encryption.

**Router**: `app/routers/oauth.py` — 4 endpoint (`/status`, `/{provider}/start`, `/{provider}/callback`, `/{provider}/disconnect`).

**Env vars**: `GOOGLE_OAUTH_CLIENT_ID/SECRET`, `MICROSOFT_OAUTH_CLIENT_ID/SECRET`, `OAUTH_REDIRECT_BASE_URL`.

466 routes totale. Smoke tabella + 4 routes ✓.

**Backlog α.153+**:
- UI /settings tab "Integrazioni"
- Servizi send_email/list_drive/upload
- Token refresh auto
- AI capability propose_send_email_oauth
- Cross-currency CR aggregati
- Test parse 14 capitolati
- Automazione portali

## (versione precedente)

**v3.5.0-alpha.151** — 17 maggio 2026 sera — F29 i18n round 5 (finale): modal/form/JS dinamico

~50 chiavi nuove (modal commons 4 + form labels 22 + toast 11 + badge dinamici 5 + generic 12). Tot dict cumulata **~300 chiavi × 4 lingue = ~1200 traduzioni**.

mfT(key) helper esposto window.mfT per JS render dinamico (toast/badge).

**F29 sweep foundation CHIUSO** (5 round α.133+α.147→α.151). Coverage: sidebar/topbar/login/dashboard + 10 template principali.

Round successivi (on-demand):
- Granularità fine modal/form per campo
- Refactor JS render dinamici via mfT()
- Pluralizzazione, date/numeri locale-aware

**Prossimi fronti**:
- α.152 OAuth Gmail/Outlook/Drive/OneDrive
- α.153 Cross-currency cost-report aggregati
- α.154 Test parse 14 capitolati restanti
- α.155 Automazione portali consegne

## (versione precedente)

**v3.5.0-alpha.150** — 17 maggio 2026 sera — F29 i18n round 4: suppliers + resources + departments + settings

~40 chiavi nuove. Tot dict cumulata **~250 chiavi × 4 lingue = ~1000 traduzioni**.
Foundation F29 completa sui 10 template principali.

Backlog:
- JS dinamico mfT() per toast/render
- data-i18n granularità fine su modal/form

## (versione precedente)

**v3.5.0-alpha.149** — 17 maggio 2026 sera — F29 i18n round 3: planning + finance + cost-report

~50 chiavi nuove (planning 17 + finance 16 + cr 17). Tot dict ~210.
data-i18n: finance tab + bottone + 3 card titoli, cr table headers, planning bottone Booking.
Cache buster bumpato.

Backlog F29 round 4 (α.150): suppliers + resources + departments + settings + JS dinamico mfT().

## (versione precedente)

**v3.5.0-alpha.148** — 17 maggio 2026 sera — F29 i18n round 2: clients + projects + quotes

~40 chiavi nuove (clients 11 + projects 11 + quotes 19). Tot dict ~160 chiavi.
data-i18n applicati a clients.html, projects.html, quotes.html (titoli card, bottoni, search placeholder, table headers).
Cache buster bumpato 147→148.

Backlog F29:
- Round 3 (α.149): planning + finance + cost-report
- Round 4 (α.150): suppliers + resources + departments + settings
- JS dinamico via mfT() finale

## (versione precedente)

**v3.5.0-alpha.147** — 17 maggio 2026 sera — F29 i18n round 1: dashboard + common keys

~60 chiavi i18n nuove (dashboard 20 + col headers 12 + buttons 14 + status 11 + misc).
Cache buster i18n.js bump 133→147.

Backlog F29:
- Round 2 (α.148): clients + projects + quotes
- Round 3 (α.149): planning + finance + cost-report
- Round 4 (α.150): suppliers + resources + departments + settings
- JS dinamico (toast/render) via mfT() helper finale

## (versione precedente)

**v3.5.0-alpha.146** — 17 maggio 2026 pomeriggio tarda — Workflow acconti Step 4/4: CR fill mode + badge JCL

Chiusura ciclo acconti Pattern B end-to-end (4 step completati: α.139 termini quote → α.144 hook auto-create → α.145 UI bozze + emit → α.146 fill mode CR).

CR job endpoint: pre-fetch advance_coverage_by_jcl + per-JCL advance_coverage/drift/overflow.
UI: badge inline `💰 €X · drift Y` con bordo rosso se overflow.

Backlog α.147+:
- F29 round 1: dashboard + sidebar + topbar
- F29 round 2: clients + projects + quotes
- F29 round 3: planning + finance + cost-report
- OAuth, cross-currency aggregati

## (versione precedente)

**v3.5.0-alpha.145** — 17 maggio 2026 pomeriggio tarda — Workflow acconti Step 3/4: UI /finance Bozze + emit

3 endpoint nuovi:
- `GET /advances/pending-draft` — lista tenant-wide pending/draft/confirmed
- `POST /advances/{id}/confirm` — update + transition pending→draft|confirmed
- `POST /advances/{id}/emit-invoice` — crea Invoice(kind=advance) + lega + status=invoiced

UI /finance:
- Tab "💰 Bozze acconti" con badge count
- Sezione lista compatta con status badge + actions
- Modal Gestisci (allocations pct + 3 azioni: bozza/conferma/emetti)
- Modal Emit Invoice

Deprecazione /cost-report:
- Bottone "+ Crea acconto" rimosso (link "→ Gestisci in /finance")
- Card sola lettura per visualizzazione

Smoke E2E: materialize→pending→confirm→emit→invoiced ✓ Invoice creata ✓.

**Backlog α.146**:
- CR fill mode (Coperto/Maturato/Drift per JCL via AdvancePaymentAllocation)
- Warning sforamento Σ AP+maturato > quote
- F29 i18n, OAuth, cross-currency aggregati

## (versione precedente)

**v3.5.0-alpha.144** — 17 maggio 2026 pomeriggio tarda — Workflow acconti: hook converti quote→job

Step 2/4 revisione architetturale acconti (piano α.139). Hook al converti quote→job materializza schedule → AP(pending) + alloc + Notification admin.

**Modelli**:
- `AdvancePaymentAllocation` M:N AP↔JCL (foundation CR fill mode α.145).
- AP esteso: `invoice_id` NULLABLE (SQLite table rebuild runtime), `quote_advance_schedule_id` (origine), `scheduled_due_date`, `label`.

**Servizio `advance_schedule_to_payment.materialize_schedules`**:
- Idempotente (skip se `quote_advance_schedule_id` già materializzato).
- Compute due_date da anchor (4 opzioni: quote_approved/project_start/specific_date/milestone).
- Mappa QuoteLine→JCL via JCL.quote_line_id.
- Notification admin/manager con body completo + link `/finance#section-invoices`.

**Hook `_create_job_from_quote`** chiama materialize fail-soft post-flush.

**Smoke E2E**: Quote 47 + schedule 30% + 2 alloc → 2 AP pending €43k cad. + 2 alloc cad. + 4 notify ✓. Re-run idempotente skip ✓.

**Backlog α.145+**:
- UI /finance "Bozze acconti" + workflow conferma/emit (deprecazione modal CR)
- CR fill mode (Coperto/Maturato/Drift per JCL)
- F29 i18n sweep, OAuth, cross-currency aggregati

## (versione precedente)

**v3.5.0-alpha.143.1** — 17 maggio 2026 pomeriggio tarda — HOTFIX cashflow filtri + anni dup

Matteo segnala α.142 NON risolti + 1 nuovo bug:
- **Anni duplicati** select: `initYearSelect()` chiamato 2 volte. Fix: guard idempotente + rimossa doppia chiamata.
- **Filtri cli/proj non funzionanti**: MFAutocomplete → sostituito con `<select>` nativo. Auto-filter progetti per cliente.
- **Anno onchange**: addEventListener esplicito + log.
- **`/jobs/api` inesistente** α.143 modal fattura → fix `/planning/api/jobs`.
- **NC banner**: link cliccabile + lista primi 10 ID. DB demo: 0 invoice senza date (banner non appare se count=0).

## (versione precedente)

**v3.5.0-alpha.143** — 17 maggio 2026 pomeriggio — Fatturazione: crea fattura ampliato + acconti visibili

**Crea fattura**: modal con cascade cliente→progetto→quote→job→JCL. Force checkbox se senza link strutturato (400 sconsigliato).
- Backend `POST /finance/api/invoices` accetta project_id/quote_id/job_id/jcl_id + force.
- Frontend `openNewInvoiceModal()` con cache + cascade auto-populate bidirezionale.

**Acconti visibili in Fatturazione**: card "💰 Acconti aperti" in tab Fatture.
- Backend nuovo `GET /finance/api/advances/open` (tenant-wide, status=open, balance>0).
- Frontend `loadOpenAdvances()` mostra lista compatta: numero · progetto · status · importi · bottone Apri.

**Smoke**: 459 routes · render OK · endpoint `/finance/api/advances/open` registrato.

**Backlog α.144+** (workflow acconti):
- Hook converti quote→job auto-create AP(pending) da schedule + Notification admin
- UI bozze acconti + workflow conferma/emit
- CR fill mode (Coperto/Maturato/Drift per JCL)
- F29 i18n sweep TUTTA UI
- OAuth, cross-currency aggregati

## (versione precedente)

**v3.5.0-alpha.142** — 17 maggio 2026 pomeriggio — Cashflow 3 fix

- **#1** Year dropdown vuoto in apertura: `initYearSelect()` mai chiamato. Fix.
- **#2** Filtri cli/proj non funzionanti: MFAutocomplete CSV → FastAPI int rifiuta 422. Backend → str + parse CSV + `.in_(ids)` su 5 filtri SQL.
- **#3** NC senza data permaneva in cashflow gennaio fallback. Fix: skip + banner amber UI con lista invoices_missing_date.

**Smoke**: filtri CSV `project_id='12,8'` + `client_id='1'` → 12 months OK.

**Backlog α.143**:
- Crea fattura ampliato (dropdown cli/proj/quote/job/lavorazione + force no-link)
- Acconti visibili in fatturazione (lista AP pending/draft)

## (versione precedente)

**v3.5.0-alpha.141** — 17 maggio 2026 mattina — Anomalie: 7 fix UX/workflow

Backend:
- `list_anomalies` filtro `department_id` (subquery JCL→price_item)
- `_handle_single` + `handle_anomaly` accettano `target_user_id` + `next_action_label`
- Per rimanda/rivaluta → Notification a destinatario (kind=custom, severity=action_required, body completo)

UI /finance #section-anomalies:
- Legenda collassabile (6 tipi + 5 azioni con side-effects)
- Filtro chip dipartimento (dropdown da /departments/api)
- Checkbox auto-rileva (setInterval 10min)
- Cell progetto = `{code} — {title}`
- Modal `#modal-anom-handle` sostituisce prompt() numerico: dropdown azione + tooltip side-effect + target user + next_action select condizionali
- ACTION_LBL `overhead_cost` → "Dirotta su spese aziendali"

**Backlog α.142+**:
- α.142 Cashflow 3 fix (auto-load anno, filtri cli/proj, NC senza data)
- α.143 Crea fattura ampliato + acconti visibili
- α.144+ workflow acconti (auto-create AP pending al converti quote→job)

## (versione precedente)

**v3.5.0-alpha.140.1** — 17 maggio 2026 mattina — HOTFIX loadQuote → reloadQuote

**Bug**: aggiunta/cancellazione/modifica rata acconto + cambio valuta non aggiornavano UI.
**Root cause**: `loadQuote(id)` inesistente, era `reloadQuote()`. Introdotto α.137 + α.139.
**Fix**: 4 replace (changeQuoteCurrency, refreshQuoteFx, submitAdvanceSchedule, deleteAdvanceSchedule).

Backend OK (smoke pre-fix confermava GET/POST/DELETE corretti).

## (versione precedente)

**v3.5.0-alpha.140** — 17 maggio 2026 mattina — UX quote: accorpamento condizioni + modal rata bidirezionale + cards collassabili

5 fix UX richiesti Matteo prima di procedere con hook auto-create AP (slittato a α.141):

- **q1** Card "Termini acconto" separata RIMOSSA. Accorpata in card "Condizioni economiche & scadenze" (periodicità + acconti vivono insieme).
- **q2** Modal rata bidirezionale pct↔amount via oninput. Display selezione voci: "N voci · totale €X = Y% del preventivo" + warning ⚠ se pct manuale ≠ pct allocato.
- **q3** Rata salvata visibile: verificato già funziona (loadQuote post-save).
- **q4** Cards collassabili con persistenza localStorage. 6 cards taggate `data-collapsible="key"`. Helper `initCollapsibles()` idempotente.
- **q5** Audit cambio valuta: `_recalc_quote` + `quote_pdf.py` NON usano fx_rate/currency. Solo snapshot tasso. Tooltip esplicativo aggiunto.

**Backlog α.141+**:
- α.141 hook converti quote→job auto-create AP(pending) + notifica admin (slittato da α.140)
- α.142 UI /finance "Bozze acconti" + workflow conferma + emit (deprecazione modal CR)
- α.143 CR fill mode (Coperto/Maturato/Drift)
- F29 i18n sweep TUTTA UI
- OAuth integrazioni

## (versione precedente)

**v3.5.0-alpha.139** — 17 maggio 2026 mattina — Revisione architetturale acconti: termini in quote + workflow stateful

**Cambio scope architetturale richiesto Matteo** dopo α.138: acconti vanno definiti in quotazione (no manuale in CR), emessi da /finance (notifica + bozza + conferma + emit), CR visualizza fill maturato/drift.

**Piano** (4 versioni):
- α.139 (questa): foundation termini in quote
- α.140: auto-create AP pending al converti + notifica admin
- α.141: UI /finance bozze acconti + workflow conferma/emit
- α.142: CR fill mode (Coperto/Maturato/Drift per JCL coperta)

**α.139 deliverables**:
- Modelli `QuoteAdvanceSchedule` + `QuoteAdvanceAllocation` + `AdvanceDueAnchor` enum.
- `AdvancePaymentStatus` esteso workflow stateful: pending → draft → confirmed → invoiced → paid → consumed (open legacy alias).
- Auto-migrate create_all (no ALTER, tabelle nuove).
- 4 endpoint CRUD `/quotes/api/.../advance-schedules` + GET quote esposto `advance_schedules`.
- UI quote editor: card "💰 Termini di acconto" + modal add/edit (label, pct/amount, anchor 4 opzioni, offset/date/milestone, allocation opz. a QuoteLine via checkbox+%).
- DOM via createElement/textContent.

**Smoke E2E** (quote 7 Q-2024-0003): create schedule 30%+2 alloc ✓ update pct 0.30→0.35 ✓ serialize via GET quote ✓ delete cascade ✓.

**Compat**: α.136-138 ledger AdvancePayment + scomputi consumption restano attivi. UI cost-report "Crea acconto" sarà deprecato in α.141.

**Backlog α.140+**:
- α.140 hook converti quote→job: auto-create AP(pending) + Notification advance_pending
- α.141 UI finance bozze + emit
- α.142 CR fill mode
- F29 i18n sweep TUTTA UI
- Conversione cross-currency cost-report aggregati
- OAuth Gmail/Outlook/Drive/OneDrive

## (versione precedente)

**v3.5.0-alpha.138** — 17 maggio 2026 mattina — Acconti Step 2: scomputo automatico + auto-scompute closing

Chiude il ciclo acconti aperto in α.136. Pattern B completo end-to-end.

**Backend**:
- Helper `_apply_advance_consumptions` (billing.py) crea InvoiceLine negativa + AdvancePaymentConsumption + riduce balance + auto-status consumed.
- `emit_invoice`, `compose_invoice_from_batches`: accettano `advance_consumptions` CSV `"id:amt,id:amt"`.
- `emit_closing_invoice`: **auto-scompute FIFO** di tutti gli AP open del progetto fino esaurire subtotal. `advance_overflow_open` warning se residuo non scomputabile.
- Invoice.project_id linkato direttamente per batch/closing.
- Cost Report list + job detail estesi con `advance_amount` / `advance_consumed` / `advance_balance` + `advance_overflow_flag`.

**UI**:
- Modal `/finance` emit batch: sezione "💰 Scomputo acconti aperti" con checkbox + input importo + auto-suggest + recalc live totali.
- CR card "Acconti progetto" (preesistente α.136) si aggiorna con i consumi nuovi.

**Smoke E2E**: 2 AP €3000+€2000 su Shadow → scomputo €1500+€500 (sub 5000→3000) ✓ full consume → status=consumed ✓ over-consume 409 reject ✓.

**Backlog α.139+**:
- F29 i18n sweep TUTTA UI (~500-1000 chiavi IT/EN/FR/DE)
- Conversione cross-currency in cost-report aggregati
- OAuth Gmail/Outlook/Drive/OneDrive
- Test parse 14 capitolati restanti

## (versione precedente)

**v3.5.0-alpha.137** — 17 maggio 2026 mattina — Multi-currency Quote + Settings valuta base + FX live (Frankfurter BCE)

Richiesta diretta Matteo: valuta base nelle impostazioni + quotazioni in dollari con conversione live.

**Implementato**:
- Modello `FXRate` (cache 1h, single row per coppia, UniqueConstraint).
- Quote estesa: `currency` + `fx_rate_to_base` + `fx_rate_fixed_at`.
- Servizio `app/services/fx.py` provider Frankfurter (free, no key, fail-soft).
- Auto-migrate: fx_rates created + quotes ALTER.
- Endpoint `/finance/api/fx/{from}/{to}` (refresh on-demand).
- POST/PUT /quotes accettano `currency` + `refresh_fx`. Cambio bloccato post-emissione.
- UI Settings tab Azienda: dropdown 8 valute.
- UI Quote editor: card valuta + dropdown live + bottone 🔄 refresh tasso (createElement, no XSS).

**Smoke FX live**: USD→EUR 0.85999, EUR→USD 1.1628, GBP→EUR 1.1488, convert 1000 USD = €859.99 ✓.

**Backlog α.138+**:
- Acconti Step 2 (scomputo automatico nelle fatture batch successive + closing auto-scompute).
- F29 i18n sweep TUTTA UI (~500-1000 chiavi IT/EN/FR/DE).
- Conversione cross-currency in cost-report aggregati (project quote USD vs base EUR).
- OAuth Gmail/Outlook/Drive/OneDrive.
- Test parse 14 capitolati restanti.

## (versione precedente)

**v3.5.0-alpha.136** — 17 maggio 2026 mattina — Acconti progetto Step 1 (Pattern B ledger AdvancePayment)

Risposta al gap evidenziato da Matteo dopo α.135: "fattura manuale non si lega a progetto/lavorazione, serve modalità pagamento anticipato nel CR".

**Step 1 implementato**:
- Modelli: `AdvancePayment` + `AdvancePaymentConsumption` + `InvoiceKind` + `AdvancePaymentStatus`.
- Invoice estesa: `kind` (regular/advance/balance) + `project_id` (link diretto, multi-job).
- Auto-migrate al boot: create_all + ALTER invoices.
- 3 endpoint: `POST /finance/api/projects/{id}/advances` (crea Invoice kind=advance + ledger), `GET /finance/api/projects/{id}/advances` (lista + totali), `POST /finance/api/advances/{id}/cancel`.
- UI cost-report dettaglio: card "💰 Acconti del progetto" + modal "Crea acconto" + bottone Annulla.

**Smoke E2E** su Shadow (job 9): create €5'000 → invoice 2026-00112 + AP id=1 ✓ list ✓ cancel ✓ cleanup ✓.

**Backlog α.137 (Step 2 acconti + multi-currency)**:
- Scomputo nelle fatture batch successive (estensione emit_invoice + closing auto-scompute residuo + UI cost report colonna "coperto da acconto").
- Settings valuta base: `Tenant.base_currency` (EUR default).
- FXRate cache + provider Frankfurter (BCE, free, no key).
- Quote multi-currency: `Quote.currency` + `Quote.fx_rate_used` + UI dropdown valuta con conversione live.

**Backlog α.138+**:
- F29 i18n sweep TUTTA UI (~500-1000 chiavi, IT/EN/FR/DE per pagina), aggiunge anche stringhe JS dinamiche via `mfT()` helper.
- Test parse 14 capitolati restanti.
- OAuth integrazioni.
- Automazione portali consegne.

## (versione precedente)

**v3.5.0-alpha.135** — 17 maggio 2026 mattina — F26/F27/F30 coerenza CR↔Fatturazione (pattern B) + F28 root cause

**Bundle architetturale "Coerenza CR↔Fatturazione"** chiuso con pattern B (trasparenza UI, no riarchitettura).

**F28 debug** — root cause documentato. Mismatch Invoice.subtotal vs Σ slice in Shadow è artifact `seed_stress.py` (STAGE 9 invoice manuali + STAGE 14 batch+slice disaccoppiati). In production reale, riproducibile solo combinando `POST /finance/api/invoices` manuale + `emit-invoice` batch su stessa entità. NON bug.

**F26 backend** — `cost_report` list + job endpoint estesi con:
- `invoiced_net` (Σ Invoice.subtotal imponibile, TD04 sottratto sign -1)
- `billed_admin_net` = invoiced_net − billed_locked (= fatturato non agganciato a slice)
- `admin_flag` se |delta| > 5% quotato

**F27 backend** — `fake_billing_count` (job) + `fake_billing` boolean (line) = JCL billed/paid con accrued=0.

**UI**:
- Lista CR: badge `⚠ admin ±€X` + `⚠ fake-bill N` nella riga del job
- Dettaglio CR: KPI card "Fatturato totale" (di cui admin) + card `⚠ Fake billing` se count > 0
- Riga voce di costo: badge `⚠ no-work` se fake_billing

**Smoke Shadow Stagione 3** (job 9):
- invoiced_net €36'794,81 ✓
- billed_locked €11'975,29 ✓
- billed_admin_net €24'819,52 (67% fantasma) ✓ admin_flag=True
- fake_billing_count 7/7 paid senza ore ✓

**F30** risolto dalle stesse modifiche (visibilità split slice vs invoice totale = "voce fatturazione" ora corretta).

**Backlog α.136+**:
- F29 i18n sweep completo (~500-1000 chiavi, lavoro pesante spalmato su round)
- Test parse 14 capitolati restanti (UI 1-by-1)
- OAuth integrazioni Gmail/Outlook/Drive/OneDrive
- Automazione portali consegne

## (versione precedente)

**v3.5.0-alpha.134** — 16 maggio 2026 notte tarda — F25 widget Quotato vs Fatturato + analisi Shadow

**Finding architetturale Shadow Stagione 3**:
- Quote €44'889 fatturato €44'889 incassato €44'889 — apparentemente coerente.
- MA: bookings done 0/14, JCL accrued €0, Σ slice solo €11'975 (= 27% del fatturato).
- €24'820 (67%) "fatturato fantasma" non agganciato a JCL via slice → fatture manuali "Acconto/SAL/Saldo".

**F25 fix immediato**: card "📊 Quotato vs Fatturato per progetto" in /finance#invoices (collassabile, lazy load). 8 colonne con warning visivo se admin_net > 5% quotato. Endpoint `GET /finance/api/project-billing-summary` (43 progetti listati su DB demo).

**F26/F27/F28 documentati per α.135+** (decision design):
- F26 disaccoppiamento Invoice.lines vs JCLBilledSlice
- F27 JCL billing_status="paid" + booking 0 done → semantica fuorviante
- F28 mismatch slice billed_amount vs Invoice.subtotal

Findings completi in memoria [[project_alpha134_findings]].

**Backlog α.135+**:
- Design F26/F27/F28 → implementare pattern decision
- Estensione i18n a dashboard/pagine principali (α.133 sweep)
- Continuazione capitolati / OAuth / portali

## (versione precedente)

**v3.5.0-alpha.133** — 16 maggio 2026 notte tarda — i18n GUI base IT/EN/FR/DE

**Sistema i18n client-side**:
- `app/static/js/i18n.js` (NEW): dictionary `MF_I18N = {key: {it,en,fr,de}}` + `applyI18n()` DOM scanner + `mfSetLang(lang)` + popover handler.
- Persistenza `localStorage.mf_lang`. Default IT. Fallback IT → key letterale.
- Markup: `data-i18n="key"` su elementi. Opzionale `data-i18n-attr="placeholder|title"` per attributi.
- Preserva figli (nav-icon interno): modifica solo primo text node.

**Switcher topbar**: 🇮🇹/🇬🇧/🇫🇷/🇩🇪 popover sticky. Stesso pattern F4 theme picker.

**Scope α.133**: ~50 chiavi (sidebar nav + topbar + login). Resto UI in IT, espandibile via data-i18n.

**Smoke**: 37 data-i18n in /dashboard, switcher presente, scripts caricati.

**Backlog α.134+**:
- Estensione i18n a dashboard/pagine principali
- Server-side i18n per messaggi error toast
- Date/numeri locale-aware (Intl API)
- Parse batch capitolati
- OAuth integrazioni

## (versione precedente)

**v3.5.0-alpha.132** — 16 maggio 2026 notte tarda — DeliveryTemplate export JSON + duplica

**QoL /delivery-templates**:
- `GET /api/{id}/export-json`: download template come JSON (backup/share)
- `POST /api/{id}/duplicate`: deepcopy 8 blocchi + suggested_items, code/name suffix "-copy"/"(copia)", ai_generated=False (è bozza manuale)
- UI bottoni ⬇ (export) + 📋 (duplica) nella tabella

**Smoke**: 404 corretti su id inesistente, routes registrate.

**Backlog α.133+**:
- Parse batch UI 1-by-1
- OAuth Gmail/Outlook + Drive/OneDrive
- Automazione portali consegne

## (versione precedente)

**v3.5.0-alpha.131** — 16 maggio 2026 notte tarda — Fase 5 corpus diagnostica + parse on-demand

**Diagnostica corpus capitolati**:
- Endpoint `GET /delivery-templates/api/samples-status` (15 file, stats parsati/pending)
- UI card "📚 Corpus capitolati di riferimento" in /delivery-templates con tabella 6 colonne
- Bottone "✨ Parse" per ogni capitolato non ancora analizzato → auto-save template

**Smoke**: stats endpoint = 15 total / 0 parsed / 15 pending (DB demo vuoto).

**Backlog α.132+**:
- Esecuzione parse batch (manuale 1-by-1 da UI per controllare costo AI)
- OAuth integrazioni (Gmail/Outlook, Drive/OneDrive)
- Automazione portali consegne

## (versione precedente)

**v3.5.0-alpha.130** — 16 maggio 2026 notte tarda — AI capability propose_send_invoice_email + refactor email helper

**Seconda capability AI estesa (no OAuth, riusa SMTP α.127)**:
- `propose_send_invoice_email` (mutation): invio fattura via email cliente con PDF allegato. Conferma utente Apply.
- Args: invoice_id | invoice_number (lookup fallback) | recipient_override
- Refactor logica SMTP in `app/services/invoice_email.py` (`send_invoice_via_smtp` + `InvoiceEmailError`). ~100 righe deduplicate.
- Endpoint HTTP α.127 riusa helper, zero regressione shape response.

**Smoke E2E**: 3 casi pass (missing args, lookup miss, SMTP not configured).

**Capabilities totali: 33** (era 32, +1 send_invoice_email).

**Backlog α.131+**:
- OAuth integrazioni vere (Gmail/Outlook ricezione+reply, Drive/OneDrive upload)
- Automazione portali consegne
- Test parse 14 capitolati restanti

## (versione precedente)

**v3.5.0-alpha.129** — 16 maggio 2026 notte tarda — AI capability query_filesystem

**Prima capability AI estesa "filesystem"**:
- `query_filesystem` (readonly): list path locale con whitelist tenant + glob + depth/results limits
- Sicurezza: path traversal protection, hard cap depth ≤ 8 e results ≤ 500
- Tool descriptor `ai_tools.py` con input_schema completo
- Pattern uso: "cosa c'è in /mnt/asset_library/PROJ-X/", "elenca .mov consegnati", ecc.
- Capabilities totali: 32 (era 31)

**Smoke E2E**: 4 casi pass (no whitelist→reject, autorizzato→OK, glob→filtra, fuori whitelist→reject).

**Backlog α.130+**:
- AI capability email (OAuth) - design preliminare
- AI capability Drive/OneDrive (OAuth)
- Automazione portali consegne
- Test parse 14 capitolati restanti

## (versione precedente)

**v3.5.0-alpha.128** — 16 maggio 2026 notte tarda — Fase 5 capitolati quick-load esempi

**Fase 5 audit + bundle**:
- Codice scaffolded già presente (deliverables_parser, delivery_templates router, wizard 3-step).
- Smoke parser AI: A24 Queer DOCX → confidence 0.88, 8 blocchi popolati.
- Nuovo endpoint `GET /api/sample-files` lista 15 capitolati corpus.
- Nuovo endpoint `POST /api/parse-sample` parse senza upload (path traversal safe).
- UI wizard: card "Capitolati di esempio" con pill cliccabili per quick-load.
- Path conflict fix: sample-files PRIMA di {template_id} per evitare 422.

**Backlog α.129+**:
- Test sistematico parse dei 15 capitolati restanti
- Seed batch DeliveryTemplate dal corpus
- Capability AI estese (email/Drive/Office OAuth)

## (versione precedente)

**v3.5.0-alpha.127** — 16 maggio 2026 notte tarda — P2.C F11 supplier↔resource inverso + F6 invio email SMTP

**Gruppo P2.C chiuso. BACKLOG P2 COMPLETAMENTE CHIUSO** (24/24 finding del 16 mag).

**F11 — Flusso inverso supplier↔resource**:
- Rimosso bottone "+ Crea risorsa" da modal supplier (era flusso sbagliato).
- Dropdown supplier filtra SOLO freelance.
- Nuovo endpoint `POST /resources/api/{id}/generate-supplier` (solo freelance, idempotente). UI: bottone "🏢 Genera fornitore collegato" in modal resource (visibile solo per freelance già salvati).

**F6 — Invio fattura via email cliente**:
- Endpoint `POST /finance/api/invoices/{id}/send-email`. SMTP stdlib, provider-agnostic via .env (SMTP_HOST/PORT/USER/PASS/FROM/USE_TLS). Compatibile Gmail, Microsoft 365, AWS SES, Mailgun, SendGrid, Postmark, etc.
- Risolve destinatario: admin_email_snap > admin_email live > contact_email.
- Subject auto + body con totali + PDF allegato.
- UI: bottone ✉ in lista fatture e detail modal.
- Skip-graceful: 503 se SMTP non configurato, 400 se cliente senza email, 502 SMTP fallito.

**Storia 16 mag 2026** (10 commit):
- α.119 cost_external priority + auto-dismiss drift
- α.120 6 fix P0
- α.121 7 fix P1
- α.122 sweep JCL→Lavorazione
- α.123 IVA toggle + split reparti
- α.124 naming builder modal
- α.125 fallback id + ratio precise
- α.126 revamp 3 pagine + filtri
- α.127 supplier↔resource + SMTP send
- + docs ARCHITETTURA.md

**Backlog α.128+**:
- Test UI Matteo dei fix accumulati
- Bug emersi da uso reale
- Eventuali feature nuove (Fase 5 capitolati F14/F15, AI capability estese)

**Side-effect DB α.127**: Supplier #11 "Francesca Ferrari" creato + linkato Resource #26 (test E2E).

## (versione precedente)

**v3.5.0-alpha.126** — 16 maggio 2026 notte tardi — P2.E revamp /team /resources /departments + filtri

**Gruppo P2.E chiuso**:
- Purpose chiarito via sub-title topbar (Lista / Vista per reparto / Configurazione)
- Banner header esplicativo + navigazione bidirezionale topbar fra le 3 pagine
- Filtri /resources estesi: search live client-side + toggle "Mostra inattive" server-side
- Backend param include_inactive su GET /resources

**Backlog P2 rimanente per α.127+**:
- P2.C: F11 supplier↔resource inverso + F6 admin_email SMTP send (richiede design SMTP provider)

## (versione precedente)

**v3.5.0-alpha.125** — 16 maggio 2026 notte tardi — P2.A.2 sweep fallback id + F19 ratio_net precision

**Bundle leggero**:
- P2.A.2: assets_inout fallback `#${id}` → label/serial_number/barcode descrittivo, oppure "(senza nome)".
- F19: revenue_net da `/1.22` medio a query precisa `CASE WHEN total>0 THEN amount × subtotal/total` SQL. Corretto per vat ≠ 22%.

**Smoke**: numeri identici su DB attuale (tutte fatture vat 22%) ma query coerente per casi non-standard.

**Backlog P2 rimanente per α.126+** (design discussion preliminare):
- P2.C: F11 supplier↔resource inverso + F6 admin_email SMTP send (provider?)
- P2.E: revamp /team /resources /departments (F21)

## (versione precedente)

**v3.5.0-alpha.124** — 16 maggio 2026 notte tardi — F7a/F7b naming builder: modal centrato + editor inline

**Gruppo P2.D chiuso**:
- F7a: builder ora modal centrato (no più drawer fisso a sinistra). Stile standard `.modal`.
- F7b: editor inline. Input text raw editabile + palette variabili click-to-insert al caret position. Preview live debounced. Dead code drag&drop rimosso.

**Smoke**: /settings render OK, 0 occorrenze codici legacy `nmb-blocks-active` / `nmb-custom-text`.

**Backlog P2 rimanente per α.125+**:
- P2.A.2: audit globale `#${id}` user-facing
- P2.C: F11 supplier↔resource inverso + F6 admin_email SMTP send
- P2.E: revamp /team /resources /departments (F21)
- F19 ratio_net precision

## (versione precedente)

**v3.5.0-alpha.123** — 16 maggio 2026 notte tardi — F16 IVA toggle + F19 split cashflow per reparto

**Gruppo P2.B chiuso**:
- F16 totali fatture+cashflow SENZA IVA di default. Toggle "Mostra IVA" persistente localStorage. Backend ritorna campi paralleli `*_net` (imponibile) accanto a totali.
- F19 split cashflow per reparto annuale. Endpoint `/api/cashflow/{year}/by-department` (revenue via JCLBilledSlice→JCL→PriceItem.department, supplier via Resource.department). Card UI nuovo sotto chart.

**Smoke E2E**: cashflow `_net` coerente (~82% ratio), 4 reparti aggregati ordinati per revenue_net.

**Backlog P2 rimanente per α.124+**:
- P2.A.2: audit globale `#${id}` user-facing
- P2.C: F11 supplier↔resource inverso + F6 admin_email send SMTP
- P2.D: naming drawer (F7a center popup, F7b inserimento inline)
- P2.E: revamp /team /resources /departments (F21)
- F19 ratio_net precision (join per invoice per ratio esatto invece di /1.22)

## (versione precedente)

**v3.5.0-alpha.122** — 16 maggio 2026 notte — F17/F24 sweep terminologia JCL→Lavorazione + nascondi id interni

**Primo step backlog P2 architetturale** (gruppo A "Visualizzazione globale").

**Sweep parziale**: 5 rinomine user-facing nei template più impattanti (assets_inout, cost_report, manuale, quotes). "Lavorazione" come termine UI canonico per JobCostLine. Rimossi `#${id}` numerici dai badge.

**Backlog P2 rimanente per α.123+**:
- P2.A.2: audit globale fallback `#${id}` (assets_inout, planning)
- P2.B: cashflow architettura (F16 IVA default off, F19 split reparti)
- P2.C: flusso resource/supplier (F11 inverse, F6 admin_email send + SMTP)
- P2.D: naming drawer (F7a center popup, F7b inserimento blocchi inline)
- P2.E: revamp /team /resources /departments (F21)

## (versione precedente)

**v3.5.0-alpha.121** — 16 maggio 2026 tarda notte — 7 fix UX P1 da backlog α.120

**7 finding P1 UX chiusi**:
- F4 palette tema sticky toggle (no più hover-driven close)
- F5 chip filtro cliente visibile in /projects?client_id
- F7c naming pattern riflesso nel modal Nuova Quotazione (esteso ad altri modal in round successivi)
- F8 overhead write-off drawer: endpoint `/overhead/api/losses` dedicato (LossEntry source)
- F18 lista fatture: click row → drawer dettaglio + hide select status se terminal
- F20 componi fattura: bottone "Aggrega con N batch" in batch detail se composable > 1
- F10/F23 fattura passiva: dropdown "Lavorazione" (JCL) cascata Project→Job→JCL

**B5 verificato già funzionante**: chip "Drift costo" presente statico, summary card sempre renderizzata (no actionable change).

**Smoke E2E**: endpoint nuovi `/overhead/api/losses` (458+ LossEntry) e `/finance/api/invoices/{id}` (113 paid con allowed_transitions=[] terminal) OK.

**Backlog α.122+ — P2 architetturale (10 finding, design discussion)**:
F6 admin_email send semantica, F7a drawer center popup, F7b inserimento blocchi inline, F11 supplier↔resource flusso inverso, F16 IVA default off, F17 terminologia JCL→lavorazione globale, F19 cashflow split reparti, F21 UX revamp team/resources/departments, F24/F9 sweep codici DB.

## (versione precedente)

**v3.5.0-alpha.120** — 16 maggio 2026 tarda sera — 6 fix P0 da checklist post-audit α.114-118

**6 finding bloccanti chiusi**:
- F3 CR lista valori falsi al primo render (force=1 reconcile per JCL job attivi)
- F12 Cashflow NC TD04 ignorata (NC nasce sent, non draft)
- F13 Cashflow no aggiornamento outstanding post status paid (auto amount_paid=total)
- F14 PDF fattura cancelled stampabile (backend 409 + UI bottone disabled)
- F15 PDF NC manca progetto + voci duplicate (banner project + aggregazione TD04 in 1 riga)
- F22 Resource.supplier_id delink form vuoto (Request.form() raw parsing)

**Smoke E2E**: tutti 6 fix verificati server-side. Esempi: F22 5 casi pass, F3 350/484 JCL aggiornate al force, Voice of Tide Ep. 3 ora coerente al primo render.

**Backlog α.121 — P1 UX (8 finding)**:
F4 palette sticky, F5 chip filtro cliente nome, F7c naming pattern non riflesso UI, F8 overhead write-off mismatch, F10/F23 fattura passiva dropdown lavorazione JCL, F18 lista fatture detail on click, F20 batch aggrega tasto sparisce, B5 chip drift sempre visibile.

**Backlog α.122+ — P2 architetturale (10 finding, design discussion)**:
F6 admin_email send semantica, F7a drawer center popup, F7b inserimento blocchi inline, F11 supplier↔resource flusso inverso, F16 IVA default off, F17 terminologia JCL→lavorazione, F19 cashflow split reparti, F21 UX revamp team/resources/departments, F24/F9 sweep codici DB.

Backlog completo: [[project_alpha120_backlog]] in memoria progetto.

## (versione precedente)

**v3.5.0-alpha.119** — 16 maggio 2026 — Cost_external priority ranking + auto-dismiss drift self-healed

**2 finding chiusi (smoke E2E post-α.118)**:
- Finding 1: `total_cost_external` double-counted su JCL multiple stesso job (OR-soup filter) → fix priority ranking esclusivo jcl > job > project con pro-quota distribution.
- Finding 2: anomaly `cost_estimate_vs_real_drift` open zombie dopo fix causa → detect ora marca `dismissed` + `handled_action=auto_resolved` le entry non ri-emesse nel round corrente.

**Smoke E2E server-side completato**: 17 punti checklist α.113→α.118 verificati (schema, numbering, immutability, pattern guard, reconcile, anomaly types). Tutti pass tranne i 2 finding ora risolti in α.119.

**Lista test UI Matteo**: [[test_checklist_post_audit_alpha114_118]] (60+ punti) — server up su `http://127.0.0.1:8000`, snapshot DB importato.

**Architettura doc generato**: `docs/ARCHITETTURA.md` + `docs/ARCHITETTURA.pdf` (476 KB, 8 diagrammi mermaid embedded) per condivisione con team. Script riproducibile `scripts/build_arch_pdf.py`.

**Pendente alpha.120+**:
- Esecuzione test UI Matteo su checklist.
- Bug emersi da uso reale.
- Knowledge Base capitolati F14/F15 (parser deliverables → DeliveryTemplate).
- Capability AI estese (email/Drive/Office OAuth, filesystem Asset Library).

## (versione precedente)

**v3.5.0-alpha.118** — 15 maggio 2026 tardi notte — Audit M-finding chiusi (delete supplier hook + preview placeholder + quote pattern guard)

**3 fix audit minori chiusi (cleanup roadmap)**:
- Delete SupplierInvoice → trigger recompute cost_external (bug Q11)
- Preview placeholder `«PROJ»`/`«CLI»` esplicito + nota UI
- Quote pattern validation: deve terminare con {NNN}/{NN}/{NNNN}

**Roadmap audit completamente chiusa**. 6 round consecutivi:
- α.113: 11 punti revisione Q1-Q11
- α.114: 16 fix audit deep-dive
- α.115: Q11 cost-side + NumberingConfig core + reconcile dirty flag
- α.116: NumberingConfig cabling 6 generator + UI vars validation
- α.117: anomaly cost_drift + UI background reconcile
- α.118: 3 audit M-findings (delete supplier, preview, quote pattern)

## (versione precedente)

**v3.5.0-alpha.117** — 15 maggio 2026 tarda notte — Anomaly cost_drift + UI background reconcile

**Roadmap alpha.114-117 completata**. Tutti i pendenti dell'audit chiusi.

**Anomaly cost_drift**:
- 6° tipo: `cost_estimate_vs_real_drift`
- Detector con threshold 15% drift su (external vs accrued)
- UI: chip filtro + summary card + label
- Esempio: cost stimato €2000 vs fattura passiva €2500 → drift 25% →
  anomaly. Manager rivede rate o assorbe via write_off.

**UI background reconcile (Strategy C combinata con A dirty flag α.115)**:
- Page load CR immediato (no più blocco reconcile sincrono)
- Background polling /api/reconcile-status ogni 2s
- Indicator fixed top-right: "🔄 Sincronizzazione (N righe)"
- Auto-refresh lista quando stale=0
- Stress DB 80k JCL: page load <100ms, sync visibile in background

**Da testare Matteo**:
1. /finance#anomalies: nuovo chip "⚖ Drift costo".
2. Crea fattura passiva con resource_id linked > stima → click "🔄 Rileva"
   → vedi anomaly emessa.
3. /cost-report apertura: deve essere IMMEDIATA + indicator sync top-right
   (se ci sono JCL stale).

**Summary 5 round alpha.113-117**:
- α.113: 11 punti Q1-Q11 (header, project filter, admin email, naming
  builder, CR reconcile, overhead detail, supplier→project, job select,
  resource link)
- α.114: 16 fix da audit (immutability, cashflow NC, Q5 root, NC closing
  reset, race lock, COUNT bug, re-assign recompute, drift read-only,
  tenant sweep, ...)
- α.115: Q11 cost-side + NumberingConfig core + reconcile dirty flag
- α.116: NumberingConfig cabling completo (6 generator) + UI validation
- α.117: anomaly cost_drift + UI background reconcile

**Pendente alpha.118+**:
- Test estensivi Matteo
- Eventuali bug emersi da uso reale

## (versione precedente)

**v3.5.0-alpha.116** — 15 maggio 2026 notte — NumberingConfig cabling completato + UI vars validation

**Cabling completato per tutti i generator**:
- Quote.number (α.115)
- BillingBatch.code (α.115)
- Job.code (α.116)
- OverheadCost.code (α.116)
- IngestBatch.code (α.116)
- DDT delivery_note_number (α.116)

**3 nuovi doc_type esposti in /settings#numbering**:
- overhead_cost (date+seq, no project/client)
- ingest_batch (date+seq+PROJECT_CODE)
- ddt (date+seq+PROJECT_CODE)

**UI validation greyed-out**:
- Builder drag&drop mostra variabili non supportate come greyed/disabled
  con tooltip "non disponibile per questo tipo".
- Backend `validate_pattern()` rifiuta 400 su variabili fuori scope.

**Pattern collision safety**:
- Tutti i 6 generator usano `gen_doc_code()` con verifica uniqueness +
  fallback automatico alla logica legacy in caso di config errata o
  collision. Zero risk crash.

**Da testare Matteo**:
1. /settings#numbering: vedi 11 doc_type (era 8). Per overhead_cost
   PROJECT_CODE/CLIENT_CODE greyed-out con tooltip.
2. Salva `OH-{PROJECT_CODE}-{NNNN}` per overhead → backend rifiuta 400.
3. Crea nuova spesa azienda → codice OH-2026-0001 (o custom se hai
   impostato format).
4. Crea ingest batch / DDT → codici riflettono config se presente.
5. Crea Job da quote → code segue config "job" (fallback {PROJECT_CODE}-J{N}).

**Pendente alpha.117+**:
- Anomaly type "cost_estimate_vs_real_drift" per forecast.
- UI background indicator durante reconcile-all (Strategy C async).
- Test estensivi alpha.114 + alpha.115 + alpha.116.

## (versione precedente)

**v3.5.0-alpha.115** — 15 maggio 2026 notte — Q11 cost-side + NumberingConfig cabling + reconcile-all perf

**3 punti pesanti dall'audit chiusi**:

1. **Q11 cost-side aggregation (vista doppia stimato vs reale)**:
   - `JobCostLine.total_cost_external` aggrega Σ SupplierInvoice del progetto
     dove resource_id ∈ risorse dei booking della JCL.
   - Recompute hook in cost_line_sync + trigger su save/update SupplierInvoice.
   - CR dettaglio: stat card "Costo reale (fatture)" + Δ vs stima.
   - Esempio: JCL "Color 5gg" - revenue €5000, cost stimato €2000 (booking ×
     rate), cost reale €2500 (fatture passive Marco linkate). Margin reale
     vero = €5000-2500 = €2500 (non più €3000 ingannevole).

2. **NumberingConfig cabling**:
   - Helper `expand_pattern()` + `gen_doc_code()` in numbering.py.
   - Quote.number e BillingBatch.code leggono NumberingConfig + fallback
     automatico su default storico se config assente o collision.
   - Esempio: admin imposta `Q-{PROJECT_CODE}-{YYYY}-{NNN}` → nuova quote
     su progetto MEDUSA_2026 → `Q-MEDUSA_2026-2026-001`.
   - Reset annuale automatico.
   - Pendente cabling: Job/OverheadCost/IngestBatch (logica custom).

3. **Reconcile-all perf (dirty flag pattern)**:
   - `JobCostLine.accrued_stale` boolean.
   - reconcile-all ora WHERE stale=True → ~50ms invece di 15-30sec freeze.
   - Endpoint `/api/reconcile-status` per UI polling.

**Da testare Matteo**:
1. Settings#numbering: cambia Quote format con `{PROJECT_CODE}` → crea
   nuova quote → verifica codice contenga project_code.
2. /suppliers nuova fattura passiva: imposta resource_id linkata a una
   risorsa con booking → vedi CR dettaglio quel job → stat "Costo reale"
   mostra Σ fatture + Δ vs stima.
3. /cost-report apertura: deve essere immediata (no più freeze).
4. /cost-report dopo move booking done: lista immediato allineata.

**Pendente alpha.116+**:
- Cabling NumberingConfig su Job/OverheadCost/IngestBatch/DDT
- Anomaly type "cost_estimate_vs_real_drift" per forecast (esempio Matteo)
- UI background indicator durante reconcile (Strategy C async polling)

## (versione precedente)

**v3.5.0-alpha.114** — 15 maggio 2026 sera — Audit deep-dive: 16 fix bug+architettura

Audit multi-agent in-depth ha trovato BLOCKER + HIGH bugs su:
- Q5 ROOT CAUSE: bulk_edit shift temporale su done bookings no recompute
- Storno NC closing → JCL lost orfani
- Race double-close per project
- PDF drift mutava Invoice (regressione alpha.112)
- Cashflow ignorava storno NC TD04
- OverheadCost code COUNT collide con soft-delete
- update_booking re-assign JCL senza touch assignments → stale
- Resource delink missing su supplier save
- Tenant scope mancante su nuovi FK alpha.112+113

**Decisioni di prodotto recepite**:
1. Fatture IMMUTABILI post-draft. AI no touch. Solo storno NC.
2. Cashflow include TD01 cancelled + NC TD04 segno negativo (storico).
3. Q11 cost-side aggregation: vista doppia stimato/maturato (alpha.115).
4. NumberingConfig cabling (alpha.115).
5. reconcile-all perf: dirty flag + async UI (alpha.115).

**16 fix in alpha.114**:
- A1: card grid alignment (`.card+.card` scoped)
- A2: PDF drift read-only + UI badge ⚠
- A3: Invoice immutability guard (409 su PUT post-draft)
- A4: cashflow include storno NC con segno
- A5: bulk_edit recompute on done bookings (Q5 root)
- A6: storno NC closing → reset JCL lost zero-approved
- A7: with_for_update Project precheck (race lock)
- A8: OverheadCost.code via canonical generator (no COUNT bug)
- A9: update_booking re-assign JCL → recompute vecchia+nuova
- A10: resource delink su supplier save
- A11: job_id senza project_id form fix
- A12: /projects?client_id sconosciuto → warning
- A13: + Crea risorsa deferred (disabled finché supplier salvato)
- A14: drawer naming flush right sidebar
- A15: tenant scope sweep nuovi FK
- A16: zero-accrued JCL nel closing precheck (double-check)

**Da testare Matteo**:
1. CR list maturato deve essere allineato SUBITO senza reconcile-all
   (A5 root cause). Verifica spostando booking done.
2. PUT Invoice post-emit deve dare 409 (no più auto-modifica).
3. Cashflow: emetti TD01, storna via NC TD04 stesso anno → saldo netto 0.
4. Emit chiusura progetto, storno NC, riemetti closing → no orfani lost.
5. Modal supplier: cambia risorsa associata → vecchia deve essere delinked.
6. /projects?client_id=99999 → toast warning.
7. /settings#numbering builder drawer → flush a destra sidebar.

**Roadmap alpha.115** (next round):
- Q11 vista doppia maturato/stimato + SupplierInvoice aggregation cost-side
- NumberingConfig cabling (refactor numbering.py + 7 callers)
- reconcile-all: dirty flag + background async UI

## (versione precedente)

**v3.5.0-alpha.113** — 15 maggio 2026 — Round revisione Matteo pomeriggio (11 punti Q1-Q11)

**Hotfix critico**: alpha.112 aveva `<script src=".../global.js">` senza
`</script>` chiusura in base.html → JS rotto. Fixato in alpha.113.

**11 punti chiusi Q1-Q11**:
- Q1: header topbar contrasto pieno (var(--text) + indigo hover)
- Q2: /projects?client_id=N preseleziona filtro
- Q3: Client.admin_email + snapshot + intestazione PDF
- Q4: Naming conventions builder drag&drop drawer left
- Q5: reconcile-all bulk all'apertura lista CR
- Q6: drawer dettaglio voci per categoria in /overhead
- Q7: supplier_invoice senza project = categoria virtuale in /overhead
- Q8: lista fatturazione mostra codice + titolo progetto
- Q9: lista suppliers mostra Progetto colonna
- Q10: job select fattura passiva (era 404 /jobs/api → /planning/api/jobs)
- Q11: SupplierInvoice.resource_id + Resource.supplier_id + UI link

**Da testare Matteo**:
1. Header su temi paper/sand/linen/sage: icone visibili
2. /clients → "Vedi progetti" lancia /projects con filtro cliente
3. /clients edit: nuovo campo "Email amministrazione" → emit fattura → PDF mostra "Att.ne Amministrazione"
4. /settings#numbering rinominato "Naming conventions" → click regola → drawer left con drag&drop chips
5. /cost-report apertura: numeri lista corretti SUBITO (no più gap dopo apri-dettaglio)
6. /overhead: click card categoria → drawer con voci che compongono
7. /overhead: card "Fatture passive (no progetto)" se presenti
8. /finance lista fatture: colonna Progetto con codice + titolo
9. /suppliers lista: nuova colonna Progetto
10. /suppliers nuova fattura: dropdown Job ora popolato + filtra per progetto
11. /suppliers modal fornitore: "Risorsa associata" + "+ Crea risorsa"

**Cabling pendente** (alpha.114+):
- NumberingConfig non ancora letto dal numbering service.
- Match SupplierInvoice.resource_id ↔ Booking.resources nei CR (UI ok,
  aggregazione cost-side ancora non implementata).

## (versione precedente)

**v3.5.0-alpha.112** — 15 maggio 2026 — Round revisione Matteo (12 punti P1-P12)

**12 punti chiusi in single bump**:
- P1: 13 look in /settings#aspect (aggiunti paper/linen/sage)
- P2: header topbar leggibile su temi chiari (color var(--text2))
- P3: /hr 500 fix (Jinja tag dentro commento JS → mismatch endif)
- P4: modal Trasmetti CR 980px + totale iniziale corretto
- P5: banner "altri batch aperti progetto" in modal emit + switch compose
- P6: PDF si apre subito post-emit (window.open)
- P7: PDF ricomputa Σ lines + drift-detection auto-fix ORM
- P8: ricerca per numero fattura (backend ilike + UI debounce)
- P9: fattura chiusura progetto (modelli + endpoint + PDF riepilogo +
  storno NC riapre automaticamente)
- P10: filtro stato job CR allineato a JobStatus enum reale
- P11: stati CR chiariti (tooltip Maturato totale vs post + banner
  esclusioni transmit modal)
- P12: regole nomenclatura in /settings#numbering (scaffolding solo;
  cabling effettivo nel numbering service in iterazione futura)

**Da testare Matteo**:
1. /hr deve caricare (no 500)
2. Modal Trasmetti CR: larga + totale iniziale corretto + banner esclusioni
3. Tema paper/sand: icone topbar visibili
4. Settings > Aspetto: 13 temi presenti
5. Settings > Numerazione: nuovo tab (admin only)
6. Emit fattura: PDF si apre subito + se batch multipli → banner compose
7. /finance: bottone topbar `🏁 Fattura chiusura` → modal precheck
8. CR detail line: header "Maturato post" tooltip esplicito
9. Storno NC su closing → progetto riapre automaticamente

**Cabling pendente** (alpha.113+):
- `NumberingConfig` salvato ma non ancora usato. Quote/Batch/Job code
  ancora generati da default storico.

## (versione precedente)

**v3.5.0-alpha.111.12** — 14 maggio 2026 — Density compact/spacious tagliati + heatmap su label

**Density buttons rimossi** (Matteo: "togliamole"):
- ⠿ Compact + ☰ Spacious mai funzionanti correttamente
- Solo Comfortable rimane (implicito, no button toolbar)
- CSS + JS density code semplificato

**Heatmap su label risorsa** (Matteo: "doveva apparire sulla risorsa"):
- α.111.10 (bg items in foreground) interferiva con hover items
- Ora overlay abs-positioned bottom strip dentro `.tl-res-cell` label
- `position:relative` su wrapper cell + `position:absolute` overlay →
  no impatto altezza label (problema α.99 originale evitato)
- Cache-bust planning.css?v=3.5.0-alpha.111.12

**Da testare Matteo**:
1. Toolbar timeline: niente più ⠿/☰, solo opzioni utili (font, etc)
2. Hover item: tooltip rich (no interferenza heatmap)
3. Toggle 📊 Heatmap → barra colorata sotto nome risorsa (sotto Online Editor)
4. No bg colorato strisce nel foreground timeline

**Round timeline α.111.3→α.111.12 chiuso**. 10 commit pushati.

## (versione precedente)

**v3.5.0-alpha.111.10** — 14 maggio 2026 — Fix hover tooltip + heatmap reintrodotta

**Tooltip hover items**: bug pre-esistente da α.83. `tlTooltipShow`
referenziava `bookings` (let locale di `tlRender`) invece di
`window._tlBookings`. Early return silenzioso. Fix puntuale.

**Heatmap capacity**: reintrodotta come background items (1 per giorno
per risorsa, colore = ore/8 ratio). Architettura corretta: vis renderizza
dietro items normali senza toccare row height. Toggle ricarica dataset.

**Stato density**:
- ✓ Comfortable (normale): funziona (Matteo OK)
- ✗ Compact: ancora rotta
- ✗ Spacious: ancora rotta
- Matteo si accontenta della normale per ora.

**Da testare Matteo**:
1. Hover item timeline → tooltip rich (titolo, durata, stato, progetto, job, note)
2. Toggle 📊 Heatmap in toolbar → background colorato per giorno (verde/arancio/rosso)
3. Re-toggle off → background eliminato

**Tutta sessione α.111.3→α.111.10** focused timeline fix. Push fatto
ogni commit. Export ZIP allegato. Heatmap bug aperto dal α.99 ora chiuso.

## (versione precedente)

**v3.5.0-alpha.111.6** — 14 maggio 2026 — Timeline min-height uniforme cross-row

**Round timeline fix (4 commit incrementali oggi)**:
1. α.111.3: `orientation:{axis:'top', item:'top'}` fix groups ancorati
   al fondo. ✓ Confermato da Matteo "allineamento top sicuramente migliore".
2. α.111.4: helper `tlDebugAlign()` per dump label/group coord. Output:
   diff=0.0 ovunque, ma labelH variabile (56-69px).
3. α.111.5: helper `tlDebugItems()` per dump items. Tutti 5 items in
   row corretto del dataset. Bug NON è items↔group mismatch.
4. α.111.6: causa vera — `max(items, label) per group`. Risorse senza
   items collassano + Spacious overflow label content.

**Fix**: min-height su BOTH `.vis-label` + `.vis-foreground .vis-group`
(planning.css). 3 valori per density: compact 34, comfortable 48,
spacious 62. Cache-bust planning.css?v=3.5.0-alpha.111.6.

**Heatmap toggle**: ancora no-op (commit α.99). Da affrontare in
sessione separata: reintrodurre come overlay assoluto sul foreground.

**Da testare Matteo**:
1. /planning → Timeline → Spacious: "Online Editor" NON deve overfloware
2. Compact: testi label non più tagliati
3. Comfortable: nessun parziale overlap con linea demarcazione
4. Risorse senza items (es Luca Bianchi) hanno row con stessa altezza
   delle risorse con items

Push: SÌ (Matteo in remoto). Export ZIP DB allegato.

## (versione precedente)

**v3.5.0-alpha.111.2** — 14 maggio 2026 — Rollback timeline + riallineamento quadranti quote + seed lean + simulazione CR→billing

Post-feedback Matteo (notte 13-14 mag):

**Quote editor — disallineamento Riepilogo/Stato&azioni FIX**:
5 form-group meta estratte dalla card destra "Stato & azioni" in
nuova card "Condizioni economiche & scadenze" sotto top-row. Le 2
card top ora bilanciate.

**Anomalies detect 500 fix**:
- Invoice.tenant_id (inesistente) → JOIN Client
- JobStatus.in_progress (inesistente) → active/completed/invoiced
Test detect_all → 3983 anomalie OK.

**Rollback timeline α.111** (regressioni):
planning.html + planning.css ripristinati a stato α.110.

**Seed lean**: `seed_stress.py --scale 0.3` → ~30 clienti, ~300
progetti, ~150 risorse, ~2600 booking. Test 34s.

**Simulazione CR→billing**: `simulate_cr_to_billing.py --n 15
--storno 3` → 15/15 fatture emesse, 3 NC TD04 stornate, slice voided,
batch riaperti. DB finale: 614 fatture (3 TD04), 116 batch.

**Da testare sul Mac di Matteo**:
1. /quotes/{id} editor: 2 card top "Riepilogo + Stato&azioni"
   allineate. Sotto: card "Condizioni economiche & scadenze".
2. /finance tab Anomalie: "Rileva" → 200 OK (non più 500).
3. Timeline planning ripristinato: side scroll, heatmap, drag bordo,
   stack adattivo.
4. DB lean: 300 progetti, ~150 risorse, ~2600 booking visibili.
5. /finance: batches lean popolati con SIM-* + 3 NC stornate visibili
   (filtro doc_type=TD04).

2 commit locali NON pushati (α.111 + α.111.1 + α.111.2 incoming).

## (versione precedente)

**v3.5.0-alpha.111** — 13 maggio 2026 — Billing UX cleanup + storno NC TD04 + scadenze Quote→Project + timeline polish

Round chiuso a 13 richieste Matteo (5 fronti):

**Billing**:
- Tab Timesheet+P&L rimossi
- Endpoint nuovo `/finance/api/billing/invoice/{id}/pdf` (PDF via invoice_id)
- batch invoice-pdf fallback via JCLBilledSlice + error msg descrittivo
- Batch list: hide-invoiced default + data fattura + "Vai alla fattura"
  filtra alla singola (focus-bar) + bottoni storno/PDF per riga
- "Componi fattura" mode `per progetto` (default) | `per periodo`
- Invoice line description con `[periodo → validità]`
- **Storno NC TD04**: endpoint `POST /finance/api/billing/invoice/{id}/storno`
  — crea TD04, voida JCLBilledSlice, riapre batch
- Auto due_date da Project.billing_terms_days

**Quote → Project scadenze**:
- Quote.billing_frequency + billing_terms_days (auto-migrate)
- Project.billing_terms_days (auto-migrate)
- UI editor quote con dropdown + input
- Propagation all'approve

**Timeline**:
- horizontalScroll:false (side scroll rimosso)
- Drag bordo rimosso (CSS display:none su drag-left/right)
- stack:false default → righe uniformi
- Heatmap toggle rimosso (era no-op)
- Shift+wheel target multipli con scrollHeight check

**Cost report**:
- Backfill JobResourceAssignment al boot da booking storici
- Tabelle Voci/Ore booking rese mf-sortable

**Schema auto-migrate**:
- jcl_billed_slices.voided_at + voided_by_invoice_id
- quotes.billing_frequency + billing_terms_days
- projects.billing_terms_days
- slice_guard filtra voided_at IS NULL

**Da testare**:
1. `/finance` 3 tab (Fatture/Batch/Anomalie)
2. Batch fatturati nascosti default + numero+data fattura visibili
3. "Componi fattura" mode progetto
4. Storno TD04: NC emessa, source annullata, batch riaperto
5. Quote editor scadenze + propagation a Project
6. Timeline righe uniformi, no side scroll, no drag bordo
7. Cost report: assignment popolate (backfill) + tabelle sortable

1 commit locale NON pushato (α.111).

## (versione precedente)

**v3.5.0-alpha.110** — 13 maggio 2026 — Storage adapter S3 + TPN strong isolation

**Storage adapter pattern**:
- `app/services/storage/` con LocalFS + S3 (boto3 1.43.6, signature v4)
- factory routing per Project.storage_backend
- `/dam/download/{id}` ritorna redirect 302 a presigned URL per file su S3
- Legacy locale sempre leggibile

**TPN strong isolation (mutator critici)**:
- DAM assign-project / upload / fs-import: check
  `user_can_access_project(user, target)` per target progetto
- Physical-assets shipments charged_to_client: idem per billable project
- Skip per is_admin (super-admin bypass)

**Da testare**:
1. `pip install boto3` (locale) — necessario solo se attivi S3 backend
2. Configura .env: AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY + 
   AWS_S3_DEFAULT_BUCKET + AWS_S3_ENDPOINT (per MinIO/R2)
3. Crea project con `storage_backend=s3 s3_bucket=...` via API
4. Upload asset al project → file_path = `s3://bucket/...`
5. Download asset → redirect 302 a presigned URL S3
6. Non-admin user non in grants progetto → upload bloccato 403

**Aperti R12 backlog**:
- Sostituzione vis-timeline (cantiere settimane)
- PDF clausola markup esplicita
- UI editor storage_backend per project

1 commit locale NON pushato (α.110).

## (versione precedente)

**v3.5.0-alpha.107** — 13 maggio 2026 — Timeline density attiva stack + scroll keyboard + legenda

Risposta screenshot Matteo righe altezze diverse (138/50/69/54px):

**Root cause**: vis-timeline 7.x `stack:true` espande righe su item
overlap. Limite strutturale libreria (sostituzione = backlog R12).

**Fix α.107**:
1. Density toggle ora cambia `inst.setOptions({stack: false/true})`:
   - compact/spacious = stack:false (uniformi)
   - comfortable = stack:true (expand su overlap)
2. Scroll keyboard: ↑↓ step, PgUp/PgDn fast, Home/End jump,
   Shift+wheel = scroll verticale
3. Legenda aggiornata con shortcuts reali

**Da testare**: planning → click bottone "☰ Spazioso" → righe ora
uniformi 50-70px tutte. Scroll con ↑↓ e PgUp/PgDn.

**Su "ripensare GUI timeline da zero"**: vis-timeline limiti
documentati. Sostituzione Bryntum/DHTMLX = cantiere 2-3 settimane (R12).

1 commit locale NON pushato (α.107).

## (versione precedente)

**v3.5.0-alpha.106** — 13 maggio 2026 — Spedizioni+Reparti+Quote+Bug AI

5 fronti chiusi:
1. **Bug AI 500 fix**: encrypt_secret try/except → 503 chiaro.
   requestIdleCallback TypeError fixato (options object).
2. **Spedizioni dettaglio**: click row apre drawer 520px con asset fisici
   + storico contenuti AT batch.batch_date (snapshot AssetMembership).
3. **Spedizioni indirizzi**: autocomplete unificato tenant + departments
   + clients + suppliers. Form fieldset Mittente/Destinatario con
   address+contact auto-popolato.
4. **Department.shipping_address/contact**: nuovi field per reparti con
   sede diversa (auto-migrate).
5. **Quote.shipping_markup_pct**: campo dedicato nel card "Stato &
   azioni" (default 15%, override Project).

**Aperti** (effort esplicitato):
- **Storage adapter S3** ~1 settimana
- **TPN audit endpoint mutator** ~3-5gg
- **PDF clausola markup esplicita**

1 commit locale NON pushato (α.106).

## (versione precedente)

**v3.5.0-alpha.105** — 13 maggio 2026 — Storage multidomain per progetto + ENV S3 + UI multipath FS scan

Preparazione storage S3 + compartimentazione TPN per progetto.

**Modello Project** esteso (+4 colonne auto-migrate):
- storage_backend / storage_root / s3_bucket
- fs_scan_paths (whitelist per-project override tenant-level)

**Settings ENV** per S3-compatible (MinIO/R2/Wasabi/AWS).

**UI nuova tab "💾 Storage"** in `/settings`:
- Multipath FS scan tenant-level con add/remove
- Istruzioni ENV S3 + workflow attivazione per Project

**FS scan TPN strict**: se `Project.fs_scan_paths` valorizzato → SOLO
quella whitelist (no fallback tenant). Compartimentazione stagna.

**Da testare**:
1. `/settings` tab Storage → aggiungi 2 paths → vedi lista
2. `PUT /projects/api/1 storage_backend=s3 s3_bucket=X fs_scan_paths_json=[...]`
3. `POST /dam/api/fs-scan project_id=1 path=/Volumes/X` → valida contro
   project paths

**Aperti**:
- **α.106**: storage adapter pattern (`storage/{local_fs,s3,factory}.py`),
  upload/download routing, presigned URL
- **α.107**: TPN strong isolation audit endpoint mutator

1 commit locale NON pushato (α.105).

## (versione precedente)

**v3.5.0-alpha.104** — 13 maggio 2026 — Super-admin GUI tenant + manuale

**Console super-admin platform** (`/platform/tenants`):
- Lista cross-tenant con KPI users/projects/clients
- Modal crea Tenant (delega a stesso flow del CLI)
- Edit / Sospendi / Riattiva tenant
- Aggiungi admin user a tenant esistente
- Auth: `User.is_platform_admin=True` (bootstrap admin@mediaflow.it +
  matteo@mediaflow.it via auto-migrate)
- Sidebar: sezione "Platform · Tenants" visibile solo a super-admin

**Manuale aggiornato**: 5 sezioni nuove (capitolati, spedizioni, fs scan,
cross-check, portale cliente, multi-tenant + console). TOC sidebar
aggiornata.

**Da testare**:
1. Login admin@mediaflow.it → sidebar mostra "Platform · Tenants"
2. Click → lista tenant (Default + acme)
3. "+ Nuovo Tenant" → crea con slug "testco" → vedi credenziali popup
4. Login `?tenant=testco` con email/password generate → dashboard vuota
5. `/manuale` → vedi sezioni nuove nella TOC

1 commit locale NON pushato (α.104).

## (versione precedente)

**v3.5.0-alpha.103** — 13 maggio 2026 — Multi-tenant HARD R-MT3 + R-MT4 (onboarding + test)

**Multi-tenant HARD COMPLETO** (4 sprint chiusi: R-MT1→R-MT4).

R-MT3 onboarding:
- `scripts/create_tenant.py` CLI: Tenant + admin User + 4 Department +
  `uploads/t{id}/` isolata. Listino vuoto. Password admin random.
- `save_upload` ora usa `uploads/t{tid}/assets/` invece di globale.

R-MT4 test + audit:
- Script `scripts/test_multitenant.py`: 8 check E2E via HTTP urllib.
- **8/8 PASS**: login scope, cross-tenant block, isolation clienti +
  projects, leak detection.
- Fix bulk `projects.py`: 8 `.filter(Project.id == X)` aggiunti tenant
  scope. Era leak cross-tenant.

**Tenant Acme** già creato in DB (id=2) per testing:
- admin@acme.it / acmepw123
- Login: `http://localhost:8000/auth/login?tenant=acme`
- O via lvh.me: `http://acme.lvh.me:8000/auth/login`

**Da testare sul Mac**:
1. Crea tenant via script: `python scripts/create_tenant.py --slug myco
   --name "MyCo Post" --admin-email admin@myco.it --admin-name "Test"`
2. Login `?tenant=myco` con credenziali stampate
3. Verifica lista clienti vuota, listino vuoto, departments default
4. Logout, login `?tenant=acme` (dovrebbe vedere altri dati = []  )
5. Cross-test: login senza ?tenant=, modifica cookie a /clients/api con
   header `X-Tenant-Slug: myco` → atteso 303 redirect login

**Backlog post-MT**:
- Audit altri router con `.filter(X.id == y).first()` no tenant filter
- UI gestione tenant (oggi solo CLI)
- Subdomain DNS wildcard + cert SSL (quando dominio scelto)
- `Tenant.onboarding_completed` flag setting workflow

2 commit locali NON pushati (α.102 già pushato, α.103 pendente).

## (versione precedente)

**v3.5.0-alpha.102** — 13 maggio 2026 — Multi-tenant HARD R-MT2 (341 router refactor)

24 file router refactorati: `CURRENT_TENANT = 1` rimpiazzato con
`current_tenant_id()` (chiamata dinamica letta da contextvars
settato dal middleware tenant_resolver). 341 occorrenze totali.

E2E test post-refactor:
- Login → JWT con tid=1 ✓
- /clients/api → 200 ✓
- /finance/api/billing/composable-batches → 200 ✓

**Aperti**:
- **R-MT3**: onboarding CLI/UI nuovo tenant + uploads/t{tid}/ isolation
- **R-MT4**: test cross-tenant leak + security audit

## (versione precedente)

**v3.5.0-alpha.101** — 13 maggio 2026 — Multi-tenant HARD R-MT1 (auth scope)

Primo sprint Multi-tenant HARD (#6 roadmap, 4 sprint totali).

Decisioni semantiche confermate Matteo:
- Resolution: subdomain (`acme.mediaflow.it`)
- Onboarding: invito only
- Listino: vuoto per nuovo tenant
- Uploads: per-tenant
- Billing: backlog
- Tenant 1 = Default

**R-MT1 fatto**:
- `User.tenant_id` FK + email UNIQUE per (tenant_id, email)
- `context.py` con `contextvars.ContextVar` reale (era stub → 1)
- Middleware `tenant_resolver` → host/header/query/JWT
- Cross-tenant gate in `auth_guard`: JWT.tid != request.tid → re-login
- JWT include `tid` claim
- Login scope al tenant resolved

**Aperti**:
- **R-MT2**: 376 occorrenze `CURRENT_TENANT = 1` in 25 router → switch a
  `current_tenant_id()` per-request
- **R-MT3**: onboarding CLI/UI + uploads/t{tenant_id}/
- **R-MT4**: test cross-tenant leak

**Da testare R-MT1**: login standard funziona (verifica JWT include `tid`).
Subdomain `acme.lvh.me:8000` (lvh.me → 127.0.0.1) → resolution tenta slug
"acme" → cade su DEFAULT se tenant inesistente.

1 commit locale NON pushato (α.101).

## (versione precedente)

**v3.5.0-alpha.100** — 13 maggio 2026 — Tint vars theme-aware per temi chiari

Variabili nuove `--tint-faint/soft/medium/strong` in `:root` (dark default
= bianco semitrasparente) + override `.theme-sand/paper/linen/sage` (nero
semitrasparente). 5 hardcoded più visibili in planning.css sostituiti con
var() per bordi/separatori/hover che diventavano invisibili su tema chiaro.

**Da testare**: tema chiaro Paper/Sand → bordi card storyboard,
separatori, hover ora visibili (erano "fantasma" prima).

2 commit locali NON pushati (α.99, α.100).

## (versione precedente)

**v3.5.0-alpha.99** — 13 maggio 2026 — Timeline design fix: density funzionante + heatmap fuori da label

Screenshot Matteo 15.21-15.22 → "problema di design a monte" individuato:

1. **Density preset ⠿/≡/☰ era decorativo**: bottoni settavano data-density
   ma nessuna regola CSS lo applicava per #tl-host (esisteva solo per
   #sb-host storyboard). Aggiunte regole compact/spacious che scalano
   font name/role/item + padding. `tlSetDensity()` ora forza redraw.
2. **Heatmap dentro label cell rompeva sync altezza** label↔foreground.
   Rimossa. Item ora allineati. Re-introduzione come overlay foreground
   è backlog.

**Da testare**: ricarica `/planning`:
- Click ⠿ compact → font label piccolo, righe basse. Click ☰ spacious →
  font grande, righe alte. Click ≡ comfortable → default. Tutti
  cambiano visibilmente.
- Verifica: item allineati con label (vedi item arancione del 15.22.20
  che era sfasato — ora dovrebbe stare sulla riga della sala giusta).

1 commit locale NON pushato (α.99).

## (versione precedente)

**v3.5.0-alpha.98** — 13 maggio 2026 — Fix timeline duplicati + label role leggibile

Screenshot Matteo 12.47-12.49 → 3 bug separati:
1. **Stefano Marini duplicato**: seed test aveva 2 Resource id=232+254
   con stesso nome/role/dept. Script `dedup_resources.py` deduplica
   (riassegna booking al keeper, soft-delete duplicato). 1 gruppo, 52
   booking riassegnati.
2. **Role illegibile**: font 9px uppercase → bumpato 11px no-uppercase.
   Rimosso `color:#ffffff` inline su nameEl (eredita var(--text)
   theme-aware ora).
3. **Sale duplicate visive**: vis-timeline 7.x bug `stack:true` con item
   overlap crea righe virtuali. NON fixable senza cambio libreria.
   Documentato come limitazione nota in changelog.

**Da testare**: ricarica `/planning` con tema scuro → vedi:
- "Stefano Marini" UNA sola volta
- Label risorsa: nome 14px bold + ruolo 11px sotto (era 9px illegibile)
- Tema chiaro: nome leggibile (no più #fff invisibile)

**Push fatto**: 7 commit (e0f1ddf → 50f4f6e) ora su origin/main.

## (versione precedente)

**v3.5.0-alpha.97** — 13 maggio 2026 — Portale Cliente fase A: magic-link auth + dashboard read-only

Punto #10 roadmap fase A:
- Modello `ClientPortalAccess` (token magic-link, expires, project_scope)
- Router `/portal/*`: admin crea access → cliente accede via cookie
  `portal_token` (auth separata da admin)
- Pagine: login, dashboard progetti, scheda progetto con milestone + DAM
- Layout pulito `portal_base.html` (no sidebar admin, palette minimal)

Fasi B (DAM gate per portale, fatture read-only) + C (ticket, notifiche
email, dominio vanity) sono backlog.

**Da testare**:
1. Admin: `POST /portal/api/access` con `client_id=X` + `email` →
   ricevi `magic_link`. Forma: `http://localhost:8000/portal/login?token=...`
2. Apri magic_link in browser (idealmente incognito) → ti porta a
   `/portal/` con lista progetti del cliente. Cookie `portal_token` settato.
3. Click su progetto → scheda + milestone + DAM (con bottoni Scarica).
4. Logout → redirect a `/portal/login`.
5. Admin: `POST /portal/api/access/{id}/revoke` → token invalidato.

**ATTENZIONE sicurezza fase B**: `/dam/download/{id}` attualmente
accessibile via portal_token bypass del middleware admin. Per fase B
serve gate dedicato che verifichi portal_token + asset.project_id in
accessible_project_ids del portal_access.

17 commit locali NON pushati (b8b8bb6 → α.97). Push a major bump.

## (versione precedente)

**v3.5.0-alpha.96** — 13 maggio 2026 — Capability AI #9b filesystem scan + #9d web cross-check

**#9b — Filesystem scan generico**:
- `Tenant.fs_scan_allowed_paths` whitelist obbligatoria (path NAS/dischi
  esterni). Endpoint `/dam/api/fs-scan` + `/dam/api/fs-import` (registra
  Asset DAM senza copiare file). Pagina `/dam/fs-scan` con KPI + tabella
  classificata + import bulk.

**#9d — Web cross-check progetti/clienti**:
- Service `web_crosscheck.py`: confronta DB con IMDB/BoxOffice/Variety
  (progetti) e Cerved/news (clienti). Native web search → Tavily →
  knowledge-only cascata.
- Endpoint `/projects/{id}/cross-check` + `/clients/{id}/cross-check`.
- UI modal preview differenze + external_info, NO DB write.

**Da testare**:
1. `/settings` o Copilot → configura `Tenant.fs_scan_allowed_paths`
   (esempio `["/Users/frico/Desktop"]` per test locale Mac).
2. `/dam/fs-scan` → input path autorizzato → vedi tabella file
   classificati → seleziona alcuni → import con/senza progetto target.
3. `/projects/{id}` → bottone "🔍 Cross-check" topbar → modal con
   differenze IMDB/BoxOffice.
4. `/clients/{id}` modal → bottone "🔍 Cross-check" → idem per cliente.

16 commit locali NON pushati (b8b8bb6 → α.96). Push a major bump.

## (versione precedente)

**v3.5.0-alpha.95** — 13 maggio 2026 — Fase 5 capitolato import + Fase 3 enrichment workflow approval

Cantieri grandi 7-8 della roadmap (importanza alta, mai partiti prima):

**Fase 5 — Import capitolato → Quote bozza**:
- Wizard `/delivery-templates/import`: upload PDF/docx/xlsx → AI parsa
  voci capitolato + 8 blocchi DeliveryTemplate (opt) → matching auto
  voci listino con confidence → preview tabella editable → "Crea Quote
  bozza" genera Quote.draft con N QuoteLine linkate ai PriceItem.
- 2 endpoint nuovi (`parse-and-match`, `create-quote-from-deliverables`).
- Fix bug latente: `requires_permission("edit_settings")` non esisteva
  → tutti i mutator delivery_templates erano broken con 403.

**Fase 3 — Enrichment cliente workflow approval**:
- Modal interattivo campo-per-campo: vedi current vs proposed, decheck
  campi sbagliati, edit inline prima di applicare.
- 2 endpoint nuovi (`enrich-preview`, `enrich-apply`). Vecchio `/enrich`
  back-compat per flow create-and-enrich.

**Da testare sul Mac**:
1. Sidebar Capitolati → "Import → Quote" → upload uno dei 17 capitolati
   in `docs/capitolati_esempio/` (es. Netflix/A24/Vision). Aspettare
   ~30-60s. Vedere preview con KPI + tabella matching.
2. Override prezzo/qty/sezione su qualche riga, decheck quelle non
   pertinenti, selezionare progetto target, "Crea Quote bozza".
3. Vai a `/quotes/{id}` → vedi quote draft con righe categorizzate.
4. `/clients/{id}` → "Arricchisci con AI" → modal preview campo-per-campo.
   Decheck/edit, "Applica selezionati".

15 commit locali NON pushati (b8b8bb6 → α.95). Push a major bump.

## (versione precedente)

**v3.5.0-alpha.94** — 13 maggio 2026 — Timeline tema chiaro + spedizioni v2 + tab Spedizioni

3 task in α.94:

1. **Timeline tema chiaro fix** — Bug root: `--bg-elev` mai definito, fallback
   `#1a1d29` scuro su tema chiaro causava "rettangoli neri" su /hr. Fix in
   `:root` + audit color hardcoded planning.css (labels, time-axis,
   nesting-group → var() theme-aware).

2. **Spedizioni v2** — `Project.shipping_markup_pct` (default 15%), PriceItem
   "Spedizione standard" + categoria "Spedizioni" auto-create. JCL applica
   markup: 100€ + 15% = 115€ riaddebitati. UI campo markup nel modal con
   prepopolato dal Project + persist al submit.

3. **Tab Spedizioni in /assets/inout** — nuovo endpoint
   `GET /ingest-batches` con totali (costo vettori + riaddebitato cliente).
   3 KPI cards + filtri direction/payer/has_cost + tabella sortable + link
   a JCL fatturazione. Pulsante "Nuova spedizione" anche in tab.

**Da testare sul Mac**:
1. `/hr` su tema chiaro Sand/Paper/Linen/Sage → niente più rettangoli neri
2. `/storyboard` o `/planning` su tema chiaro → label risorse + header
   reparto leggibili (no testo bianco invisibile)
3. `/assets/inout` → vedi tab "🚚 Spedizioni" + KPI con totali
4. Nuova spedizione con `payer=charged_to_client` + progetto → JCL ha 115€
   se markup default 15%. Cambia markup a 25% → JCL nuova ha 125€,
   markup persiste nel Project.
5. Tab Spedizioni → click su #JCL apre cost-report del Job

14 commit locali NON pushati (b8b8bb6 → α.94). Push a major bump.

## (versione precedente)

**v3.5.0-alpha.93** — 13 maggio 2026 — Spedizioni con costi + ricarico cliente

Feature richiesta Matteo: spedizioni come entità di prima classe con
tracking del payer e ricarico automatico al cliente in fatturazione.

Estensione `IngestBatch` (raggruppava già movimenti per DDT) con:
- `carrier`, `tracking_number`, `shipping_cost` — batch-level
- `shipping_payer`: `internal` / `client_direct` / `charged_to_client`
- `pickup_mode`: `we_ship` / `client_carrier_pickup` / `client_in_person`
- `billable_to_project_id` + `auto_billed_jcl_id`

Endpoint nuovo `POST /physical-assets/api/shipments` (transazionale).
Se `charged_to_client`: auto-crea JobCostLine `[Spedizione]` sul primo
Job attivo del project (is_extra=True, billing_status=not_billed). Il
flusso fatturazione standard la includerà nel prossimo BillingBatch.

Modal UI `🚚 Nuova spedizione` su `/assets/inout` topbar: form completo
con asset selector multi (fisici + digitali), search, badge tipo.

**Smoke test E2E**: 2 batch creati (internal + charged), JCL #8629
generata correttamente, total_accrued=80€.

**Da testare sul Mac**:
1. `/assets/inout` → bottone "🚚 Nuova spedizione" (nuovo, topbar)
2. Compila: direzione outgest, vettore DHL, costo 50€, pickup we_ship,
   payer internal → selettore asset (alcuni fisici + digitali) → submit
3. Verifica: appare nella lista movimenti con DDT generato, niente JCL
4. Ripeti con payer=`charged_to_client` + progetto valido → JCL creata
   visibile nel cost report del Job (categoria/desc inizia con `[Spedizione]`)
5. Rifletti nel ciclo fatturazione: la JCL Spedizione entra nel prossimo
   BillingBatch trasmesso per quel Job (categoria estratta da desc)

13 commit locali NON pushati (b8b8bb6 → α.93). Push a major bump.

## (versione precedente)

**v3.5.0-alpha.92** — 13 maggio 2026 — 6 task Matteo (compose-invoice fix + drawer storico + light themes + sezioni quote)

Risposta a 6 punti aperti da Matteo (sessione mattina 13 mag):

1. **T1** In/out Asset: click row apre drawer laterale 420px con storico
   completo movimenti + link "→ Asset fisico" per i physical.
2. **T2** PhysicalAsset: tab "📦 Contenuti del supporto" nel modal Edit con
   current + history (checkbox "Mostra rimosso"). Seed simulato 40 asset
   × 3-10 file via `scripts/seed_asset_memberships.py`.
3. **T3** Compose-invoice "Errore sconosciuto": route order bug.
   `/composable-batches` veniva catturato da `/{batch_id}` → 422. Spostata
   sopra. Bonus parsing 422 in `global.js`.
4. **T4** Quote sezioni: modal pulito sostituisce `prompt()` per
   `section_label`. Badge `📦 Nome` visibile su ogni riga (cliccabile).
   Chip suggeriti delle sezioni esistenti.
5. **T5** 3 nuovi temi chiari (Paper/Linen/Sage) + fix `color-scheme: light`
   per dropdown su temi chiari (era hardcoded `dark`).
6. **T6** Suppliers: `mf-sortable` su entrambe le tabelle + chip
   "Solo scadute" su fatture passive.

**Da testare**:
1. `/finance` → "Componi fattura periodo": ora vede batch in cassetto (o
   "nessuno"); niente più "Errore sconosciuto".
2. `/assets/inout` → click su riga apre drawer storico per quell'asset.
3. `/physical-assets` → apri un asset (es. CRU-0003 / HDD-0008): vedi
   "Contenuti del supporto" con file mock + storico rimossi.
4. Topbar palette → vedi 3 nuovi temi chiari (Paper/Linen/Sage). Attiva
   uno qualsiasi: dropdown nativi (es. Cliente in Asset fisici) ora chiari.
5. `/quotes/X` → click sul pulsante 🏷 su una riga: si apre modal Sezioni
   invece del prompt vecchio. Badge `📦 Nome` visibile sulla riga.
6. `/suppliers` → click su un `<th>` ordina. Checkbox "Solo scadute" filtra.

12 commit locali NON pushati (b8b8bb6 → α.92). Push a major bump.

## (versione precedente)

**v3.5.0-alpha.91** — 13 maggio 2026 — Audit pre-push: P0+P1 fix da 3 code review

Multi-audit a fine giornata con 3 agent code-reviewer paralleli (uno per
α.88/89/90). Bug confermati ad alta confidenza fixati prima del push:

- **P0** `/finance/forecast` redirect 302 → `?tab=forecast` (fragment veniva
  strippato, atterrava sempre su Cassa)
- **P0** `AnomalyEntry.dedup_key` UniqueConstraint enforced + auto-migrate
  con DELETE duplicati esistenti
- **P1** `mancato_recupero` deriva project_id da `inv.job.project_id`
- **P1** DAM tag CSV: refactor a `exists()` subquery (no più righe duplicate)
- **P1** `compose_invoice` `jcl.billed_amount = bl.total_approved` (overwrite)
- **P1** `compose_invoice` race su Invoice.number → 409

P2 lasciati (todoEdit undo, soft-delete filter detector, reopen orphan,
sort stopPropagation) — non-bloccanti.

**Push fatto**: 11 commit (b8b8bb6 → α.91) ora su origin/main.

## (sessione chiusa 13 maggio sera tardi)

Matteo stanco, andiamo a dormire. Da rispondere domani:
1. **Pass-through OT al cliente · ATTIVO** non sembra cambiare nulla.
   Verificare dove dovrebbe mostrare differenza nel cost report (esempio
   numerico con OT 6h × 1.30 → JCL.total_accrued gonfiato). Vedi commento
   in [[project-pass-through-ot]] (memory da creare).

## (versione precedente)

**v3.5.0-alpha.90** — 13 maggio 2026 — Accrual billing + 4 fix Matteo

4 ticket post-test S4:
- **C1** Fatture lista mostra Progetto · Batch mostra Cliente (endpoint arricchiti)
- **C2** Accrual billing — batch approved restano in cassetto; nuovo modal
  "📦 Componi fattura periodo" aggrega N batch dello stesso progetto in
  1 fattura. `Project.billing_frequency` (monthly/quarterly/milestone/
  on_completion/custom) configurabile (UI in roadmap)
- **C3** Cost report list sort fixato (event delegation globale)
- **C4** Cashflow filtri spostati dalla topbar a card dedicata (erano clippati)

392 routes (+2 endpoint: compose-invoice + composable-batches).
+1 colonna `projects.billing_frequency` (auto-migrate).

**Da testare domani**:
1. `/finance` tab Fatture → vedi colonna Progetto (era assente)
2. `/finance` tab Batch → vedi colonna Cliente
3. `/finance` topbar → bottone "📦 Componi fattura periodo": apri modal,
   seleziona progetto con batch approved in cassetto, anteprima live,
   conferma → fattura unica + tutti i batch linkati
4. Cost report list → click su qualsiasi `<th>` ordina ✅
5. `/finance/cashflow` → vedi filtri cliente/progetto in card sopra le tab

9 commit locali NON pushati (b8b8bb6 → α.90). Push a major bump.

## (versione precedente)

**v3.5.0-alpha.89** — 12 maggio 2026 notte — Sprint S4 Workflow anomalie fatturazione

Stateful workflow per anomalie (era stateless). Tassonomia confermata:
extra_after_billed / sforamento_monte_ore / quote_discrepancy / mancato_recupero / over_budget.

- Modello nuovo `AnomalyEntry` (dedup_key idempotente)
- Detector service `anomaly_detector.py` con 5 funzioni di detect
- Router `/finance/api/anomalies/v2*` (list/summary/detect/handle/bulk/dismiss/reopen)
- 4 azioni: rimanda_commerciale | rivaluta_producer | write_off_loss (→ LossEntry) | overhead_cost (→ OverheadCost)
- UI `/finance` tab Anomalie totalmente refatturata: chip status/type, multiselect, bulk-action bar
- RBAC: view_anomalies + handle_anomalies (admin auto-resync)

390 routes (+5). 1 nuova tabella `anomaly_entries`.

**Test domani**: cliccare "🔄 Rileva" sul tab Anomalie, poi selezionare 1-2
anomalie open, applicare "Pozzo costi" o "Write-off", verificare creazione
OverheadCost/LossEntry, riaprire l'anomalia per testare reopen.

8 commit locali NON pushati (b8b8bb6 → α.89). Push a major bump.

## (versione precedente)

**v3.5.0-alpha.88** — 12 maggio 2026 — Maratona feedback Matteo (9 batch B1→B9)

Risposte alla lista 26 ticket UX/funzionali post-test sera 12 mag. Tutte in
unica alpha (consolidamento, no nuove feature di dominio).

- **B1** Cost Report: KPI compatti, Risorse sopra, Voci full-width, no Timesheet,
  click risorsa → solo job del progetto corrente
- **B2** Cashflow + Forecast accorpati in 2-tab (`/finance/cashflow#forecast`);
  fix dropdown bianco-su-bianco (`color-scheme: dark`)
- **B3** Fatture: filtro "Solo scadute" (`only_overdue=true` server-side)
- **B4** Anomalie: chip toggle 4 categorie + isola con doppio-click + diag job orfani
- **B5** DAM modal filtri avanzati (multi-select tag search), Physical Assets
  filtri cliente/progetto/periodo/search aggiunti
- **B6** Helper `mfEnableSortableTables()` (global.js) — `class="mf-sortable"`
  applicata a 11 tabelle elenco
- **B7** Bottone "✏ Modifica booking" in popup Storyboard/Per progetto/Le mie
- **B8** Legenda timeline estesa (Ferie/Malattia/Festività/Weekend), filtro
  "Nascondi non fatte" riposizionato, drop multi-move ora incrementale (5-6s → <100ms)
- **B9** Hyperlink visibility audit (underline dotted plain anchor) + bordi card+table

385 routes invariato. No DB migration.

## (versione precedente)

**v3.5.0-alpha.87** — 12 maggio 2026 — Sprint S8 Pozzo costi / Spese aziendali

- Modello nuovo `OverheadCost` standalone (cluster D.2 ticket Matteo) — costi
  non fatturabili in 11 categorie (maintenance/software/rent/staff/capex/training/
  marketing/legal_admin/bank_fees/tax/other).
- Write-off restano in LossEntry (single source of truth) — summary UNION.
- Tenant `capex_threshold_eur` configurabile (default 500€) per auto-CAPEX
  da PhysicalAsset.
- RBAC view_overhead + edit_overhead — admin auto-resync ALL_PERMISSION_KEYS.
- Router /overhead CRUD + summary KPI + categories.
- UI page /overhead/ con MFFilterBar + KPI grid + breakdown per categoria +
  tabella + modal full (recurring/CAPEX conditional fields).
- Cashflow extension: overhead_paid + capex_paid per mese.
- Sidebar link "💸 Spese aziendali" in sezione Finanza.

385 routes (+7). 1 nuova tabella + 1 colonna tenant.

Plus Sprint S7 (config-only, stesso giorno): MCP mcp-fattura-elettronica-it
(21 tool SDI), VoltAgent subagent marketplace globale, 3 custom skill
(mediaflow-finance-feature-dev, italian-tax-compliance, sdi-xml-builder).

## RIAPERTURA (sessione chiusa 12 mag tarda notte dopo α.88)

Ultimo commento Claude: **9 batch B1→B9 completati. Aspetta test Matteo
sulle pagine modificate prima di prossima sessione.**

Verifiche consigliate da Matteo (in ordine):

1. **Cost Report** — apri un job, controlla: KPI in 1 riga (≥1480px),
   Risorse SOPRA Voci di costo, Voci full-width senza scroll orizzontale,
   no più card "Ore lavorate consuntivo", click su risorsa in "Ore booking"
   apre drill scoped al solo progetto corrente.
2. **/finance/cashflow** — switcha tra tab Cassa/Forecast (filtri condivisi).
   Anni dropdown leggibile (era bianco-su-bianco). Forecast lazy-load.
   Vecchio link `/finance/forecast` redirect a `#forecast`.
3. **Anomalie** — chip toggle + doppio-click isola. Job orfani "vuoto" è
   atteso (richiede Job senza Quote — non presenti in dataset).
4. **Fatture** — checkbox "Solo scadute" filtra anche sent non flaggate overdue.
5. **DAM** — bottone "🎯 Filtri avanzati" → modal search + multi-tag.
6. **Asset fisici** — filtri cliente/progetto/periodo + search etichetta/serial.
7. **Liste sort** — click su qualsiasi `<th>` di clients/projects/pricelist/
   departments/overhead/delivery_templates/cost-report-list ordina.
8. **Storyboard/Per progetto/Le mie** — click booking → popup ha "✏ Modifica".
9. **Timeline** — drag-drop di un booking dovrebbe essere istantaneo (<100ms,
   era 5-6s). Legenda mostra ora Malattia/Ferie/Festività.

Aperti pre-α.88 (non toccati in questa maratona):

1. **S4 — Anomalie fatturazione workflow** (decisione D.2 RISOLTA via OverheadCost).
   Tassonomia + 3 azioni + multiselect. **NEL CANTIERE — DA RIPRENDERE.**
2. **S6 — Asset Media Hub** (BACKLOG, yoyotta/Frame.io API da indagare).
3. **Restart Claude Code** per attivare MCP `fattura-elettronica-it` (S7).

**7 commit locali NON pushati** (b8b8bb6 → α.88): alpha.84/85/86/87 + S7
config + α.88 maratona. Push rinviato a major bump (policy [[feedback-push-solo-major]]).

**Sicurezza pending:** API key Anthropic ancora da ruotare
(https://console.anthropic.com/settings/keys), era in chiaro nella conversation
log di stamattina (vedi [[project-session-12mag2026]] mattina).

## (versione precedente)

**v3.5.0-alpha.86** — 12 maggio 2026 — Sprint S3 MFFilterBar + filtri standard

- Helper `MFFilterBar` in global.js (autocomplete + date + select + text, dependsOn).
- Server: estesi 7 endpoint con filtri opzionali client_id/project_id/period/tech.
- finance.html: barra filtri globale sopra tab, applicata a tutti i tab.
- suppliers.html: filtri standard cliente/progetto/periodo.
- cost_report.html: layout swap (voci costo SOPRA ore booking) + filtri sezione.
- dam.html: filtri standard + quick chips tecnici (HDR/SDR/4K/ProRes/DCP/IMF).
- assets_inout.html: filtri cliente/progetto/periodo.

Cache-buster bump main.css + global.js. No DB migration.

## Prossimo step

Cluster S4-S6 da ticket Matteo 12 mag:
- **S4** — workflow anomalie fatturazione: tassonomia + 3 azioni + multiselect.
- **S5** — cashflow+forecast merge in 1 pagina (decisione utente: combinato default).
- **S6** — asset media hub (BACKLOG, yoyotta/Frame.io/etc. da indagare separatamente).
- Decisione semantica aperta D.2: "pozzo costi generici" (nuovo LossReason o Department "OVERHEAD"?) — da fare con Matteo prima di S4.

## (versione precedente)

**v3.5.0-alpha.83** — 11 maggio 2026 — Custom tooltip booking

**v3.5.0-alpha.78** — 11 maggio 2026 — Reportistica YoY + proiezioni + export

- Service financial_reports.py: year_over_year + ytd_projection
  (linear + realistic) + export_csv + export_xlsx multi-sheet.
- Endpoint /finance/api/reports/* (comparison, projection, export).
- Pagina /finance/reports con 4 KPI + bar export + tabella YoY +
  chart 2 barre + tabella YTD breakdown.
- Sidebar link "Report YoY + Export".
- α.77.1 toggle granularità mensile/trim/annuale anche in cashflow.

378 routes (+5).

## Prossimo step

- AI capability `propose_forecast` (scenari best/worst case via AI)
- Export PDF financial report (riusa reportlab branding)
- Tab "Forecast" dedicato dentro project_detail
- R7.x continuazione planning_bookings

## (versione precedente)

**v3.5.0-alpha.77** — 11 maggio 2026 — Financial model + sales pipeline

Pattern Salesforce/HubSpot per quote forecast:
- Quote.win_probability_pct + expected_close_date.
- Default: draft 10% · sent 30% · approved 90% · rejected 0%.
- Service quote_forecast.py: weighted + yearly_forecast.
- /finance/api/cashflow/{year} esteso: forecast_soft + committed +
  weighted + pipeline + projected_cash + win/loss totals.
- Pagina nuova /finance/forecast: 6 KPI + cascata chart + tabella +
  win/loss top 10 clienti.
- Sidebar link "Forecast / Pipeline".

373 routes (+2).

## Prossimo step

- **UI per override win_probability_pct + expected_close_date** in
  /quotes editor (form-input semplice).
- **AI capability** `propose_forecast` (analizza trend + suggerisce
  scenari best/worst case).
- **Export PDF financial report** (riusa reportlab branding).
- **R7.x continuazione planning_bookings** — quando green light.

## (versione precedente)

**v3.5.0-alpha.76** — 11 maggio 2026 — AI capability assets

3 capability nuove copilot (riusa stack α.72-α.75):
- query_physical_assets (readonly, filtri completi).
- query_asset_contents (readonly, "cosa c'è sul disco X?").
- propose_asset_movement (mutation, DDT auto).

31 AI tools (era 28). Chiude roadmap asset α.72→α.76.

## Prossimo step

- **UI contenuto** in physical_assets.html: tab "Contenuto" su modal
  asset + import manifest + scan FS button.
- **α.77 Dashboard shelf/vault** mappa storage.
- **OCR DDT entrante** (parse PDF DDT cliente).

## (versione precedente)

**v3.5.0-alpha.75** — 11 maggio 2026 — AssetMembership + manifest + fs scan

Risponde "storico HDD cliente + sistema legge disco + index".

- AssetMembership N:M digital↔physical con storico (added/removed).
- Endpoint contents (list/add/remove + manifest CSV/JSON import).
- fs_scan service: walk filesystem + xxhash64 + auto-register Asset
  + AssetMembership da path locale.
- xxhash installato.

371 routes (+5).

## Prossimo step

- **α.76 AI capability** assets: propose_asset_movement,
  query_assets_in_physical, parse_ddt_pdf (riusa supplier pattern).
- **UI contenuto** in physical_assets.html: tab "Contenuto" su modal
  asset + import manifest + scan FS button.
- **UI tracking** AssetMembership su scan page mobile.
- **α.77 Dashboard shelf/vault** mappa storage visuale.

## (versione precedente)

**v3.5.0-alpha.73** — 11 maggio 2026 — Asset In/Out unificato + digital ingest

Risponde audit Matteo:
- AssetMovement esteso con `asset_id` (digital) opt + `ingest_batch_id`.
- `IngestBatch` nuovo (raggruppa N movement, code BATCH-YYYY-NNN).
- Page `/physical-assets/inout` con vista unificata digital + physical.
- Ingest digitale: upload file → Asset DAM + Movement + DDT auto.
- Sidebar link "🚚 In/Out Asset".

366 routes (+5).

## Prossimo step

- **α.74 AssetMembership** (digital ↔ physical N:M con storico).
  "Cosa c'è dentro l'HDD X?" lookup. Import manifest CSV/JSON.
- **α.75 Filesystem scan** server-side: tool che monta path → walk +
  checksum + auto-register Asset digital + AssetMembership.
- **α.76 AI capability** propose_asset_movement, query_assets,
  parse_ddt_pdf (riusa supplier pattern).
- **α.77 Dashboard shelf/vault** mappa storage visuale.

## (versione precedente)

**v3.5.0-alpha.72.1** — 11 maggio 2026 — Fix etichetta + numerazione + batch

3 issue:
1. Fix bug: bottone etichetta crashava per joinedload vuoto.
2. Numerazione automatica: Tenant config JSON {kind: {prefix, counter,
   pad}}. Service asset_numbering.py + UI modal config.
3. Batch import: crea N asset stessa kind con label progressiva.

Endpoint nuovi: /api/numbering/{config,peek} + /api/batch-import.
UI: topbar bottoni "📦 Batch import" + "🔢 Numerazione".

361 routes (+3).

## Prossimo step (α.73 → α.77 design roadmap)

Pensata su confronto con CatDV/Iconik/Frame.io/MediaSilo:

- **α.73**: Estendi AssetMovement con asset_id (Asset digital) opt
  (mutex con physical_asset_id). Page `/assets/inout` con vista
  unificata movimenti in/out + filtri. Wizard crea movimento +
  genera asset al volo (digital file upload o physical inline).
- **α.74**: AssetMembership (digital ↔ physical N:M con storico).
  "Cosa c'è dentro l'HDD X?" lookup. Endpoint manifest CSV/JSON import.
- **α.75**: Filesystem scan (mock manifest upload per ora — full fs
  walk richiede agent locale, scope futuro).
- **α.76**: AI capability propose_asset_movement, query_assets,
  parse_ddt_pdf (riusa supplier parser pattern).
- **α.77**: UI shelf/vault dashboard (mappa storage).

## (versione precedente)

**v3.5.0-alpha.72.0** — 11 maggio 2026 — Asset fisici: logistics + DDT + QR

Sistema logistico completo per PhysicalAsset:
- Modelli: AssetMovement + AssetOwnerType + AssetMovementType enum.
- PhysicalAsset esteso con ownership (internal/client/supplier/third_party
  + owner_client_id/supplier_id/label) + qr_code_token + logistics_status.
- Service asset_qr.py: QR PNG + etichetta stampabile 60×40mm @300dpi +
  PDF DDT A5 con mittente/destinatario/colli/corriere/firme + QR.
- Router: GET movements + POST movement + POST confirm + QR/label/ddt PDF
  + scan/{token} mobile.
- UI /physical-assets: bottoni 🏷 etichetta + 🚚 movimenti per riga +
  modal lista + form "+ Nuovo movimento" + auto-open DDT PDF post-create.
- Template scan mobile: banner ownership (cliente/noleggio/interno).

358 routes (+7).

## Prossimo step

- **AI capability propose_asset_movement** — copilot crea movimento
- **OCR DDT entrante** — upload PDF DDT cliente → estrazione auto
- **Owner UI** in modal edit physical asset (selettore client/supplier)
- **Stampa multipla** etichette (selezione + grid PDF A4)
- **R7.x continuazione planning_bookings** — quando green light
- **R5/R8/R9** — tech debt

## (versione precedente)

**v3.5.0-alpha.71** — 11 maggio 2026 — Supplier parse PDF + AI query

Crea fornitore + fattura da upload PDF in un colpo. AI query readonly.

- Service `supplier_invoice_parser.py`: AI extract da testo fattura.
- Endpoint `/suppliers/api/invoices/parse-upload` + `/create-from-parsed`.
- UI `/suppliers` topbar "✨ Estrai da PDF" 2-step modal.
- AI tools nuovi: `query_suppliers`, `query_supplier_invoices` (readonly).
- Match fornitore esistente per vat_number o name.

351 routes. 28 AI tools.

## Prossimo step

- **OCR fatture scansionate** (tesseract/cloud) — scope grosso
- **UI tab Accessi TPN** estesa con toggle ip_allowlist + mfa_required
- **DAM tab "Asset interni"** + bulk-assign UI
- **JobDeliverable auto-create** da template
- **F15 esecuzione reale** sul Mac Matteo
- **R5/R8/R9** — tech debt

## (versione precedente)

**v3.5.0-alpha.70.4** — 11 maggio 2026 — MFA TOTP completa

Chiude roadmap TPN α.70.0→α.70.4.

- Dipendenze pyotp + qrcode installate (`pip install` fatto).
- User: 3 colonne nuove (mfa_secret_encrypted Fernet, mfa_enabled,
  mfa_enabled_at). Auto-migrate.
- Service mfa.py: setup/verify/disable + QR PNG generation.
- Login flow 2-step: password OK → se mfa_enabled redirect mfa-challenge.
- UI /settings tab "🔒 MFA TOTP" con setup QR + verify + disable.
- Enforcement DAM: project.mfa_required=True blocca download se user
  senza MFA (errore con hint).

349 routes (+6).

## Prossimo step

- **UI ip_allowlist + mfa_required toggle** in tab Accessi TPN del project
- **DAM tab "Asset interni"** + bulk-assign UI per asset orfani
- **Watermark video** (richiede ffmpeg integration)
- **Session timeout configurabile** per tenant
- **JobDeliverable auto-create** da template alla creazione job
- **F15 esecuzione reale** sul Mac Matteo
- **R7.x continuazione planning_bookings** — quando green light

## (versione precedente)

**v3.5.0-alpha.70.3** — 11 maggio 2026 — TPN roadmap (foundation→IP allowlist)

Roadmap TPN α.70.0→α.70.3 completata in 4 commit:

- **α.70.0** Foundation: ProjectAccessGrant + AssetAccessLog models +
  service project_access + DAM router hardenato (access check + audit).
- **α.70.1** UI: tab "🔒 Accessi TPN" su /projects/{id} +
  /admin/audit-log viewer per admin.
- **α.70.2** Watermark immagini + secure delete (DOD wipe 3-pass).
- **α.70.3** IP allowlist per progetto (Project.ip_allowlist JSON CIDR)
  + check su download. Placeholder MFA + min_role_for_access.

343 routes. 3 tabelle nuove + 3 colonne projects (auto-migrate).

**MFA TOTP non implementato** — richiede `pip install pyotp qrcode`.
Quando Matteo conferma deps → α.70.4 implementerà setup/verify/login flow.

## Prossimo step

- **α.70.4 MFA TOTP** — solo se Matteo OK su pip install pyotp + qrcode
- **UI per ip_allowlist** in tab Accessi TPN (textarea CIDR multipla)
- **DAM tab "Asset interni"** (project_id=NULL) + bulk-assign UI
- **Watermark video** via ffmpeg (scope grosso)
- **JobDeliverable auto-create** da template alla creazione job
- **F15 esecuzione reale** sul Mac Matteo (corpus 17 capitolati)
- **R7.x continuazione planning_bookings** — quando green light
- **R5/R8/R9** — split planning.html, Float→Decimal, datetime tz-aware

## (versione precedente)

**v3.5.0-alpha.69.1** — 11 maggio 2026 — Fix cashflow + filtri + drill-down

3 issue Matteo:
1. **Cashflow paid mese aprile** — root cause: Invoice paid senza
   InvoicePayment (legacy). Fix backfill in auto-migrate idempotente.
2. **Filtri progetto/cliente cashflow** — backend query params +
   dropdown UI in topbar.
3. **Cost report drill-down risorsa** — modal con job lavorati (reverse
   vista voci di costo). Endpoint `/cost-report/api/resource/{id}/jobs`.
4. **Templates capitolati vuoti** — `scripts/seed_delivery_templates.py`
   con 11 broadcaster (A24, MUBI, Vision, RAI, Sky, Netflix, Amazon
   MGM, BETA, Fremantle, NBCU). Da lanciare: `python scripts/seed_delivery_templates.py`.

335 routes (+1).

## Prossimo step

- **AI config UserAISettings reset** — Matteo deve riconfigurare in
  /settings → tab AI (key Fernet-encrypted, non recuperabile)
- **JobDeliverable auto-create** da template alla creazione job
- **AI parser PDF capitolato batch** — script che processa i 17
  capitolati esempio in `docs/capitolati_esempio/` per popolare auto
  i blocchi tech dei template seedati
- **F15 esecuzione reale** sul Mac Matteo (corpus test capitolati)
- **R7.x continuazione planning_bookings** — quando green light Matteo
- **AI parser PDF fattura passiva** — pattern simile a capitolato
- **R5/R8/R9** — split planning.html, Float→Decimal, datetime tz-aware

---

**v3.5.0-alpha.66.20.1** — 11 maggio 2026 — F15 script test corpus capitolati + push

Aggiunto `scripts/test_capitolati_corpus.py`: batch parser sui 17
capitolati reali in `docs/capitolati_esempio/` con banner colorato +
frequenza blocchi + report JSON opzionale.

Eseguibile sul Mac Matteo: `python scripts/test_capitolati_corpus.py`.
Costo stimato $0.20-0.40 per run completo.

**Push GitHub fatto** su richiesta esplicita Matteo (in deroga regola
"push solo a major bump").

---

**v3.5.0-alpha.66.20** — 11 maggio 2026 — α.66 InvoicePayment + R7.x + Capitolati F14

3 sviluppi sostanziali post recap roadmap (α.65 già fatto da prima):

- **α.66 InvoicePayment**: modello + Invoice.amount_paid denorm +
  auto-migrate + 4 endpoint payment + endpoint cashflow 12-mesi.
  Cashflow timeline UI da fare (endpoint pronto).
- **R7.x**: planning.py 4296 → 3678 righe. Estratti planning_diag.py
  (3 endpoint) + planning_unavailabilities.py (7 endpoint). Path
  esterni invariati.
- **Fase 2 step C — Capitolati F14**: nuovo prompt `PARSE_TEMPLATE`
  + funzione `parse_delivery_template` + router + pagina HTML
  `/delivery-templates` con upload→preview→edit→save degli 8 blocchi.
  Sidebar link in sezione Media.

**Decisioni billing chiuse con Matteo** (3 trade-off da memoria
billing_roadmap): solo overtime APPROVED conta, day-unit lineare,
booking interni esclusi. Engine attuale `_booking_hours_weighted`
già rispetta tutte (codice pre-esistente).

**Smoke**: AST OK su 10 file. +22 endpoint totali.

## Prossimo step

- **F15** — Test E2E parser su 17 capitolati in
  `docs/capitolati_esempio/`. Verificare confidence + completezza
  blocchi su corpus reale (A24, Netflix, Amazon, NBCU, Sky, RAI,
  Vision, MUBI, …).
- **Cashflow timeline UI** — `/finance/cashflow` pagina che disegna
  endpoint `/finance/api/cashflow/{year}` come 12-mesi stacked
  (invoiced/paid/outstanding).
- **α.67 — Resource cost-side**: `Resource.hourly_cost` + `JCL.total_cost_accrued`
  + margine reale per riga. Migrazione DB.
- **α.68 — Supplier/SupplierInvoice**: modulo nuovo esterni.
- **R7.x continuazione**: estrarre `planning_bookings.py` (~1500 righe
  ancora in planning.py: create_booking, PUT, multi-move, bulk-edit).
- **R5/R8/R9**: split planning.html (7377), Float→Decimal, datetime tz-aware.
- **Frontend polish** (in caldo, lo riprendiamo quando Matteo dice).

---

**v3.5.0-alpha.66.19** — 11 maggio 2026 — Frontend polish round 2

Dopo α.66.18 ("procedi con prossimi step"):
- **Topbar theme switcher**: bottone palette cyclable + popover
  swatches (10 temi), su ogni pagina via base.html.
- **Dashboard capacity-week strip**: 7 celle lun-dom, ore/giorno +
  fill-bar % capacità (green ≤50% / indigo ≤80% / amber ≤100% / rose
  overbook), today highlighted cyan.
- **Dashboard upcoming deadlines**: top 5 job end_date ≤14gg con
  border-left urgenza (rosso ≤3gg / amber ≤7gg / indigo ≤14gg).
- **Dashboard dept margin**: nuovo endpoint
  `/finance/api/report/departments/{year}` + service
  `departments_pl_summary`. Bar a doppia traccia revenue/cost +
  margine numerico per reparto, ordinati per volume.

## Prossimo step

In attesa feedback Matteo:
- Density preset "broadcast" come variante compatta separata
  (toggle in /planning preferences)
- Timeline item dept-icon inline (lucide via DOM injection per item)
- Quick-filter su capacity-week strip (click giorno → planning con
  filter date)
- Toggle font cyclable simile al theme switcher
- Eventuale R7.x extraction planning_diag/planning_unavailabilities

---

**v3.5.0-alpha.66.18** — 11 maggio 2026 — Frontend polish primo giro

Su richiesta Matteo "frontend più sleek, sfruttare vis.js":
- **Tema Broadcast** (10°): cyan `#00d4ff` su `#1c1c1f`, flat,
  DaVinci/Avid-style. Override scoped sidebar + card + tabelle +
  vis-timeline (linea oggi cyan, selected outline cyan, axis cyan).
- **Stat card variants**: 5 colori border-left (accent/green/amber/
  rose/purple) + `.stat-trend` pill (up/down/flat) + `.kpi-bar` 5-cell
  mini-bar (warn≥70%, danger≥85%).
- **Dashboard 4 KPI cards** ora colorate + 2 kpi-bar (jobs
  attivi/totali, risorse interne/totali).
- **Planning timeline broadcast scope**: items flat (no bevel 3D),
  heatmap capacity più alta+contrastata, reparti UPPERCASE 14px, tab
  cyan, drag-overlay cyan.

Switch tema: `/settings → Aspetto → Broadcast`. Persistito
localStorage.

**Smoke**: theme switch live (no reload necessario), stat-card
colorati, kpi-bar disegnati al load.

## Prossimo step

Dipende da feedback Matteo dopo test visivo:
- Se piace il tema Broadcast: estendere ad altri 2 temi "pro"
  (Resolve/Premiere/AfterEffects) + toggle topbar rapido
- Se la dashboard appare ancora scarna: aggiungere capacity-week
  strip + dept ROI gauge + upcoming deadlines
- Se la timeline è OK così: passare a R7.x extraction
  (planning_diag, planning_unavailabilities) come da backlog R7

---

**v3.5.0-alpha.66.17.3** — 11 maggio 2026 — Sprint R7 MVP: deprecated duplicate

Audit pattern G "file giganti" planning.py: CRUD duplicate clients/jobs
sono usati attivamente da template (dropdown/multi-filter). Decisione
conservativa: marcare deprecated POST, lasciare GET. Estrazione diag/
unavailabilities/bookings rinviata a R7.x dedicati.

**Smoke**: 303 routes invariato, version 3.5.0-alpha.66.17.3.

---

**v3.5.0-alpha.66.17.2** — 11 maggio 2026 — Sprint R6 Step 2: capability registry

Chiude pattern systemico N audit: drift _ACTION_HANDLERS (23) vs
VALID_ACTION_TYPES (13) statici → 10 capability invisibili al parser
legacy. Decorator @ai_capability registra 23 handler in
ai_capability_registry; _ACTION_HANDLERS + VALID_ACTION_TYPES derivati
auto. Drift chiuso.

**Smoke**: 303 routes invariato, 23 handler decorati, version 3.5.0-alpha.66.17.2.

---

**v3.5.0-alpha.66.17.1** — 11 maggio 2026 — Sprint R6 Step 1: legacy parser estratto

Continua R6 split ai_assistant.py. 2339 → 1785 righe (-23% totale).
Estratto ai_legacy_parser.py (156 righe) con VALID_ACTION_TYPES +
extract_proposed_actions + _balanced_json_at. Re-export in ai_assistant
per compat call site router/ai.py.

**Smoke**: 303 routes invariato, version 3.5.0-alpha.66.17.1.

---

**v3.5.0-alpha.66.17.0** — 11 maggio 2026 — Sprint R6 Step 0: ai_context.py estratto

Apre R6. ai_assistant.py 2287→1899 righe (-19%). Estratto ai_context.py
con CURRENT_TENANT + ASSISTANT_SYSTEM_PROMPT + build_context +
_build_planning_context + _short_money. Re-export per compat.

**Smoke**: 303 routes invariato, version 3.5.0-alpha.66.17.0.

---

**v3.5.0-alpha.66.16.4** — 11 maggio 2026 — Sprint R10: AI token tracking

Modello AIUsageLog + tabella prezzi 14 modelli + helper compute_cost_usd
+ log_ai_usage. Hook in ClaudeProvider.chat_with_tools (kwargs opzionali
usage_db/user/conv/tenant). Migrazione ai_loop con try/except per compat
provider non-Anthropic. Endpoint GET /ai/api/usage con totali +
breakdown user/model/day, RBAC view_finance.

**Smoke**: 303 routes (+1), $0.030 vs $0.0179 con cache 90% (40% saving),
version 3.5.0-alpha.66.16.4.

---

**v3.5.0-alpha.66.16.3** — 11 maggio 2026 — Sprint R4 Step 2: planning router migrato

Coverage R4 completata. _assert_no_blocking_slice ora delega a
booking_mutate.assert_slice_lock_safe internamente; nuova helper
_assert_no_blocking_slice_for_dates per NEW position. Tutti i 7 call
site SLICE_LOCK centralizzati nel service. Pattern systemico O chiuso.

**Smoke**: 302 routes invariato, version 3.5.0-alpha.66.16.3.

---

**v3.5.0-alpha.66.16.2** — 11 maggio 2026 — Sprint R4 Step 1: AI handlers migrati

_h_propose_move_booking + _h_propose_resize_booking ora usano
booking_mutate.assert_mutation_safe + audit_booking_mutation. ~30 righe
sostituite con 2 chiamate per handler. Bug fix collaterale: slice-lock
check su resize ora applicato sempre (prima solo dm>0).

R4.2+ migrerà router planning (PUT booking, multi-move, bulk-edit,
assignment update, delete, restore).

**Smoke**: 302 routes invariato, version 3.5.0-alpha.66.16.2.

---

**v3.5.0-alpha.66.16.1** — 11 maggio 2026 — Sprint R4 Step 0: booking_mutate service

Apre R4. app/services/booking_mutate.py con 3 helper unificati:
assert_slice_lock_safe (3 modi: current/new/force_unlock),
assert_no_overlap_after, audit_booking_mutation. Helper combinato
assert_mutation_safe per move/resize/multi-move.

Eccezioni tipate SliceLocked/BookingConflict.

R4.1 migrerà i 7 call site con check inline duplicato.

**Smoke**: 302 routes invariato, version 3.5.0-alpha.66.16.1.

---

**v3.5.0-alpha.66.16.0** — 11 maggio 2026 — Sprint R3: permission gate sweep

Pattern systemico D audit chiuso. 27 mutator senza gate su 6 router
(finance/pricelist/resources/dam/ai/planning) protetti via dependencies.
Stato finale: 76/76 mutator protetti (100%). Closure leak salary
viewer su resources.PUT.

**Smoke**: 302 routes invariato, version 3.5.0-alpha.66.16.0.

---

**v3.5.0-alpha.66.15.4** — 11 maggio 2026 — Sprint R2 Step 1: helper unique-aware

Chiude audit HIGH #2 — bug pre-check unicità Project.code che non
bypassava soft-delete (IntegrityError 500 su INSERT post-cestino).

Helper centralizzato is_unique_or_deleted_aware in
app/services/soft_delete.py. Project.create migrato. Altri call site
(quote rename, new-version, batch/job/quote numbers) già a posto.

**Smoke**: 302 routes invariato, version 3.5.0-alpha.66.15.4.

---

**v3.5.0-alpha.66.15.3** — 11 maggio 2026 — Sprint R2 Step 0: soft-delete esteso

_SOFT_DELETE_MODELS da 2 a 5 modelli: aggiunti PricelistSnapshot,
PhysicalAsset, JobDeliverable. Filter auto su SELECT, bypass via
execution_options(include_deleted=True). Chiude pattern systemico B audit.

Helper unique-aware + cascade purge orfani in R2.1+.

**Smoke**: 302 routes invariato, version 3.5.0-alpha.66.15.3.

---

**v3.5.0-alpha.66.15.2** — 11 maggio 2026 — Sprint R1 Step 2: tenant filter

Tenant filter applicato a list+by-id critici dei 4 router maggiori
(quotes/jobs/cost_report/dam). Pattern transitorio
`CURRENT_TENANT = current_tenant_id()` a livello modulo. Sweep su altri
servizi (cost_line_sync, billing_slice_guard, reverse_quote, ecc) +
billing/finance/hr router rinviato a R1.3/R1.4.

**Smoke**: 302 routes invariato, version 3.5.0-alpha.66.15.2.

---

**v3.5.0-alpha.66.15.1** — 11 maggio 2026 — Sprint R1 Step 1: context DI

Single source of truth per tenant scope: app/context.py con
get_tenant_id (FastAPI dep), current_tenant_id (service layer),
get_optional_tenant_id (endpoint pubblici). Stub ritorna 1.
Future-ready per Fase 7 senza toccare call site.

**Smoke**: 302 routes invariato, version 3.5.0-alpha.66.15.1.

---

**v3.5.0-alpha.66.15.0** — 11 maggio 2026 — Sprint R1 Step 0: tenant_id orfani

Apre il sprint R1. Quote/Job/JobCostLine/Asset acquisiscono colonna
tenant_id (default=1, ALTER TABLE auto al boot). Comportamento runtime
invariato. UNIQUE constraints restano globali (R1.5 dedicato).

Project aveva già tenant_id (audit aveva sbagliato lì).

**Smoke**: 302 routes invariato, ALTER TABLE testate sul DB reale (vuoto),
version 3.5.0-alpha.66.15.0.

---

**v3.5.0-alpha.66.14.9** — 11 maggio 2026 — CSS extract da planning.html

Apre il refactor "file giganti" suggerito dall'audit. planning.html da
7377 → 6747 righe (–9%). CSS vive in app/static/css/planning.css (682
righe). Cache HTTP indipendente, IDE meno stressato, diff git pulito.

PR2 (split partial Jinja) e PR3 (moduli JS) restano backlog R5.

**Smoke**: 302 routes invariato, version 3.5.0-alpha.66.14.9.

---

## Cantiere consolidamento (M1) — quick wins post-audit

**Sessione 11 maggio 2026** — chiuse 11/11 quick wins:

| QW | Versione | Descrizione | File toccati |
|----|----------|-------------|--------------|
| 1  | α.66.14   | Modal a11y completa (focus trap + Esc + ARIA) | global.js |
| 2  | α.66.14.1 | Light mode auto-on planning sopra soglia | planning.html |
| 3  | α.66.14.2 | Auth fail-closed via env flag | config.py + auth.py + 5 router |
| 4  | α.66.14.3 | Tenant scope build_context AI | ai_assistant.py |
| 5  | α.66.14.4 | Upload copilot security (auth+MIME+ownership) | copilot_attachments.py + ai.py |
| 6  | α.66.14.5 | Permission gate mutator quote (11 endpoint) | quotes.py |
| 7  | α.66.14.6 | Slice-lock re-check su new dates AI move/resize | ai_assistant.py |
| 8  | α.66.14.7 | Anthropic prompt caching (~90% saving) | ai_provider.py |
| 9  | α.66.14.8 | Numbering service unificato + soft-delete bypass | numbering.py + quotes.py + billing.py |
| 10 | α.66.14.8 | (combinato con 9) include_deleted ovunque pre-check | (vedi 9) |
| 11 | α.66.14.9 | CSS extract planning.html (–9% righe) | planning.html + planning.css |

**11 commit**, tutti su origin/main al prossimo push (autorizzazione Matteo).

**Prossimo step (M1 in corso)**: sprint R1 (tenant scope DI), R2 (soft-delete
framework completo), R3 (permission gate sweep su tutti i mutator). Vedi
audit roadmap sopra.

---

**v3.5.0-alpha.66.14.8** — 11 maggio 2026 — Numbering service unificato

Pattern systemico C dell'audit. app/services/numbering.py centralizza
le 3 funzioni _next_*_code (quote/batch/job). Tutte ora con
include_deleted=True esplicito (chiude bug riciclo code da cestino su
job e batch). Quote già aveva il bypass, ora consolidato.

with_retry_on_unique disponibile per race condition; wrapping sui call
site rimandato a sprint R4 (richiede refactor signature).

**Smoke**: 302 routes invariato, version 3.5.0-alpha.66.14.8.

---

**v3.5.0-alpha.66.14.7** — 11 maggio 2026 — Anthropic prompt caching

Saving stimato ~90% sui costi input copilot Claude ricorrenti. System
prompt + tools schema marcati cache_control ephemeral in chat_with_tools.
Soglia minima 1024 tokens (Claude 3.x+), sopra quella → cache hit a 0.1×
del costo cold. Logging hit_ratio per monitoring.

**Smoke**: 302 routes invariato, version 3.5.0-alpha.66.14.7.

---

**v3.5.0-alpha.66.14.6** — 11 maggio 2026 — Slice-lock re-check AI move/resize

Chiude bypass slice-lock documentato in audit HIGH services #5: AI
handlers controllavano find_blocking_slice sulla posizione OLD del
booking, ma move/resize potevano portarlo dentro un nuovo slice billed
non visto. Re-check con find_blocking_slice_for_dates su new_min/new_max
prima dell'apply. Allineato all'invariante α.66.5.

**Smoke**: 302 routes invariato, version 3.5.0-alpha.66.14.6.

---

**v3.5.0-alpha.66.14.5** — 11 maggio 2026 — Permission gate mutator quote

11 mutator quote senza permission check (audit HIGH #4) ora protetti via
`Depends(requires_permission("edit_quotes"))` come router-level dependency.
Pattern `RequireEditQuotes` riusabile a inizio modulo.

**Smoke**: 302 routes invariato, version 3.5.0-alpha.66.14.5.

---

**v3.5.0-alpha.66.14.4** — 11 maggio 2026 — Upload copilot security

Chiude 3 buchi auth+MIME+ownership su /ai/api/upload e attachment pipeline.
Magic-bytes validati prima del write. file_id include prefisso user_id
per ownership server-side senza persistence DB. Auth required (compat dev).

**Smoke**: 302 routes invariato, version 3.5.0-alpha.66.14.4.

---

**v3.5.0-alpha.66.14.3** — 11 maggio 2026 — Tenant scope build_context AI

Chiude cross-tenant data leak latente in build_context/build_planning_context.
Filtri tenant_id su Client/PriceItem/PriceCategory/Department/Resource/Booking.
Modelli senza tenant_id (Project/Quote/Job/JobCostLine/Asset) marcati TODO R1.

**Smoke**: 302 routes invariato, version 3.5.0-alpha.66.14.3.

---

**v3.5.0-alpha.66.14.2** — 11 maggio 2026 — Auth fail-closed via env flag

Chiude l'auth bypass effettivo causato dal fallback "primo admin attivo"
quando il cookie JWT è assente o scaduto. Default DEV invariato. In
produzione: settare `AUTH_REQUIRED=true` in `.env`.

Singleton `app/services/auth.py:resolve_current_user` sostituisce 5
copie identiche nei router. ~30 call site beneficiano senza modifiche.

**Smoke**: 302 routes invariato, version 3.5.0-alpha.66.14.2.

---

**v3.5.0-alpha.66.14.1** — 11 maggio 2026 — Light mode auto-on planning

Risolve il rischio "freeze Chrome al primo accesso con dataset reale".
Light mode (α.46.2) ora si auto-attiva una volta sopra soglia (items > 80
OR groups > 15) con toast informativo, ma rispetta la scelta utente
permanente se ha mai toccato il toggle manualmente.

**Smoke**: 302 routes invariato, version 3.5.0-alpha.66.14.1.

---

**v3.5.0-alpha.66.14** — 11 maggio 2026 — Modal a11y completa

Apre il "cantiere consolidamento" post-audit profondo. Quick win
foundazionale: tutti i ~30 modali ora hanno focus trap, Esc handler,
aria-modal, restore focus al close, stack di modali annidati gestito
correttamente. Una sola modifica nel helper `openModal/closeModal` di
`global.js`, zero template da toccare. WCAG 2.1.2 + 2.4.3 a posto.

**Smoke**: 302 routes invariato, version 3.5.0-alpha.66.14.

---

**v3.5.0-alpha.66.13** — 10 maggio 2026 — Branding aziendale completo

Personalizzazione documenti azienda applicata a quote PDF, cost report
cliente PDF e fattura PDF: logo + tagline + brand_color + intestazione
documento + footer "Generato con MediaFlow" toggleable per white-label.

**Tenant esteso** (4 campi, ALTER TABLE auto al boot):
- tagline + brand_color (hex) + show_powered_by + document_header

**Service nuovo**: `app/services/branding.py` con `get_branding(db)`
single source of truth per tutti i PDF.

**PDF aggiornati**: quote (logo nell'header, brand_color sul titolo),
cost report cliente (parametro `branding=` nuovo), invoice (footer
toggleable). Tutti rispettano `show_powered_by=False` per white-label.

**UI /settings#company**: blocco "Branding documenti" con tagline,
color picker + hex sincronizzati, intestazione documento, checkbox
powered_by.

**Smoke E2E**: PUT con brand_color #a855f7 + powered_by=false → 200,
get_branding helper restituisce dict completo.

**Smoke**: 302 routes invariato, version 3.5.0-alpha.66.13.

---

**v3.5.0-alpha.66.12** — 10 maggio 2026 — PhysicalAsset CRUD UI

Nuova pagina `/physical-assets` per gestire LTO/HDD/CRU/Blu-Ray/DVD/Case
introdotti come modello in α.66.9. Sidebar nav "Asset Fisici" sotto
"Asset Library" (icona hard-drive).

**Funzionalità**:
- CRUD completo con modal ricco (tipo, label, serial, barcode, capacità
  GB/TB auto, condizione, location, costo unitario)
- Flag ortogonali archive interno + consegna esterna
- Campi consegna: courier + tracking + delivered_to + delivered_at
  (appaiono solo quando is_delivered_external=true)
- Verifica integrità (collassabile): MD5/xxHash + last_verified +
  next_verification_due (per LTO calibrazione periodica)
- Filtri: tipo + solo archivio + solo consegnati + mostra cestino
- Soft-delete via deleted_at, restore endpoint dedicato

**Router nuovo**: `app/routers/physical_assets.py` (7 endpoint).
**Smoke E2E**: POST LTO + HDD consegnato → list → filtri tipo/delivered → OK.
**Smoke**: 302 routes (+7), version 3.5.0-alpha.66.12.

---

**v3.5.0-alpha.66.11** — 10 maggio 2026 — Cost report split cliente vs interno

Chiude il loop hardcost α.66.9. Le ore booking attribuiti a deliverable
non-time-based (DCP/ProRes/LTO) contano come hardcost interno (cliente
NON le vede); quelle attribuite a JCL time-based (color grading day) sono
fatturate al cliente come prima.

**Helper**: `is_time_based_unit(unit)` in cost_line_sync.py.

**API**: `/cost-report/api/job/{id}` espone
`summary.deliverable_hardcost_internal/hours_internal/count` (totali job)
+ per ogni cost_line: `unit_is_time_based` + `deliverable_hardcost_internal`
+ `deliverable_hours_internal` + `deliverable_count`.

**`_bookings_hours_cost(client_view=True)`**: esclude booking attribuiti a
deliverable non-billable. `_client_filtered_report()` usato da PDF/CSV/XLSX
cliente — rimuove anche `estimated_cost`, `margin` per sicurezza.

**UI `/jobs/{id}`**: nuova card KPI viola "Hardcost ore deliverable INTERNO"
visibile solo a finance, mostra € + ore + count quando ci sono deliverable.

**Smoke E2E**: 14h totali (4 DCP + 2 orfano + 8 color) → vista interna
mostra €165.06 hardcost, vista cliente solo 8h color.

---

**v3.5.0-alpha.66.10** — 10 maggio 2026 — UI cost-rate Resource con live preview

Modal `/resources` esteso con sezione "💰 Costo interno" + dropdown
`cost_type` (employee/freelance/studio/external) + blocchi condizionali
per tipo + **live preview** calcolo (es. `2800 × 13 × 1.30 / 1720h = €27.51/h`).
Backend `/resources/api/` esteso con tutti i 7 nuovi campi e ritorno
`internal_cost_hourly` confermato server-side.

Senza questa UI non era possibile testare l'hardcost α.66.9. Ora il flusso
è completo: configura cost_type su Resource → crea deliverable → attribuisci
booking → vedi `internal_hardcost.hardcost_eur` calcolato in dettaglio.

**Verifica live**:
1. `/resources` → matita su risorsa → sezione "💰 Costo interno"
2. Compila Dipendente con stipendio €2800 → vedi preview €27.51/h
3. Salva, riapri modal → valori persistiti.

---

**v3.5.0-alpha.66.9** — 10 maggio 2026 — JobDeliverable + cost-rate Resource + DAM physical + naming helper

Substrato dati per il modello deliverable. UI completa rinviata a α.66.10+.

**Nuovi modelli**: `JobDeliverable`, `PhysicalAsset` (separato da Asset
digitale per chiarezza, vedi memoria `project_dam_physical_assets`).

**Estesi**: `Asset` (+ flag archive/delivery + bridge deliverable),
`Booking` (+ job_deliverable_id per hardcost interno),
`Resource` (+ cost_type + monthly_gross_salary + freelance_hourly_cost +
studio_hourly_cost + property `internal_cost_hourly`).

**Naming helper** con 34 token e 9 preset (ISDCF DCP cinema, Netflix
Picture Archival, IMF, DPP/AS-11 broadcast, ProRes, screener, LTO label,
custom). Token resolver con build_token_dict + resolve_template +
overrides utente live.

**8 endpoint nuovi** sotto `/jobs/api/`: CRUD deliverable + naming presets
+ naming preview.

**UI MVP**: blocco "Consegne" in `/jobs/{id}` sotto Lavorazioni con lista
+ modal "Nuovo deliverable" + live preview naming dal preset.

**Smoke E2E**: create qty=3 → 3 deliverable separati con suffix (i/N) +
hardcost calc verificato (4h × €27.51 employee = €110.04).

**Smoke**: 295 routes (+8), version 3.5.0-alpha.66.9.

**Cosa NON è in α.66.9** (apre α.66.10+):
- Kanban + drag stato; UI edit completo con asset link DAM
- CRUD PhysicalAsset (modello solo, no UI ancora)
- Copilot QC (ffprobe + LLM contro spec_json)
- Cost report split cliente vs interno
- UI cost-rate in `/resources/{id}` con live preview calc
- Tool generazione nomi file completo (regole, validazione, batch)

---

**v3.5.0-alpha.66.8** — 10 maggio 2026 — Listino lean 79 → 43 (–46%) + seed_demo rifattorizzato

Scrematura del listino base secondo mappatura concordata. Le specifiche
tecniche scendono dalla voce di listino alla **descrizione di riga in
quote** (pattern modulare con placeholder). Il listino legacy 79 voci
resta disponibile come preset `legacy_2026q2_full` (α.66.7) per restore.

Aggiunto preset `lean_2026q3_v1.json` (43 voci) generato da
`scripts/build_lean_preset.py`. `scripts/seed_demo.py` rifattorizzato per
caricare il preset lean (single source of truth). Quote demo aggiornata
con voci lean + specifiche tecniche in `detail` di riga.

Hardcost preservate dove c'erano nel legacy (mix surround €500, Atmos
€800, drive €90, dubbing €200) ma **da ridiscutere in α.66.9** insieme
al modello cost-rate Resource e all'estensione DAM per asset fisici
(LTO/HDD/CRU/Blu-Ray vendibili al cliente — vedi memoria
`project_dam_physical_assets`).

**Smoke**: 287 routes invariato, version 3.5.0-alpha.66.8.
Boot DB reale: 2 preset caricati come kind=preset, no auto-apply.
Smoke seed_demo su DB pulito: 4 dept + 12 cat + 43 items + 12 quote lines.

**Cosa fa Matteo per applicare il lean al suo DB esistente**:
1. `/pricelist` → bottone `📦 Snapshot` → "🎁 Preset built-in" →
   "Preset: lean_2026q3_v1" → "Carica come snapshot"
2. Tab Lista → Ripristina → modalità Replace (auto-backup automatico)
3. Verifica con un test su una quote di prova; se non torna, ripristina
   il legacy con un click.

---

**v3.5.0-alpha.66.7** — 10 maggio 2026 — Preset legacy committato + bootstrap

Listino corrente (79 voci, 12 cat, 4 dep) salvato in repo come preset
`app/data/pricelist_presets/legacy_2026q2_full.json` (44KB schema 1.1).
Bootstrap loader nel `lifespan` carica ogni preset come
`PricelistSnapshot kind=preset` per ogni Tenant al boot, idempotente.
Sicurezza assoluta prima della scrematura α.66.8.

**Smoke**: 287 routes invariato, doppio-boot test = 1 preset (no dup).

---

**v3.5.0-alpha.66.6** — 10 maggio 2026 — Backup/restore listino con snapshot persistenti

Apertura cantiere multi-versione **Listino & Deliverable** dopo discussione
strategica con Matteo (10 maggio). Sequenza concordata:

| Versione | Cantiere | Stato |
|---|---|---|
| α.66.6 | Backup/restore listino (snapshot DB + UI dedicata) | ✅ chiuso |
| α.66.7 | Snapshot legacy committato come preset built-in | ✅ chiuso |
| α.66.8 | Semplificazione listino base (79 → 43 voci, –46%, descrizione modulare) | ✅ chiuso |
| α.66.9 | Modello `JobDeliverable` + cost-rate Resource + DAM digital/physical separato + naming helper Netflix/ISDCF | ✅ chiuso |
| α.66.10 | UI cost-rate Resource con live preview | ✅ chiuso |
| α.66.11 | Cost report split cliente vs interno (hardcost ore deliverable solo interno) | ✅ chiuso |
| α.66.12 | PhysicalAsset CRUD UI | ✅ chiuso |
| α.66.13 | Branding aziendale (logo + tagline + brand_color + powered_by toggle) | ✅ chiuso |
| α.66.14+ | UI deliverable kanban + edit completo + bridge DAM + copilot QC + cost report split UI completa | 🔜 |

**Decisioni architetturali fissate (10 maggio)** per i prossimi step:
- **Deliverable ≠ "no ore"**: anche un DCP/ProRes ha ore di produzione che vanno
  a **hardcost interno** (ore × cost_rate risorsa). Cliente NON le vede, internamente sì.
- **JobDeliverable** è entità DB nuova, terza tra `JobCostLine` (riga prezzo
  cliente) e `Asset` (file DAM). Spec_json snapshot da DeliveryTemplate.
  Booking.job_deliverable_id e Asset.job_deliverable_id come bridge.
- **Cost-rate per tipo risorsa**: aggiungere `Resource.cost_type`
  (employee | freelance | studio | external). Per employee:
  `monthly_gross_salary` + `annual_bonus_months` (default 13) +
  `cost_multiplier_oneri` (default 1.30) → calcolo deterministico orario su
  1720h/anno. Per freelance: `freelance_hourly_cost` (≠ `hourly_rate` di
  vendita). AI usata per suggerire multiplier per CCNL specifici.
- **Naming file deliverable**: campo libero con helper "Genera da template"
  (token replacement: `{project_code}`, `{territory}`, `{format}`, ecc.).
  Tool completo (regole, validazione, batch) come **α.66.11 dedicato**.
- **Quantity > 1 in quote** → conversion crea N deliverable separati.
- **QC AI engine MVP**: `ffprobe` locale + LLM contro `spec_json` (gratis,
  best-effort). Provider-pluggable per Baton/Vidcheck commerciale futuro.

**Chiuso α.66.6:**
- ✅ Modello `PricelistSnapshot` + enum `PricelistSnapshotKind`
  (manual/auto/preset). Tabella creata auto al boot, soft-delete via `deleted_at`.
- ✅ Service `app/services/pricelist_snapshot.py`: build_payload (schema 1.1
  con departments — schema 1.0 ne era privo), apply_payload con mode
  merge|replace + auto-backup pre-replace, list/CRUD snapshot, preset loader.
- ✅ 10 endpoint nuovi in `app/routers/pricelist.py` (snapshots CRUD +
  download/upload + preset list/load), tutti con permission gate `edit_pricelist`.
- ✅ UI `/pricelist`: bottone toolbar `📦 Snapshot` + modal completo
  (lista, salva, ripristina merge/replace, scarica, importa file, preset
  built-in, cestino).
- ✅ UI `/settings#data`: blocco "Listino" con shortcut + lista compatta
  ultimi 5 snapshot. Opt-in "Includi snapshot listino" in Export ZIP
  (default ON, dump in `listino-snapshots/`).
- ✅ Test idempotenza: build payload → create snapshot → apply merge → 0
  diff (4 dept updated, 12 cat updated, 79 items updated, 0 skipped).

**Smoke**: 287 routes (+10), version 3.5.0-alpha.66.6. Listino reale di
Matteo: 79 voci, 12 categorie, 4 reparti.

**Verifica live** (hard-refresh):
1. `/pricelist` → bottone `📦 Snapshot` → modal vuoto → "💾 Salva listino
   corrente" → snapshot id=1 in lista (kind=manual badge blu).
2. Modifica una voce listino → torna nel modal → "↺ Ripristina" merge →
   modifica annullata. Per replace: confirm dialog + auto-backup id
   nei stats della response.
3. "⬇ Scarica .json" → file con schema 1.1 + departments.
4. "⬆ Importa file .json" → snapshot importato (no apply automatico).
5. `/settings#data` → blocco "Listino" → bottone "💾 Salva" → toast +
   lista aggiornata.
6. Export ZIP completo → `listino-snapshots/` con N file + `_index.json`.

---

**v3.5.0-alpha.66.5.2** — 9 maggio 2026 — Fix conflict check su booking smart-split + Audit E2E α.66.5.2 (originale precedente)

---

**v3.5.0-alpha.66.5.1** — 9 maggio 2026 — Audit cleanup: bulk-edit + 5 mutator + UI legacy + AI

Audit con agente Explore post-α.66.5 ha rilevato 3 HIGH + multipli MEDIUM
rimasti disallineati. Tutti sistemati.

**Chiuso α.66.5.1:**
- ✅ **HIGH bulk-edit rotto**: UI con valori `todo/started/done/not_done`
  non-enum + backend che li validava. Fix UI con 5 valori `BookingState`
  canonici + motivazione inline per `not_done`. Fix backend con `state`
  Form param canonico + `execution_status` deprecated alias.
- ✅ **HIGH 5 mutator non sincronizzano state**: `add_assignment_to_booking`
  (revive), `delete_assignment` (empty), `delete_booking`, `restore_booking`,
  AI `_h_propose_delete_booking`. Tutti aggiungono `b.state = ...`.
- ✅ **HIGH AI recurring booking** desync permanente (status=confirmed,
  state=tentative default): aggiunto `state=BookingState.confirmed` esplicito.
- ✅ **HIGH create_booking** (POST): sincronizza `state` da `status` passato
  dal client (in entrambi i branch standard + ricorrenza).
- ✅ **MEDIUM dashboard.mySetExec** + **planning.todoSetExec**: migrate da
  `/execution` legacy → `/state`. 'planned' mappato a 'confirmed'.
- ✅ **MEDIUM filter UI tlsp-status**: aggiunto `confirmed` mancante.
  tlSelectPanelApply filtra su `state` canonico.
- ✅ **MEDIUM AI prompt + tool schema**: descrizione `propose_booking`
  parla ora di BookingState (5 stati esclusivi).

**Smoke**: 277 routes invariato, version 3.5.0-alpha.66.5.1.

**Verifica live** (hard-refresh + restart per migrazione):
1. Bulk-edit: seleziona 2+ booking → ✏ Bulk → "Cambio stato lavorazione" ha
   5 opzioni. Scegli "Non fatto" → prompt motivazione. Apply → tutti i
   selezionati cambiano stato.
2. Elimina booking → soft-delete → state=cancelled.
3. Ripristina dal cestino → state=tentative.
4. Dashboard ▶ Inizia / ✓ Fatto / ↺ Riapri → tutti via /state.
5. Filtro toolbar planning per stato → vedi 5 opzioni esclusive.
6. AI propone booking → response BookingState=tentative.

---

**v3.5.0-alpha.66.5** — 9 maggio 2026 — Stato unificato BookingState (refactor enum DB)

Rifusione architetturale: i 2 enum DB ortogonali `BookingStatus` +
`BookingExecutionStatus` ora vivono come **una sola dimensione** di 5 stati
esclusivi nel ciclo di vita.

**Sequenza** (transizioni libere):
`tentative → confirmed → in_progress → done | not_done`

Cancelled è soft-delete (azione "Elimina"), non appare nel selettore.

**Chiuso α.66.5:**
- ✅ Modello: nuovo enum `BookingState` + colonna `Booking.state` canonica.
  Helper `apply_state_to_booking` sincronizza state + status + execution_status.
  Helper `compute_state_from_legacy` per migrazione.
- ✅ Migrazione DB auto al boot: ALTER TABLE bookings ADD state + UPDATE
  popolamento da (status, execution_status). Idempotente.
- ✅ Endpoint nuovo `PATCH /api/bookings/{id}/state` + `state` nell'API
  response. Slice-lock + force_slice_unlock supportati. Notifiche su
  done/not_done. Vecchi endpoint sincronizzano automaticamente state.
- ✅ Modal: 1 select unico "Stato lavorazione" (5 valori). Motivazione
  appare solo per `not_done`.
- ✅ Context-menu: 1 submenu "🏷 Stato: <corrente>" con 4 voci esclusive
  (lo stato corrente è filtrato).
- ✅ Timeline render: 1 sola icona inline (⏳/✓/▶/✅/✗) all'inizio del
  content. CSS unificato `.tl-state-*`.
- ✅ Tutti i call site backend legacy (slice-lock/billing/recompute/AI)
  funzionano senza modifiche perché status+execution_status sono
  sincronizzati automaticamente.

**Smoke**: 277 routes (+1 endpoint), version 3.5.0-alpha.66.5. Mapping
state ↔ legacy verificato per tutti i 6 valori + edge case.

**Verifica live** (hard-refresh!):
1. Pull → migrazione automatica al boot.
2. Click destro su booking → "🏷 Stato" → submenu 4 voci → cambio.
3. Doppio-click → modal con select "Stato lavorazione" pre-compilato.
4. Booking tentative ⏳ giallo + bordo dashed + banda gialla sx.
   Confirmed ✓ verde discreto. In progress ▶ + glow. Done ✅ + bordo verde.
   Not done ✗ + tratteggio rosso.
5. Slice-lock: tentative passa, confirmed+ richiedono conferma.

---

**v3.5.0-alpha.66.4** — 9 maggio 2026 — Icone status più visibili + submenu inline + tentative nel modal

3 fix da feedback Matteo dopo α.66.3:

**Chiuso α.66.4:**
- ✅ **Icone status visibili**: ⏳ tentative ora 13px+700+text-shadow+giallo
  (#fde68a) → contrasto netto. Confirmed ✓ verde discreto opacity .85.
- ✅ **Submenu nativo**: riscritto `tlContextMenu` per supportare voci
  con `submenu: [...]` che aprono sottomenu adiacente on hover/click
  MANTENENDO il menu padre visibile. Hover su voce senza submenu chiude
  il sub aperto. Esc chiude prima il sub, poi il padre. Pattern
  applicabile a qualsiasi futuro submenu del context-menu.
- ✅ **Marcature ora submenu nativo** (era workaround "secondo
  tlContextMenu esplicito" in α.66.3).
- ✅ **Voce status BookingStatus nel context-menu come submenu**: "⏳ Stato:
  Tentative" / "✓ Stato: Confermato" → submenu con toggle.
- ✅ **Tentative/Confirmed nel modal edit**: nuovo gruppo radio sotto
  Priorità. Default tentative su create, pre-fill in edit. tlbSubmit
  invia sempre `status` Form → backend aggiorna BookingStatus.

**Smoke test**: 276 routes invariato, version 3.5.0-alpha.66.4.

**Verifica live** (hard-refresh!):
1. Click destro su booking → "🏷 Marcature" ha "▸". Hover → submenu si
   apre a destra, padre resta. Hover su altra voce padre → sub si chiude.
   Stessa cosa per "Stato: Tentative/Confermato".
2. Tentative ⏳ giallo ben visibile in timeline. Confirmed ✓ verde discreto.
3. Doppio-click → modal con nuova sezione "Stato booking" radio.

---

**v3.5.0-alpha.66.3** — 9 maggio 2026 — Submenu Marcature + icone status booking + slice-lock relax

Bundle 3 punti dopo conferma α.66.2 (DB pulito, fix doubleClick OK):

**Chiuso α.66.3:**
- ✅ **P1 Submenu Marcature**: voci ▶ Inizia / ✓ Fatto / ✗ Non fatto /
  ↺ Riapri raggruppate dietro "🏷 Marcature ▸" nel context-menu (apre
  secondo tlContextMenu adiacente con voci condizionali). Menu
  principale meno gonfiato.
- ✅ **P2 Icone status booking**: ⏳ per tentative (oltre bordo dashed),
  ✓ verde discreto per confirmed. Coesistono con icone execution_status
  ▶/✓/✗. Legenda aggiornata.
- ✅ **P3 Slice-lock relax**:
  - Tentative dentro periodo fatturato → SKIP guard (modificabili
    liberamente, niente bordo viola).
  - Confirmed dentro periodo fatturato → 409 con
    `code=SLICE_LOCK_CONFIRM_REQUIRED` + dettaglio slice/fattura.
  - Frontend `api()` globale intercetta automaticamente quel code,
    mostra confirm() con periodo+fattura, su OK re-invia con
    `force_slice_unlock=true`. Single retry, no loop. Tutti i call
    site mutator beneficiano senza cabling puntuale.
  - 5 endpoint backend con nuovo Form/query param `force_slice_unlock`:
    update_booking, update_assignment, delete_assignment, delete_booking,
    multi_move_assignments, update_booking_execution.

**Smoke test**: 276 routes invariato, version 3.5.0-alpha.66.3.

**Verifica live**:
1. Hard-refresh (cache-buster `global.js?v=3.5.0-alpha.66.3`).
2. **Marcature submenu**: click destro su booking → "🏷 Marcature ▸" →
   secondo menu con voci condizionali. Click "▶ Inizia" → toast.
3. **Icone status**: tentative mostra ⏳ + dashed; confirmed mostra ✓
   verde piccolo discreto.
4. **Slice-lock tentative**: drag-resize libero, no lock visivo 🔒,
   no blocco.
5. **Slice-lock confirmed**: drag su booking confirmed in periodo
   fatturato → confirm dialog "Stai modificando booking CONFERMATO
   in periodo fatturato. Confermi?". OK passa, Annulla → errore
   originale.

---

**v3.5.0-alpha.66.2** — 9 maggio 2026 — Fix root cause: vis-timeline doubleClick double-fire

Matteo segnala booking #99 nuovi che nascono con risorsa "duplicata" anche
quando il DB ha 1 solo assignment. Diagnosticato via logging client-side
temporaneo: **vis-timeline 7.x emette `doubleClick` due volte** (Hammer.js
+ DOM nativo) → `tlbOpenEdit` invocato 2 volte → modal con 2 righe per
1 assignment in DB.

**Chiuso α.66.2:**
- ✅ Fix root cause: dedup nel listener `tlInstance.on('doubleClick', ...)`
  con timestamp window 350ms (gap dblclick ~250ms, doppio-fire <10ms).
  1 listener, 1 guard, ~3 righe.
- ✅ Endpoint diag `GET /planning/api/diag/booking-raw/{id}` (manager+)
  lasciato in app come strumento utile per future investigazioni: dumpa
  booking + assignments + audit changes raw.
- ✅ Memoria progetto aggiornata: `feedback_vis_timeline_quirks.md` ora
  ha 4ª trappola "doubleClick double-fire (Hammer.js + DOM nativo)".

**Cosa NON era il bug**:
- Backend `create_booking` / `update_booking` corretti.
- Booking #61 (4 assignments) NON era duplicato: 2 risorse × 2 segmenti
  contigui smart-split pausa pranzo. Legittimo (α.63 lo permette).
- Audit di 8 endpoint senza guard intra-payload (multi-move, extend-as-
  series, ecc.) → potenziali fragilità ma NON il bug del #99. Si potranno
  hardenare in α.67 se serve, ma non urgenti.

**Smoke**: 274 routes (+1 endpoint diag), version 3.5.0-alpha.66.2.

**Verifica live**: hard-refresh (Ctrl+Shift+R) → doppio-click su qualsiasi
booking → modal apre con il numero corretto di righe (1 per assignment in
DB). Test su #99 (dovrebbe ora aprirsi con 1 sola riga). Test su #61
(dovrebbe aprirsi con 4 righe, ma sono legittime: 2 risorse × split pranzo).

---

**v3.5.0-alpha.66.1** — 9 maggio 2026 — Hotfix: warning duplicate-overlap nel modal edit booking

Hotfix per bug rilevato da Matteo via screenshot: modal edit booking #96
mostrava 2 righe Luca Bianchi in overlap totale (09:00–13:00 stesso giorno)
senza alcun warning. Il pannello giallo "🧹 Rimuovi duplicati" α.63 era
cablato solo nella todo-card, non nel modal edit. Dato sporco invisibile.

**Chiuso α.66.1:**
- ✅ Detection client-side `_tlbCheckDuplicateOverlaps()` nel modal edit:
  scorre le righe assignment, raggruppa per resource_id, verifica overlap
  pairwise. Se duplicati: pannello giallo + bordo rosso 4px sx sulle righe
  + bottone "🧹 Rimuovi duplicati" che riusa endpoint α.63
  `POST /api/bookings/{id}/cleanup-duplicate-overlaps`.
- ✅ Cabling: check all'apertura del modal edit (`tlbOpenEdit`), live re-check
  ad ogni cambio risorsa/orario (`tlbAssOnChange` + throttle 80ms),
  ricontrollo post-remove riga, reset warning su `_tlbReset` (modal nuovo).
- ✅ CSS `.tlb-ass-row.tl-row-duplicate-overlap`: bordo rosso 4px sx + sfondo
  rgba(220,38,38,.10), si combina con `.has-conflict` esistente.

**Smoke test**: 273 routes invariato, version 3.5.0-alpha.66.1.

**Verifica live**: apri modal edit booking #96 → ora vedi warning giallo +
2 righe rosse → click "🧹 Rimuovi duplicati" → cancella la 2ª riga,
ricarica modal pulito.

---

**v3.5.0-alpha.66** — 9 maggio 2026 — Planning quick wins: paste immediato + fasce orarie + status visivo + cambio stato dal menu

Bundle 4 punti pertinenti al planning, da feedback Matteo dopo α.65. Nessuna
migrazione DB, nessun nuovo endpoint backend (riusa quelli esistenti).

**Chiuso α.66:**
- ✅ **Ctrl+V incolla SUBITO**: era paste-mode interattivo → ora replica
  immediata +1 giorno (stessa risorsa/orario), retry automatico +2..+7gg
  su conflict. Ctrl+Shift+V mantiene paste-mode per scelta del punto.
  Voci context-menu nuove "📅 Duplica giorno dopo" e
  "📅 Duplica settimana dopo" che riusano `tlInstantPaste`.
- ✅ **Fasce orarie nel modal booking**: 3 bottoni preset 🌅 Mattina /
  ☀ Pomeriggio / 📆 Tutto il giorno sopra le righe assignment. Leggono
  da `WorkingHoursPolicy` default via `/settings/api/working-hours`
  (cached lazy). Applicano gli orari a TUTTE le righe preservando la
  data corrente di ciascuna. Fallback hardcoded 09-13 / 14-18 / 09-18.
- ✅ **Status visivo rinforzato + legenda**: CSS done con bordo verde
  3px a sx + opacity .92 (era .82) + check ✓ più grande. Nuovo bottone
  toolbar 🏷 Legenda con popover dei 5 stati booking + 2 stati
  trasversali (cross-dept, slice-locked). Pattern esistenti per
  in_progress/not_done/tentative invariati.
- ✅ **Cambio execution_status dal context-menu**: voci condizionali
  ▶ Inizia / ✓ Fatto / ✗ Non fatto (con prompt reason) / ↺ Riapri.
  Riusa endpoint `PATCH /planning/api/bookings/{id}/execution`.

**Smoke test boot**: 273 routes (invariato vs α.65, nessun nuovo endpoint),
version 3.5.0-alpha.66. Nessun errore di import.

**Verifica live richiesta a Matteo**:
1. Pull → app boot pulito (273 route, version 3.5.0-alpha.66). Niente
   migrazione DB.
2. **Ctrl+V immediato**: seleziona 1+ booking → Ctrl+C → Ctrl+V →
   replica +1 giorno con stesso orario+risorsa. Su conflict, scivola a
   +2..+7gg (toast informativo). Ctrl+Shift+V → paste-mode legacy.
3. **Context-menu duplica**: click destro su booking → "📅 Duplica
   giorno dopo" / "📅 Duplica settimana dopo".
4. **Fasce orarie**: nuovo booking modal → "🌅 Mattina" → tutte le
   righe a 09:00–13:00. Stesso per pomeriggio (14–18) e tutto il
   giorno (09–18). Hint a destra mostra l'intervallo applicato.
5. **Legenda**: toolbar planning → 🏷 Legenda → popover con i 5 stati
   spiegati + suggerimento sul cambio stato rapido.
6. **Cambio stato dal menu**: click destro su booking → vede voci
   condizionali. Marca "✗ Non fatto" → prompt reason obbligatorio.
   "↺ Riapri" appare solo su done/not_done. Timeline si aggiorna subito.

**Cosa NON cambia in α.66**:
- Nessuna migrazione DB, nessun nuovo endpoint.
- Pattern CSS esistenti per in_progress/not_done/tentative/cross-dept/
  slice-locked invariati.
- Pre-α.66 paste-mode interattivo mantenuto su Ctrl+Shift+V.

**Prossimi step**:
- α.67 candidato roadmap billing 5.b: `InvoicePayment` + cashflow
  timeline revenue-only.

---

**v3.5.0-alpha.65** — 9 maggio 2026 — Pass-through OT al cliente (opt-in) + monte ore booking interni

Primo step roadmap billing α.65+ (overtime weighted). Decisioni semantiche
prese con Matteo prima di scrivere codice (memoria
`project_billing_roadmap_alpha65plus`):
- **OT status**: solo APPROVED applica i moltiplicatori, PENDING resta
  lineare ma esposto in tooltip "+€X pending".
- **Day-unit**: conversione lineare → 8-22 con 6h OT × 1.30 = 1.725 gg.
- **Booking interni**: report HR-side separato dal cost-report cliente.
- **Scope weighted al maturato cliente**: opt-in per progetto via flag
  `Job.weighted_revenue` (default OFF). Cost-side interno
  (`_bookings_hours_cost`) era già pesato.

**Chiuso α.65:**
- ✅ **Flag `Job.weighted_revenue` (default False)** + auto-migrate
  ALTER TABLE jobs idempotente al boot (`_auto_migrate_columns` in
  `app/main.py`). Default OFF = back-compat 100% per tutti i job
  esistenti.
- ✅ **Engine weighted hours nel sync** (`app/services/cost_line_sync.py`):
  refactor `_booking_hours()` con due path (`_linear` storico +
  `_weighted` che usa `compute_assignment_breakdown.weighted_factor`
  per assignment con la WorkingHoursPolicy della risorsa). Pending OT
  NON pesato. JCL.qty per day-unit = `weighted_factor / 8`.
  `recompute_cost_line_actual()` risolve `Job.weighted_revenue` e
  attiva il path corrispondente. L'engine
  `compute_assignment_breakdown` esisteva già in
  `app/services/booking_cost.py`: nessun nuovo file richiesto.
- ✅ **UI toggle nel cost-report**: checkbox "Pass-through OT al cliente"
  in toolbar dettaglio con badge ATTIVO viola e conferma all'attivazione.
  Endpoint `PUT /cost-report/api/job/{id}/weighted-revenue` (Form):
  persiste flag + trigger automatico `recompute_for_job` per allineare
  maturato esistente. Idempotente.
- ✅ **Tooltip pending OT per riga JCL**: response /api/job/{id} espone
  `pending_overtime_hours` (sempre) + `pending_overtime_amount` (stima €
  delta maturato post-approvazione, > 0 solo se weighted_revenue ON).
  UI: badge giallo "⏳ Xh pending" con tooltip contestuale.
- ✅ **Report HR booking interni**: `GET /hr/api/internal-bookings-report`
  aggrega booking con kind ∈ {internal_maintenance, internal_research,
  internal_training} per risorsa+kind. Tab nuova "🛠 Booking interni"
  in /hr accanto a Tabella/Calendario, con filtro periodo, KPI
  (lineari/pesate/delta), card per tipologia, tabella per risorsa.
  Persistenza vista in localStorage.

**Migrazione DB**: ALTER TABLE jobs ADD COLUMN
`weighted_revenue BOOLEAN NOT NULL DEFAULT 0`. Idempotente.

**Smoke test boot**: 273 routes (+2 vs α.64), version 3.5.0-alpha.65.
Nessun errore di import, nessun crash al boot.

**Verifica live richiesta a Matteo**:
1. Pull → app boot pulito (273 route, version 3.5.0-alpha.65). DB
   migrato in automatico al primo boot (log `[auto-migrate]
   jobs.weighted_revenue mancante -> ALTER TABLE`).
2. **Pass-through OT (default OFF, opt-in)**: /cost-report → progetto
   con booking che hanno OT/notte/dom/festivo APPROVATI → toolbar
   detail ha checkbox "Pass-through OT al cliente" (default off,
   testo grigio). Click → conferma esplicita ("rifattura al cliente con
   moltiplicatori") → badge ATTIVO viola, maturato JCL aumentato (es.
   1 gg con 6h OT × 1.30 → 1.725 gg). Toggle OFF → torna a lineare.
3. **Pending OT in tooltip**: booking con `overtime_status=pending`
   → riga JCL mostra badge giallo "⏳ Xh pending". Hover → tooltip
   con stima `+€` SOLO se pass-through ON, altrimenti messaggio
   "non rifatturate al cliente con questa configurazione".
4. **Solo APPROVED conta col moltiplicatore**: pending o rejected
   → maturato resta lineare per quelle ore. Approve → trigger
   recompute (manuale via "Aggiorna ore" o automatico al toggle
   weighted_revenue) → maturato sale.
5. **Booking interni**: /hr → tab "🛠 Booking interni" → range mese
   corrente → 4 KPI cards (count, lineari, pesate, delta moltipl.)
   + card per tipologia + tabella per risorsa. Test: crea booking
   `internal_maintenance` su una risorsa → la risorsa compare con
   monte ore atteso.

**Cosa NON cambia in α.65**:
- Cost-side interno (`_bookings_hours_cost`): già pesato a prescindere,
  invariato.
- Tutti i job esistenti restano `weighted_revenue=False` → back-compat
  100% sul maturato cliente.
- Nessuna nuova colonna in JCL, nessuna modifica a slice/billing.
- Cashflow completo (5.b InvoicePayment, 5.c timeline) e supplier
  invoice (punto 6): rimandati ad α.66+ secondo roadmap.

**Prossimi step (post-test live)**:
- α.66 candidato: Punto 5.b + 5.c base della roadmap
  (`InvoicePayment` + cashflow timeline revenue-only).
- (eventuale α.65.x): se Matteo vuole anche **colonna informativa
  "OT da rifatturare"** in cost-report (delta tra weighted e lineare,
  per decidere caso per caso), aggiunta semplice senza migrazione.

---

**v3.5.0-alpha.64** — 8 maggio 2026 — Trasmissione granulare + refer-to-sales completo

Bundle "trasmissione & refer-to-sales completo" da feedback Matteo dopo α.63
(test live billing). 3 punti distinti, 1 sola release coerente. Cashflow è
un altro round (α.65+) con decisioni semantiche da fare.

**Chiuso α.64:**
- ✅ **Link strutturale [EXTRA] → JCL d'origine**: nuova colonna
  `quote_lines.referred_from_jcl_id` (FK), valorizzata dal refer-to-sales
  α.62. Badge bidirezionali UI: "↪ Da JCL #X" in /quotes (cliccabile, apre
  cost-report) e "↪ Q-NNN-NN v2" in /cost-report (link a /quotes#{id}).
  Risolve "vedo una voce extra, a cosa corrisponde?".
- ✅ **Trasmissione granulare**: la modal Trasmetti in /cost-report
  diventa tabella editable con checkbox per JCL candidata (default
  tutte checked), bottoni tutti/nessuno, subtotale dinamico in tempo
  reale, evidenza sforamenti+extra. Backend: `_transmit_core` accetta
  `jcl_ids` opzionale; endpoint Form `jcl_ids` CSV. Back-compat preservata.
- ✅ **Refer-to-sales DA batch detail**: nuovo bottone `↪ AM` (viola)
  in /finance batch detail su righe in draft con `is_extra=True` o
  `over > 0`. Combina defer (rilascio JCL) + refer (estendi/nuova quote).
  Atomico (rollback se refer fallisce). Refactor: estratto
  `_refer_jcl_to_sales_core` per riuso.

**Migrazione DB**: ALTER TABLE quote_lines ADD COLUMN
`referred_from_jcl_id INTEGER NULL REFERENCES job_cost_lines(id)`.
Idempotente, eseguita al boot via `_auto_migrate_columns`.

**Smoke test boot**: 271 routes (+3 vs α.63), version 3.5.0-alpha.64.

**Verifica live richiesta a Matteo**:
1. Pull → app boot pulito (271 route, version 3.5.0-alpha.64). DB
   migrato in automatico al primo boot (log `[auto-migrate]
   quote_lines.referred_from_jcl_id mancante -> ALTER TABLE`).
2. **Trasmissione granulare**: apri /cost-report → un progetto con
   ≥3 JCL maturate non fatturate → bottone Trasmetti → modal mostra
   tabella con checkbox di default tutte checked. Decheck 1-2 righe
   → subtotale aggiornato in tempo reale. Submit → batch creato
   contiene SOLO le righe checked, le decheck-ate restano `not_billed`
   nel cost report (sono ancora trasmissibili in un batch successivo).
3. **Link bidirezionale [EXTRA] → JCL**: in /cost-report apri un
   progetto con ≥1 JCL già "Riferita al commerciale" (α.62 + click ↪)
   → vedi badge viola "↪ Q-NNN-NN v2" sulla riga, click → apre la
   quote in nuova tab. Nella quote la riga `[EXTRA]` ha badge viola
   "↪ Da JCL #X" → click → apre cost-report del job d'origine.
4. **Refer-to-sales da batch**: in /finance apri un batch in draft
   con almeno 1 riga in over (badge `+€...` rosso) → riga mostra ora
   2 bottoni: `↪ Rimanda` (giallo, defer al consuntivo) e `↪ AM`
   (viola, refer al commerciale). Click `↪ AM` → modal extend/new +
   note → submit → la riga sparisce dal batch, la JCL torna
   `not_billed`, la quote del job ha una nuova versione con la riga
   `[EXTRA] referred_from_jcl_id=jcl.id`. Si apre in nuova tab.
5. Caso "extra batch vuoto post-refer": se rimuovi l'unica riga del
   batch via `↪ AM`, il batch resta vuoto in draft (manager può
   annullarlo manualmente — non auto-cancelliamo).
6. **Back-compat**: trasmissione senza spuntare nulla nella tabella
   = 0 selezionati → bottone disabilitato. Trasmissione classica
   (senza modificare gli check, default checked) → comportamento
   pre-α.64 (tutto trasmesso).

**Cosa NON cambia in α.64**:
- Modello straordinari weighted-hours: rimandato ad α.65 (richiede
  decisioni semantiche su solo-approved vs pending, day-unit vs hr-unit
  per la conversione).
- Costi cost-side (Resource.hourly_cost): non aggiunti.
- InvoicePayment / cashflow forecast: rimandati.
- Supplier invoice / commesse esterne (punto 6 della sessione 8 maggio
  pomeriggio): modulo nuovo, da pianificare.
- Slice lock α.59: invariato. I booking dentro slice fatturate restano
  immutabili anche con la nuova trasmissione granulare.

**Prossimi step (post-test live)**:
- α.65 candidato: engine `billable_hours.py` con coefficienti CCNL
  (overtime_brackets già nel modello tenant). Prima discussione
  semantica con Matteo, poi implementazione.
- (eventuale α.65.x): campo nullable `JobCostLine.referred_from_jcl_id`
  speculare per ereditare la catena quando una quote nata da
  refer-to-sales viene promossa a job (oggi: il link vive solo in
  QuoteLine, si "perde" alla promozione).

---

**v3.5.0-alpha.63** — 8 maggio 2026 — Bulk job-change + extend-as-series + dedup risorse

Round chiuso da feedback Matteo dopo α.62: 4 problemi distinti su pianificazione,
ognuno con causa diversa e soluzione mirata. Niente migrazione DB.

**Chiuso α.63:**
- ✅ Bulk-edit "Cambia lavorazione": dropdown candidati = tutte le JCL
  attive del progetto comune (cross-job dello stesso project OK). Errore
  esplicito se progetti diversi. Re-sync man-hours su VECCHIA + NUOVA
  cost_line per booking done. Auto-assignment risorse → nuovo job. Undo
  bulk-edit ripristina anche cost_line in 1 chiamata.
  - Endpoint nuovo: `GET /api/bookings/bulk-edit/eligible-cost-lines?ids=...`
  - Form param nuovo su `PUT /api/bookings/.../bulk-edit`: `job_cost_line_id`.
- ✅ Guard intra-payload: stessa risorsa con OVERLAP nello stesso booking
  → 400 in POST/PUT. Segmenti contigui (split pranzo) restano permessi.
  - Cleanup dati storici: `POST /api/bookings/{id}/cleanup-duplicate-overlaps`
    rimuove i duplicati pre-α.63. UI: pannello giallo nel detail con
    bottone "🧹 Rimuovi duplicati" + conferma.
  - Detail endpoint espone `has_duplicate_overlaps` + `duplicate_resource_ids`.
- ✅ Feedback chiaro skip/conflict in bulk: response include
  `skipped_locked_count` separato dai conflitti orari + ogni `failed[i]`
  ha `reason` umano (non più solo `error: "BOOKING_LOCKED_BY_SLICE"`).
  Pannello `bulk-result-detail` dentro il modal: lista per booking_id con
  motivo. Modal resta aperto se ci sono fail.
- ✅ Extend-as-series: pre-α.63 il PUT booking ignorava
  `recurrence_rule`/`recurrence_until` → toast "aggiornato" ma niente nuovi
  booking. Ora in edit mode il check "Ricorri" diventa "Estendi come serie"
  e dopo il PUT chiama `POST /api/bookings/{id}/extend-as-series`. Nuovo
  endpoint replica gli assignments shiftati per ogni occorrenza, esclude la
  data del pattern, conflict-check per occorrenza, auto-assignment risorse.

**Smoke test boot**: 268 routes (+3 vs α.62), version 3.5.0-alpha.63.

**Verifica live richiesta a Matteo**:
1. Pull → app boot pulito (268 route, version 3.5.0-alpha.63).
2. `/planning`: seleziona ≥2 booking dello stesso progetto su job diversi
   → click Bulk-edit → vedi dropdown "Cambia lavorazione" con candidati
   (codice job + descrizione lavorazione) → applica → toast "✓ aggiornati",
   timeline rispecchia il cambio job/cost-line, cost report mostra
   man-hours sulla nuova lavorazione (il vecchio JCL si decrementa).
3. Selezione su progetti diversi → dropdown disabled + warning
   "progetti diversi: non disponibile".
4. Selezione mista (1 booking dentro periodo fatturato): tooltip 🔒 vis-
   timeline + dopo Bulk applica, pannello esiti elenca quel booking come
   "🔒 bloccato (date → date, fattura N)" e gli altri vanno OK.
5. Apri il dettaglio di un booking che PRIMA aveva Sara Conti × 2 (dato
   sporco pre-α.63): pannello giallo "⚠ Anomalia". Click "🧹 Rimuovi
   duplicati" → conferma → 1 record cancellato → ricarica → Sara Conti
   appare 1 sola volta.
6. Crea un nuovo booking con stessa risorsa duplicata sovrapposta → 400
   con messaggio specifico (righe #1 e #2). Crea con stessa risorsa in
   segmenti CONTIGUI (split pranzo) → ok come prima.
7. Apri edit su un booking esistente → spunta "Estendi come serie",
   imposta regola = WEEKDAYS + data fine = +2 settimane → Aggiorna →
   toast "✓ Serie estesa: N booking aggiunti". Ricarica timeline → vedi
   le occorrenze nelle date attese (non sulla data del pattern).
   Se conflitti: alert con lista date saltate.

**Cosa NON cambia in α.63**:
- Nessuna migrazione DB.
- Slice lock α.59: sempre attivo (i booking in periodo fatturato non si
  modificano nemmeno con bulk-edit cost-line / extend-as-series).
- Convenzione segno over_under, formule cost report, status flow,
  /finance batch detail: invariati.

**Prossimi step (post-test live)**:
- Eventuali tweak feedback estensione serie (mostrare lista date in toast?).
- Roadmap billing α.59.x: endpoint rettifica per sbloccare manualmente un
  periodo dopo nota credito (rimandato finché Matteo non lo richiede).

---

**v3.5.0-alpha.62** — 8 maggio 2026 — Rimanda al commerciale

Quinto e ultimo step della riarchitettura billing concordata oggi. Il
finance ora ha un bottone esplicito per riferire un extra al commerciale:
estendi la quote esistente (versioning) o crea nuova quote linkata.
Chiude il loop Cost Report → Fatturazione → extra → commerciale.

**Chiuso α.62:**
- ✅ Endpoint `POST /finance/api/billing/refer-to-sales` (manager+):
  - `mode=extend_existing` → nuova versione della quote del job
    (parent_quote_id valorizzato), copia righe esistenti, aggiunge riga
    `[EXTRA]` con qty/prezzo derivati da JCL.accrued_post_period.
  - `mode=new_linked` → nuova Quote indipendente sul project con la sola
    riga `[EXTRA]`. Per addendum negoziati separatamente.
  - Risposta `{quote_id, quote_number, quote_url, mode}`.
- ✅ UI cost report: bottone `↪` accanto a `✎` su righe con
  `accrued_post_period > 0` o `is_extra=True && total_accrued > 0`.
  Modal con radio extend/new + textarea note. On success → toast + apri
  quote in nuova tab.
- ✅ Smoke test boot: 265 routes (+1 vs α.61), version 3.5.0-alpha.62.

**Verifica live richiesta a Matteo:**
1. Pull → app boot pulito (265 route, version 3.5.0-alpha.62).
2. Apri /cost-report → progetto con almeno una fattura emessa →
   riga con `Mat. post > 0` (es. extra after billed) → bottone `↪` visibile.
3. Click `↪` → modal "Rimanda al commerciale" → seleziona "Estendi quote
   esistente" → submit → nuova versione della quote del job creata
   (Q-...-v2), apre la quote in nuova tab. La nuova versione ha tutte le
   righe della precedente + una riga `[EXTRA]` con quantità/prezzo
   derivati da JCL.
4. Stessa azione con "Nuova quote linkata" → nuova Quote indipendente
   sul progetto con la sola riga extra.
5. Riga senza extra (Mat. post = 0 e non is_extra) → bottone `↪` non
   appare.

**Cosa NON cambia in α.62:**
- Nessuna nuova migrazione DB.
- Conversion-to-job, deletion quote, status flow: invariati.
- /finance batch detail: nessun cambiamento (il bottone è in cost report).
- Notifiche EXTRA_AFTER_BILLED di α.61 continuano a girare; il bottone è
  la risposta operativa esplicita.

**Riarchitettura billing concordata 8 maggio 2026 — completata** (α.58→α.62):
- α.58: `JCLBilledSlice` foundation (modello + emit_invoice + backfill).
- α.59: HARD-BLOCK booking dentro periodo già fatturato.
- α.60: cost report 3 colonne slice-based (Fatt. / Mat. post / Stim. fut.).
- α.61: notifica EXTRA_AFTER_BILLED automatica.
- α.62: bottone "Rimanda al commerciale" con scelta versioning vs new.

**Prossimi step (post-test live):**
- (eventuale α.59.x): endpoint di rettifica per sbloccare manualmente
  un periodo, se serve dopo test live.
- (eventuale α.62.1): bottone Rimanda anche in /finance batch detail.

---

**v3.5.0-alpha.61** — 8 maggio 2026 — Notifica EXTRA_AFTER_BILLED

Quarto step della riarchitettura billing. Le slice di α.58 + il guard di
α.59 + le 3 colonne di α.60 + ora la notifica automatica quando emerge
maturato post-fatturazione: il loop "lavoro pre-fattura → fattura →
lavoro post-fattura" ha la sua sentinella attiva.

**Chiuso α.61:**
- ✅ Modello: `NotificationKind.extra_after_billed` aggiunto. No migration.
- ✅ Service: `billing_slice_guard.maybe_notify_extra_after_billed(db, jcl)`
  — emette notifica se la JCL ha almeno una slice e maturato eccede
  fatturato. Idempotente (skippa se notifica già non-archiviata per la
  stessa JCL). Severity action_required. Destinatari ruoli admin/manager/
  producer/accounting. Link a `/cost-report#job-{id}`.
- ✅ Hook in `cost_line_sync.recompute_for_booking`: dopo recompute,
  chiama il notify (try/except non bloccante).
- ✅ Smoke test boot: 264 routes, version 3.5.0-alpha.61.

**Verifica live richiesta a Matteo:**
1. Pull → app boot pulito.
2. Progetto già fatturato (con almeno una slice). Crea un nuovo booking
   sulla stessa JCL ma con date posteriori al period_end della slice
   (così il guard α.59 non blocca). Marca il booking done.
3. Attendi recompute → in /notifications vedi una notifica
   `⚠ Extra emerso su progetto fatturato: <progetto>` con severity ambra.
4. Marca un secondo booking done sulla stessa JCL → no nuova notifica
   (idempotenza). Cresce solo l'`extra_amount` reale ma la notifica
   esistente già copre il caso.
5. Archivia la notifica → il prossimo recompute dello stesso JCL può
   ri-emetterne una nuova (utile se il problema persiste tra periodi).
6. Solleva un booking su una JCL SENZA slice → niente notifica
   (non è "after billed", è semplicemente maturato non ancora trasmesso).

**Cosa NON cambia in α.61:**
- Trigger solo da recompute_for_booking. Se l'extra emerge per edit
  diretto JCL (raro), niente notifica (estendibile in α.61.x).
- UI notifiche: invariata, riusa il rendering generico esistente.
- Nessuna nuova route, nessuna migrazione DB.

**Prossimi step (roadmap riarchitettura billing):**
- α.62: bottone "Rimanda al commerciale" da /finance con scelta
  esplicita estendi quote esistente (versioning) vs nuova quote linkata
  al progetto.
- (eventuale α.59.x): endpoint di rettifica per sbloccare manualmente
  un periodo, se serve dopo test live.

---

**v3.5.0-alpha.60** — 8 maggio 2026 — Cost report 3 colonne slice-based

Terzo step della riarchitettura billing. Le `JCLBilledSlice` introdotte in
α.58 ora alimentano una vista a 3 colonne nel cost report che separa il
"chiuso contabile" dal "maturato non ancora fatturato" dalla "stima
futuro". Permette al producer di vedere a colpo d'occhio: "ho già fatturato
X, ho Y pronto da trasmettere, attendo altri Z".

**Chiuso α.60:**
- ✅ `app/services/billing_slice_guard.py` esteso:
  `billed_locked_for_jcl`, `billed_locked_bulk` (singola query GROUP BY),
  `three_column_view(jcl, billed_locked)` → dict {billed_locked,
  accrued_post_period, forecast_future}.
- ✅ API `/cost-report/api/list` e `/api/job/{id}`: aggiunti
  `billed_locked` / `accrued_post_period` / `forecast_future` in summary
  per-job e per ogni cost_line. Pre-fetch bulk per evitare N+1.
- ✅ UI cost report detail view:
  - KPI grid: 3 nuove card (Fatturato chiuso / Maturato post-periodo /
    Stimato futuro) con tooltip.
  - Tabella cost lines: colonne Maturato + Stimato sostituite da
    Fatturato + Mat. post + Stim. fut. (3 colonne separate).
- ✅ Smoke test boot: 264 routes, version 3.5.0-alpha.60.

**Definizione delle 3 colonne (per riga e aggregato):**
- `billed_locked` = Σ slice.billed_amount (immutabile, già fatturato).
- `accrued_post_period` = max(0, total_accrued − billed_locked) (done
  ancora senza slice → prossimo candidato di trasmissione).
- `forecast_future` = max(0, total_expected − total_accrued) (planned
  non done → ulteriori ore stimate).

Identità di consistenza:
- billed_locked + accrued_post_period = total_accrued (= maturato totale).
- billed_locked + accrued_post_period + forecast_future = total_expected.

**Cosa NON cambia in α.60:**
- Lista cost report (vista riassuntiva top): invariata.
- Convenzione segno over_under (positivo = OVER) e formule esistenti.
- Export PDF/CSV/XLSX: invariati (potrà essere esteso se richiesto).
- Nessuna migrazione DB.

**Verifica live richiesta a Matteo:**
1. Pull → app boot pulito (264 route, version 3.5.0-alpha.60).
2. /cost-report → progetto con almeno una fattura emessa →
   - KPI: vedi cards "Fatturato chiuso" (verde, importo fatture) /
     "Maturato post-periodo" (ambra, ore done senza slice) /
     "Stimato futuro" (planned non done).
   - Tabella cost lines: 3 colonne dedicate (Fatturato / Mat. post / Stim. fut.).
3. Progetto ancora senza fatture → Fatturato chiuso = €0 ovunque,
   Mat. post = total_accrued, Stim. fut. = total_expected − total_accrued.
4. Marca un booking done in più → Mat. post cresce della somma.
5. Emetti una nuova fattura su batch draft → Mat. post scende del
   total_approved del batch, Fatturato chiuso sale dello stesso importo.

**Prossimi step (roadmap riarchitettura billing):**
- α.61: notifica `EXTRA_AFTER_BILLED` (extra emerso su periodo già
  slice-ato) → destinatari accounting + commerciale del progetto.
- α.62: bottone "Rimanda al commerciale" da /finance con scelta
  esplicita estendi quote esistente (versioning) vs nuova quote linkata
  al progetto.
- (eventuale α.59.x): endpoint di rettifica per sbloccare manualmente
  un periodo, se serve dopo test live.

---

**v3.5.0-alpha.59** — 8 maggio 2026 — HARD-BLOCK booking in periodo fatturato

Secondo step della riarchitettura billing. Le `JCLBilledSlice` introdotte
in α.58 sono ora attive come invariante: un Booking dentro un periodo già
fatturato è immutabile (drag, resize, cancel, exec_status, bulk-edit,
multi-move, AI tool_use → 409). Per cambiare quei booking serve emettere
nota credito o cancellare la fattura.

**Chiuso α.59:**
- ✅ Servizio nuovo `app/services/billing_slice_guard.py`:
  `find_blocking_slice(db, booking)`, `find_blocking_slice_for_dates(db,
  jcl_id, start, end)`, `slice_lock_message(slice)`, `slice_lock_payload(slice)`.
- ✅ Helper locale `_assert_no_blocking_slice` in `app/routers/planning.py`
  che solleva `HTTPException(409, detail={code: "BOOKING_LOCKED_BY_SLICE",
  message, slice})`. Applicato in: update_booking, update_assignment
  (sia date attuali sia nuove proposte), delete_booking, delete_assignment,
  update_booking_execution, bulk_edit (skippa locked), multi_move (atomico).
- ✅ Helper analogo `_assert_no_blocking_slice` in `app/services/ai_assistant.py`
  che solleva `ValueError`. Applicato in `_resolve_booking_for_planning`
  (copre move/resize/delete AI) e in bulk_move handler.
- ✅ `_assert_jcl_not_locked` rifocalizzato: ora blocca solo `in_batch`.
  Per `billed`/`paid` il check granulare è il guard slice-based.
- ✅ `GET /planning/api/bookings`: ogni assignment include `slice_lock` in
  `extendedProps` (slice_id, period_start, period_end, invoice_number).
  Singola query pre-fetch (no N+1).
- ✅ UI timeline: classe `.tl-slice-locked` (bordo viola + 🔒) + tooltip
  con periodo + fattura. CSS in `planning.html`.
- ✅ Smoke test boot: 264 routes, version 3.5.0-alpha.59.

**Cosa NON cambia in α.59 (per scelta):**
- Endpoint dedicato di rettifica (nota credito + riapri periodo): rimandato
  ad α.59.x se Matteo lo chiede dopo il test live.
- UI cost report: invariata (3 colonne arrivano in α.60).
- Nessuna migrazione DB.

**Verifica live richiesta a Matteo:**
1. Pull → app boot pulito.
2. Su `/planning` apri un periodo che include booking di un progetto
   già fatturato → vedi bordo viola + 🔒 sui booking dentro periodo
   slice-ato. Tooltip mostra `Fatturato in periodo X → Y (fattura N)`.
3. Prova a draggare/resizare uno di quei booking → toast 409
   `Booking dentro periodo già fatturato [...]`.
4. Prova a marcarlo done/not_done dalla modal → stesso 409.
5. Prova a cancellarlo → 409.
6. Booking dello stesso progetto in periodi NON fatturati restano
   editabili normalmente (per esempio aggiungerne uno in maggio se
   la fattura copre solo aprile → libero).
7. Copilot AI: "sposta il booking #X di +1 giorno" su booking locked
   → card di errore con messaggio leggibile.

**Prossimi step (roadmap riarchitettura billing):**
- α.60: cost report 3 colonne (Fatturato chiuso = Σ slice / Maturato
  post ultimo period_end / Stimato futuro). Convenzione Over/Under
  aggiornata.
- α.61: notifica `EXTRA_AFTER_BILLED` (extra emerso su periodo già
  slice-ato) → destinatari accounting + commerciale del progetto.
- α.62: bottone "Rimanda al commerciale" da /finance con scelta
  esplicita estendi quote esistente (versioning) vs nuova quote linkata.
- (eventuale α.59.x): endpoint di rettifica per sbloccare manualmente
  un periodo, se serve dopo test live.

---

**v3.5.0-alpha.58** — 8 maggio 2026 — JCLBilledSlice (foundation)

Primo step della riarchitettura billing. Modello nuovo `JCLBilledSlice`
che rappresenta la "porzione di una JCL fatturata in un periodo X". Una
JCL può avere N slice nel tempo (progetti pluri-mensili fatturati a
tranche). È foundation only: il binario `JCLBillingStatus` resta in vigore
per back-compat, ma da ora ogni emissione fattura genera anche slice
immutabili che α.59/α.60 useranno per superarlo.

**Chiuso α.58:**
- ✅ Modello `JCLBilledSlice` (`app/models/models.py`): id, tenant_id,
  job_cost_line_id, billing_batch_line_id, invoice_id, period_start,
  period_end, billed_quantity, billed_amount, unit_price_snap,
  created_at. Indici su jcl/period/batch_line/invoice. Export in
  `app/models/__init__.py`.
- ✅ Tabella creata automaticamente da `Base.metadata.create_all()` (no
  ALTER richiesta, è una tabella nuova).
- ✅ Hook in `POST /finance/api/billing/{batch_id}/invoice` (router
  billing.py): per ogni `BillingBatchLine` con `total_approved > 0`
  crea anche slice con periodo del batch e snapshot quantità/importo.
- ✅ Backfill al boot da `BillingBatch` in stato `invoiced` esistenti
  (idempotente, marker `uploads/.billed_slices_backfilled_v1`). Skip
  per slice già presenti.
- ✅ Smoke test boot: 264 routes, version 3.5.0-alpha.58. Lifespan
  esegue il backfill: con 1 batch invoiced nel DB locale → 1 slice creato.

**Cosa NON cambia in α.58 (per scelta):**
- UI: nessun cambio.
- API: nessuna nuova route, response invariate.
- Logica preview/transmit: invariata.
- `JCLBillingStatus` enum: invariato.
- Behaviour edit/cancel batch: invariato.

**Verifica live richiesta a Matteo:**
1. Pull → app boot pulito (264 route, version 3.5.0-alpha.58).
2. Log boot: linea `[lifespan] backfill JCLBilledSlice: N creati, ...`
   se ci sono batch invoiced in DB.
3. Emetti una fattura nuova da `/finance` → batch → "💶 Emetti fattura".
   Verifica con `sqlite3 mediaflow.db "select count(*) from jcl_billed_slices"`
   che il counter è cresciuto del numero di righe approved del batch.
4. Tutto il resto del flusso (cost report, /finance UI, modificare
   batch draft, cancel, ecc.) deve funzionare esattamente come prima.

**Prossimi step (roadmap concordata 8 maggio 2026 — riarchitettura billing):**
- α.59: invariante hard-block (409) su backedit di booking dentro slice
  già fatturato. Per correzioni formali → endpoint dedicato rettifica.
- α.60: cost report 3 colonne (Fatturato chiuso = Σ slice / Maturato
  post ultimo period_end / Stimato futuro). Convenzione Over/Under
  aggiornata.
- α.61: notifica `EXTRA_AFTER_BILLED` (extra emerso su periodo già
  slice-ato) → destinatari accounting + commerciale del progetto.
- α.62: bottone "Rimanda al commerciale" da /finance con scelta esplicita
  estendi quote esistente (versioning) vs nuova quote linkata al progetto.

---

**v3.5.0-alpha.57** — 8 maggio 2026 — Fix periodo trasmissione

Bug periodo modal Trasmetti: dates non riflettevano min/max effettivi del
lavoro svolto. Causa: usavamo `JCL.work_date` (solo max-done per JCL) come
proxy del periodo. Fix isolato che legge direttamente da `Booking`.

**Chiuso α.57:**
- ✅ `app/routers/billing.py`: nuovo helper `_period_from_bookings(db, jcl_ids)`
  che legge `min(start_datetime), max(end_datetime)` direttamente dai Booking
  done non cancellati delle JCL candidate. Fallback mese corrente solo se
  zero booking done.
- ✅ `preview_transmission` e `_transmit_core` usano il nuovo helper.
- ✅ `cost_line_sync` invariato (work_date resta utile per altre viste).
- ✅ Smoke boot version 3.5.0-alpha.57.

**Verifica live richiesta a Matteo:**
1. Cost report → job con booking done che si estendono su più giorni →
   "📤 Trasmetti" → modal mostra `Periodo da` = primo giorno lavorato,
   `Periodo a` = ultimo giorno lavorato (non più la "max date" della JCL
   più precoce). Anteprima con badge "📅 Periodo derivato da booking eseguiti".
2. Caso edge: progetto con sole JCL extra senza booking done → fallback mese
   corrente con badge "⚠ Nessun booking con work_date".

**Prossimi step (roadmap concordata 8 maggio 2026 — riarchitettura billing):**
- α.58: modello `JCLBilledSlice` (o estensione di `BillingBatchLine` come slice).
  Una JCL può essere fatturata "fino al periodo X" e libera dopo. Supera il
  binario `JCLBillingStatus`. Populate retroattivo dai BillingBatch fatturati.
- α.59: invariante **hard-block (409)** su backedit di booking dentro slice
  già fatturato. Per correzioni formali → endpoint dedicato rettifica.
- α.60: cost report **3 colonne** — Fatturato chiuso / Maturato post-periodo
  fatturabile / Stimato futuro. Convenzione Over/Under aggiornata.
- α.61: notifica `EXTRA_AFTER_BILLED` (extra emerso su progetto già fatturato
  in periodo X) → destinatari accounting + commerciale del progetto.
- α.62: bottone **"Rimanda al commerciale"** da /finance con scelta esplicita
  estendi quote esistente (versioning) vs nuova quote linkata al progetto.

---

**v3.5.0-alpha.56** — 8 maggio 2026 — Pulizia non-fatte + visibilità Over in fatturazione

Quattro micro-feature richieste da Matteo che chiudono il loop operativo
"booking eseguiti → cost report → trasmissione → fatturazione".

**Chiuso α.56:**
- ✅ Cost report: bottone "🗑 Scarta tutte" sul pool ore non maturate.
  Endpoint nuovo `POST /cost-report/api/job/{id}/not-done-pool/discard-all`,
  cancella in blocco i booking del pool (status=cancelled). Idempotente.
- ✅ Planning: filtro "Nascondi non fatte" (checkbox sidebar). Helper
  `filterBookingsHideNotDone(bookings)` applicato in 5 viste (timeline,
  agenda, calendar via FullCalendar `events:` function source, todo top-level
  exec_status, storyboard). Persiste in URL come gli altri filtri, chip
  visibile in active-filters bar.
- ✅ Cost report — modal Trasmetti: preview con breakdown esplicito
  Quote / Extra / Sforamento (€). Il toggle "Includi extra" funzionava già
  (verificato), ora ha effetto VISIBILE sul preview (la pillola Extra
  scompare). Endpoint preview ritorna `quote_count/total`, `extra_count/total`,
  `overrun_total`, `total_quoted` per riga.
- ✅ Fatturazione (/finance batch detail): colonne Quotato + Over per riga,
  card aggregate Over + Extra a livello batch, bottone "↪ Rimanda" per
  rimandare una riga al consuntivo finale (rimuove dal batch, JCL torna
  not_billed). Endpoint `POST /finance/api/billing/{batch_id}/lines/{line_id}/defer`,
  manager+ richiesto, draft only, reversibile.
- ✅ Smoke test boot: 264 routes, version 3.5.0-alpha.56. Sintassi
  Python+template OK.

**Verifica live richiesta a Matteo:**
1. /cost-report → job con booking marcati not_done → card "Pozzo ore non
   maturate" → bottone "🗑 Scarta tutte" → conferma → tutto sparisce.
2. /planning → checkbox "Nascondi non fatte" in sidebar → applica → tutte
   le viste (Tabella/Calendario/Agenda/Todo/Storyboard/Timeline) nascondono
   i booking not_done → URL ha `?hide-not-done=1` → Reset filtri lo spegne.
3. /cost-report → un job con quote+extra → "📤 Trasmetti" → preview mostra
   pillole separate (€ quote, € extra, € sforamento) → toglie "Includi
   extra" → pillola Extra sparisce, total_proposed scende.
4. /finance → tab Batch → apri un draft con almeno una riga in over o
   extra → vedere card aggregate "⚠ Over" e "Extra" + colonne Quotato/Over
   per riga → bottone "↪ Rimanda" → conferma → riga sparisce, JCL torna
   "Da fatturare" nel cost report.

**Note semantiche:**
- "Defer" = rimuove dal batch, JCL → not_billed. NON è "loss" (loss = scarto
  definitivo con LossEntry). Reversibile via ri-trasmissione.
- "Over" per riga = max(0, total_proposed − total_quoted) per non-extra. Le
  extra hanno over=0 perché sono "fuori budget" per definizione (categoria
  a sé, mostrata separatamente).
- Auto-cancel batch vuoto NO: dopo defer di tutte le righe il batch resta
  in draft vuoto, il manager decide se annullarlo (audit).

**Prossimi step:**
- Step 5 finale: notifica fine mese auto, "Chiudi progetto", report annuale.

**v3.5.0-alpha.55** — 8 maggio 2026 — Cost report Over/Under doppia vista

Fix bug: `total_expected` non veniva aggiornato dai booking, quindi Over/Under
restava sempre 0. Ora la stima è allineata al pianificato in tempo reale e
il cost report ha due viste selezionabili.

**Chiuso α.55:**
- ✅ `cost_line_sync.recompute_cost_line_actual` calcola `quantity_planned`
  (booking non cancellati, anche non done) e popola `total_expected`. Già
  chiamato in tutti gli hook planning/AI esistenti.
- ✅ API `/cost-report/api/list` e `/api/job/{id}` espongono `over_under_now`
  (= maturato − quotato) e `over_under_forecast` (= stima − quotato), per
  riga + summary. Convenzione: positivo = OVER (sforamento), negativo = UNDER.
- ✅ UI: toggle "Vista: Maturato vs Quotato | Stima vs Quotato" in toolbar
  dettaglio. Default Maturato (base fatturazione). Lista, KPI, righe e
  filtro Over/Under tutti reactive sulla vista.
- ✅ Export PDF/CSV/XLSX: parametro `?vista=now|forecast` propagato fino
  al totale parziale + label esplicita.
- ✅ Backfill al boot per DB esistenti: marker
  `uploads/.total_expected_backfilled_v1` ricalcola tutte le JCL una volta.
- ✅ Smoke test boot: 262 routes, version 3.5.0-alpha.55.

**Verifica live richiesta a Matteo:**
1. Pull → al primo boot log `backfill JCL.total_expected: N/M righe`.
2. /cost-report → apri un job con booking pianificati non done → Stimato
   a finire = pianificato × prezzo, Maturato = 0.
3. Vista Maturato → Over/Under = 0 (no extracosto certo finché niente done).
4. Vista Stima → se planned ≠ quoted → Over/Under = delta. Segno positivo
   sforamento (rosso), negativo sotto budget (verde).
5. Marca booking done → Maturato cresce → vista Maturato mostra over/under
   reale.
6. Export PDF in vista Maturato vs Stima → totale Over/Under coerente con
   la scelta.

**Limitazioni / decisioni semantiche:**
- Pianificato include TUTTI i booking non cancellati (anche tentative).
  Decisione esplicita di Matteo: "tutti i booking non cancellati".
- La stima default a `quantity_quoted` se nessun booking. Quando arriva
  il primo booking passa a `qty_planned`, può andare sotto o sopra il
  quotato (genera under o over rispettivamente).
- Convenzione segno invertita rispetto a pre-α.55. Vecchio campo
  `over_under` lasciato come alias di `over_under_forecast` per
  back-compat.

**Prossimi step:**
- Step 5 finale: notifica fine mese auto, "Chiudi progetto", report annuale.

**v3.5.0-alpha.54** — 8 maggio 2026 — Capability copilot avanzate + Financial Copilot

Step 4 chiuso. Sei nuove capability per il copilot: 4 sulla pianificazione
(analisi conflitti, ricerca slot liberi, ricorrenti, bulk move) + 2 sul
finance (stato finanziario progetto readonly, trasmissione a fatturazione).
L'AI ora può rispondere a "qual è il margine del progetto X?" e operare
in batch su booking/billing.

**Chiuso α.54:**
- ✅ `analyze_conflicts` (readonly) — overlap nei booking + suggerimenti
- ✅ `find_free_slots` (readonly) — slot liberi per risorsa o reparto
- ✅ `propose_recurring_bookings` (mutation) — serie ricorrenti DAILY/
  WEEKDAYS/WEEKENDS/CSV con conflict-skip non bloccante
- ✅ `propose_bulk_move` (mutation) — shift atomico N booking, JCL-locked
  rispettato, recompute cost per ognuno
- ✅ `query_project_finance` (readonly) — quotato/maturato/atteso/spese/
  margine/billing breakdown/invoices/top job per scostamento
- ✅ `propose_transmit_to_billing` (mutation) — trasmette maturato come
  BillingBatch draft, periodo auto-derivato. Refactor `_transmit_core`
  estratto da endpoint HTTP per riuso AI
- ✅ System prompt: 2 nuove sezioni (Pianificazione avanzata + Fatturazione)
  + regola JCL-locked
- ✅ `copilot.js`: 6 label + 6 case + 6 summary renderer
- ✅ Cache-buster `copilot.js?v=3.5.0-alpha.54`
- ✅ Smoke test boot: 262 routes, 23 tools / 23 handlers

**Verifica live richiesta a Matteo:**
1. Pull → app parte (262 route, version 3.5.0-alpha.54).
2. Apri copilot drawer → "Mostrami i conflitti della prossima settimana"
   → AI usa `analyze_conflicts`.
3. "Quando il colorist senior ha 4h libere questa settimana?" →
   `find_free_slots`.
4. "Prenota Luca lun-ven 9-13 dall'11 al 22 maggio sul job #5" →
   `propose_recurring_bookings` → Apply → 10 booking creati.
5. "Sposta i booking #100, #101, #102 di +2 ore" → `propose_bulk_move`
   → atomic.
6. "Qual è il margine del progetto Ligas?" → `query_project_finance`
   → AI sintetizza dal payload.
7. "Trasmetti a fatturazione il progetto Ligas" →
   `propose_transmit_to_billing` → batch draft visibile in /finance.

**Limitazioni note α.54:**
- `find_free_slots` non considera ResourceUnavailability (ferie/festività),
  solo booking esistenti. Da raffinare se richiesto.
- `propose_recurring_bookings` non supporta overnight.
- `query_project_finance` non filtra Invoice per tenant_id (Invoice non
  ha tenant_id; scoped indirettamente via job_id IN job_ids del progetto).

**Prossimi step:**
- Step 5: Cost Report flow finale (notifica fine mese auto, "Chiudi
  progetto", report annuale)
- Riempire ResourceUnavailability check in `find_free_slots` se Matteo
  lo chiede dopo il test live

**v3.5.0-alpha.53** — 8 maggio 2026 — Vision integration immagini copilot

Step 3 chiuso. Le immagini caricate nel copilot ora sono "viste"
direttamente dall'AI invece di restare placeholder testuali.

**Chiuso α.53:**
- ✅ `AIProvider.supports_vision()` astratto + override Claude (sempre True)
  e OpenAI (True su 4o/o1/vision/turbo)
- ✅ `build_user_content_blocks(text, attachments, supports_vision)` →
  ritorna stringa (backcompat) o content list canonico Anthropic
- ✅ Image blocks base64 con limite 5MB (Anthropic), fallback testuale
  per immagini corrotte/grandi/mancanti
- ✅ `_translate_blocks_to_openai` traduce Anthropic ↔ OpenAI
  (`image` → `image_url` con data URL)
- ✅ `OpenAIProvider.chat` traduce trasparentemente
- ✅ `/ai/api/chat` costruisce `last_user_content` consapevole del
  provider; helper `_flatten_content` per persistenza/title
- ✅ Smoke test boot OK + 4 scenari content + translation OK

**Verifica live richiesta a Matteo:**
1. Pull → app parte (262 route, version 3.5.0-alpha.53)
2. /settings → tab AI → verifica provider attivo (Claude o GPT-4o)
3. Apri copilot drawer → trascina screenshot capitolato cliente
4. Scrivi "Cosa specifica questo capitolato per il video master?"
5. AI risponde citando contenuti effettivamente visibili nell'immagine
   (numeri, label tabelle, scritte)
6. Test fallback: switch a Ollama/Perplexity → stessa immagine →
   placeholder testuale (chat continua a funzionare)

**v3.5.0-alpha.52** — 8 maggio 2026 — Fattura PDF formale + dati fiscali

Step 2 chiuso. Fattura italiana stampabile con cedente/cessionario, IVA per
riga, riepilogo IVA per aliquota, IBAN, bollo opt, snapshot fiscali
immutabili. Tab `/settings/Azienda` per gestire dati cedente + logo.

**Chiuso α.52:**
- ✅ Modello esteso: Tenant +9 campi fiscali, Client +zip/province,
  Invoice +4 doc + 10 snap cliente + 11 snap tenant, InvoiceLine +vat/disc
- ✅ Auto-migrate al boot per le 4 tabelle (idempotente)
- ✅ `app/services/invoice_pdf.py` — layout fattura italiana completo con
  logo, REA, capitale, regime fiscale, IVA per aliquota, bollo virtuale,
  pagamento, footer custom
- ✅ `emit_invoice` popola snapshot al momento dell'emissione → fatture
  storiche immuni a modifiche future di tenant/cliente
- ✅ Endpoint `GET /finance/api/billing/{id}/invoice-pdf`
- ✅ UI modal batch: bottone 📥 Stampa fattura PDF (visibile su `invoiced`)
- ✅ /settings tab **Azienda** (form completo + upload logo, admin-only)
- ✅ Endpoint settings: `GET/PUT /api/company`, `POST /api/company/logo`

**Verifica live richiesta a Matteo:**
1. Pull → app parte (262 route, version 3.5.0-alpha.52)
2. /settings → tab Azienda → compila P.IVA, sede, REA, IBAN, regime → Salva
3. Carica logo PNG/JPG max 1MB → vedi anteprima
4. Crea batch fatturazione (Cost Report → Trasmetti)
5. /finance → approva batch → emetti fattura (numero manuale tipo "2026/001")
6. Modal batch → bottone 📥 Stampa fattura PDF → si apre PDF in nuova tab
7. Verifica nel PDF: cedente con logo + dati fiscali, cessionario con P.IVA,
   tabella righe con IVA per riga, riepilogo IVA, totali, IBAN, footer

**Limitazioni note MVP:**
- Niente XML SDI per invio elettronico (è PDF stampabile, non FE/SdI)
- IVA per riga uniforme nell'emissione (configurabile UI futura)
- Bollo virtuale opt-in (default off; va attivato manualmente per esenti)
- 1 logo per tenant (no varianti chiaro/scuro)

**Prossimi step:**
- α.53: Vision immagini copilot (Anthropic + OpenAI image blocks)
- Capability copilot avanzate (recurring/bulk/conflicts/free-slots)
- Financial Copilot (Q&A + reporting + export status finanziario)
- Step 5: notifica fine mese auto, "Chiudi progetto", report annuale

**v3.5.0-alpha.51.1** — 8 maggio 2026 — Fix audit α.41→α.51 (3 critici + 4 minori)

Audit logico completo ha rivelato 3 bug critici e 4 alti sulla maratona
α.41→α.51, fissati prima di passare alle feature nuove.

**Chiuso α.51.1:**
- ✅ **C3 sicurezza /uploads**: rimosso `/uploads/` da `PUBLIC_PATHS`. Pre-fix
  tutti gli asset DAM e i capitolati copilot erano scaricabili senza auth.
- ✅ **C1 JCL.work_date populate**: `cost_line_sync.recompute_cost_line_actual`
  ora popola `work_date = max(start_datetime.date())` dei booking done.
  Backfill one-shot al boot via marker `uploads/.work_date_backfilled_v1`.
  Sblocca l'auto-derivazione periodo in `billing.preview_transmission`.
- ✅ **C2 AI resize/move recompute**: `_h_propose_resize_booking` e
  `_h_propose_move_booking` ora chiamano `recompute_for_booking`, allineato
  a `_h_propose_delete_booking`.
- ✅ **A2 JCL locked**: nuovo `_assert_jcl_not_locked` blocca AI su booking
  con JCL in stato `in_batch|billed|paid` (corromperebbe snapshot batch).
- ✅ **A4 BookingChange audit AI**: log in `booking_changes` per le 3
  capability AI (kind=`ai_move|ai_resize|ai_delete`).
- ✅ **A1 tenant_id**: filtro su `_resolve_booking_for_planning` e
  `set_jcl_billing_status` (via JOIN job→project).
- ✅ **A3 Invoice.number scoped**: check unicità via JOIN client per tenant.
- ✅ **M1 cancel_batch rilascia anche `lost`**: oltre a `in_batch`.
- ✅ **M5 cache-buster `global.js`**: bump α.43 → α.51.1 in `base.html`.

**Aperti (refactor non bloccante):**
- B1 OneDrive `st_mtime` su Mac (cleanup_old_attachments)
- B2 system prompt esplicitare "spostare booking done = retroattivo"
- M2/M3/M4 workflow tweaks

**Verifica smoke:**
- App boot pulita: version `3.5.0-alpha.51.1`, 258 route
- Backfill `work_date` runs al primo boot, marker per idempotenza

**v3.5.0-alpha.51** — 7 maggio 2026 — Upload documenti per copilot (PDF/DOCX/TXT/MD/immagini)

Richiesta serale Matteo. MVP solido: upload via clip 📎 o drag&drop nel
drawer copilot, estrazione testo PDF/DOCX/TXT/MD inline nel messaggio AI,
immagini salvate con placeholder testuale (vision integration in α.52).

**Chiuso α.51:**
- ✅ Servizio `app/services/copilot_attachments.py`: save/extract/embed/cleanup
- ✅ Endpoint `POST /ai/api/upload` (multipart, max 20MB, ammette
  pdf/docx/txt/md/jpg/jpeg/png/webp/gif)
- ✅ Storage `uploads/copilot/{uuid}.{ext}` + mount `/uploads` pubblico
- ✅ Cleanup auto > 7gg in lifespan startup
- ✅ Endpoint `/ai/api/chat` integra `attachments[]` via embed inline
  nell'ultimo messaggio user
- ✅ UI: bottone clip in input bar, drag&drop overlay tutto il drawer,
  lista allegati con badge tipo/size/× rimuovi
- ✅ Stati ⏳ uploading + ⚠ errore con border rosso
- ✅ PDF estratto via pypdf, DOCX via python-docx, TXT/MD raw
- ✅ Immagini: dimensioni Pillow + placeholder testuale per AI
- ✅ Cache-buster copilot.js?v=3.5.0-alpha.51

**Verifica live richiesta a Matteo:**
- Apri copilot da qualsiasi pagina
- Click 📎 → seleziona PDF (es. capitolato cliente)
- Card appare con nome + caratteri estratti + size + ×
- Scrivi prompt tipo "Leggi questo capitolato e proponi una quote"
- Send → AI riceve testo PDF inline + risponde proponendo azioni
- Test drag&drop: trascina file nel drawer → overlay "Rilascia qui" → upload
- Test rimozione × prima del send
- Test errore: trascina file > 20MB → toast errore

**Limitazioni note MVP**:
- Immagini: caricate + visibili in card ma AI riceve solo placeholder
  testuale (vision blocks per Claude/OpenAI/Gemini in α.52)
- Niente persistenza DB: dopo refresh allegati spariscono dal client
  (file su disk fino al cleanup 7gg)
- Niente OCR per screenshot con testo

**Prossimi step:**
- α.52: vision integration per immagini (Anthropic Messages API supporta
  image blocks → modifica build_messages per provider che hanno vision)
- Domani: fattura formale PDF + anagrafica cliente + dati aziendali tenant
  (rimandato da stasera per stanchezza)
- Capability copilot avanzate: recurring_bookings, bulk_move,
  analyze_conflicts, find_free_slots
- Notifiche proattive sul FAB

**v3.5.0-alpha.50** — 7 maggio 2026 — Copilot in-depth integration nella pianificazione

Pre-α.50 il copilot vedeva clienti/progetti/listino/quote ma NIENTE
pianificazione viva → poteva creare booking ma "alla cieca". Ora ha
context completo + 3 capability per operare su booking esistenti +
quick prompts contestuali per pagina.

**Chiuso α.50:**
- ✅ Sezione PIANIFICAZIONE VIVA in `build_context` (booking 14gg,
  conflitti, carico per risorsa, indisponibilità, job critici), filtra
  per project_id/job_id se presenti
- ✅ 3 capability nuove: `propose_move_booking` (shift/new_date/
  new_resource/remap), `propose_resize_booking` (delta minuti),
  `propose_delete_booking` (soft-delete con reason). Tutti con
  conflict-check pre-apply, atomic
- ✅ Tool spec in `ai_tools.py` per provider tool_use nativo + handler
  in `ai_assistant.py`
- ✅ System prompt rinforzato con sezione "PIANIFICAZIONE — operazioni
  sulla timeline" (7 regole: consulta context, rispetta indisponibilità,
  carico bilanciato, segnala conflitti, spiega perché, ricorrenti uno
  alla volta, link a job_cost_line)
- ✅ Quick prompts contestuali nel drawer per pagina (/planning ha 7
  prompt dedicati: Diagnostica + Pianificazione)
- ✅ Renderer human-readable per le 3 nuove card in copilot.js
- ✅ Cache-buster copilot.js?v=3.5.0-alpha.50

**Verifica live richiesta a Matteo:**
- Pull → app parte
- /planning → click FAB copilot → vedi quick prompts dedicati
  ("Mostrami i conflitti", "Sposta booking", ecc.)
- "Mostrami i conflitti orari della prossima settimana" → AI risponde
  consultando il context PIANIFICAZIONE VIVA
- "Sposta il booking #42 di +1 giorno" → AI propone
  `propose_move_booking` → card conferma → Apply → booking spostato
- "Allunga il booking #42 di 2 ore" → propose_resize → conferma → apply
- "Cancella il booking #42" → propose_delete → conferma → soft-delete
  (recuperabile dal Cestino)

**Prossimi step (futuri):**
- Capability avanzate: recurring_bookings, bulk_move, analyze_conflicts,
  find_free_slots
- Notifiche proattive sul FAB se rilevati problemi
- Capability per Billing: propose_transmit_to_billing
- Domani: fattura formale PDF con dati cliente (P.IVA) + dati aziendali
  proprietario (configurazione tenant settings)

**Bug ancora aperti:**
- Freeze Chrome Mac specifico (workaround light mode in toolbar)

**v3.5.0-alpha.49** — 7 maggio 2026 — Step 4 Cost Report → Billing flow: UI /finance batch

Step 4 chiuso. Pagina `/finance` ora ha tab dedicata "📦 Batch fatturazione"
con lista filtrata, drawer dettaglio editabile, bottoni azione complete
(approve/cancel/emit invoice), anteprima IVA live, sezione perso aggregato
per progetto.

**Chiuso α.49:**
- ✅ Tab `📦 Batch fatturazione` in /finance con badge giallo count draft
- ✅ Tabella batch: code, project, status, periodo, proposto/approvato/perso, fattura
- ✅ Filtro status (draft/approved/invoiced/cancelled)
- ✅ Auto-open via deep-link `/finance#batch-{id}` (link da cost report)
- ✅ Modal dettaglio batch (920px): meta-grid + lines table + footer dinamico
- ✅ Edit line inline (solo draft + manager+): input importo + prompt
  loss_reason se ridotto < proposed → PATCH endpoint α.47 + toast delta
- ✅ Bottone ✅ Approva (draft → approved)
- ✅ Bottone 💶 Emetti fattura (modal con number/date/VAT live + POST emit)
- ✅ Bottone ↩ Annulla batch (rosso, con conferma)
- ✅ Pannello "Perso aggregato" con totale + breakdown by_reason
- ✅ Auto-load batch al boot (per badge tab anche se utente è su altra tab)

**Verifica richiesta a Matteo:**
- Pull → app parte
- /finance → click tab "📦 Batch fatturazione"
- Vedi lista batch (se hai trasmesso da cost report)
- Click su batch draft → modal dettaglio con lines editabili
- Modifica importo (es. 100 → 80) → prompt motivo → vedi 20 perso + totale aggiornato
- ✅ Approva → batch approved
- 💶 Emetti fattura → numero+data → Invoice creata + visibile in tab Fatture
- Test deep-link: /cost-report → click su una card batch → /finance si apre
  con modal dettaglio aperto direttamente

**Bug ancora aperti:**
- Freeze Chrome Mac specifico (non bug MediaFlow, workaround light mode)

**Prossimi step:**
- α.50: notifica fine mese auto + chiusura progetto (producer "Chiudi
  lavorazioni") + report finanziario completo

**v3.5.0-alpha.48.2** — 7 maggio 2026 — Periodo trasmissione auto-derivato dai booking

Richiesta Matteo. GET /finance/api/billing/preview calcola period_start/end
da min/max work_date JCL candidate (popolate da cost_line_sync su booking
done). Modal Trasmetti popola defaults dal preview, mostra anteprima
righe+totale, label sorgente periodo (📅 from_bookings vs ⚠ fallback).
Submit disabled se zero candidate.

**v3.5.0-alpha.48.1** — 7 maggio 2026 — Bottone Ritira su card batch (cancel pre-invoice)

Bottone ↩ Ritira (rosso) sulla card batch nel widget cost report.
Visibile solo se status in {draft, approved}. Confirm + cancel endpoint
α.47 → JCL rilasciate, LossEntry cancellate, batch → cancelled.

**v3.5.0-alpha.48** — 7 maggio 2026 — Step 3 Cost Report → Billing flow: UI Cost Report

Step 3 del workflow billing. UI Cost Report ora mostra stato fatturazione
per riga + widget Fatturazione (sommario + batch elenco) + modal Trasmetti.
Endpoint API α.47 collegati al frontend.

**Chiuso α.48:**
- ✅ API `cost_report.py` estesa: `cost_lines[]` con billing_status/
  billing_batch_id/billed_amount/is_extra; `job` con project_id;
  `billing_batches[]` + `billing_summary` aggregati per stato
- ✅ Helper backend `_billing_batches_for_job` + `_billing_summary_for_job`
- ✅ Template colonna `Fatt.` con badge colorato per stato (5 colori)
- ✅ Marcatore `[extra]` arancio sulle righe is_extra
- ✅ Widget Fatturazione header: 5 card sommario + elenco batch
  cliccabili (link `/finance#batch-{id}`)
- ✅ Bottone `📤 Trasmetti a fatturazione` + modal con periodo/extras/note
- ✅ Submit chiama `POST /finance/api/billing` (α.47), refresh report
  per vedere nuovi stati

**Verifica live richiesta a Matteo:**
- Pull → app parte normale
- Apri `/cost-report` → seleziona un job con maturato (booking done +
  total_accrued > 0)
- Vedi nuova colonna `Fatt.` nella tabella cost lines (default tutti
  grigio "Da fatturare")
- Vedi widget Fatturazione sopra la tabella con 5 card sommario
- Click bottone `📤 Trasmetti a fatturazione` → modal apre
- Default periodo = mese corrente. Submit → batch creato (toast)
- Refresh: righe diventano ambra "In approv." + card batch appare
  nel widget
- Click sulla card batch → apre `/finance` in nuova scheda (UI batch
  arriva in α.49)

**Bug ancora aperti:**
- Freeze Chrome Mac specifico (workaround light mode disponibile)
- Step 4-5 cost report flow (UI /finance, notifiche, chiusura progetto)

**Prossimi step:**
- α.49: UI `/finance` con elenco batch + edit manager + voce perso
- α.50: notifica fine mese + chiusura progetto + report finanziario

**v3.5.0-alpha.47.1** — 7 maggio 2026 — HOTFIX Bulk button non attivava dopo ROI/Esc

Matteo: "Bulk non funziona quando bookings multiselected. Dovrebbe attivarsi?"

**Diagnosi**: vis-timeline 7.x emette `select` event SOLO per click utente,
non per `setSelection()` programmatico. Il ROI/area (tasto S + drag) usa
setSelection da codice → no event → `tlOnSelectionChange` mai chiamato →
button Bulk disabled anche con selezione popolata.

**Chiuso α.47.1:**
- ✅ Helper `_tlSetSel(ids)` che wraps setSelection + tlOnSelectionChange
  + sync cache `window._tlPrevSelection` per sticky α.42
- ✅ Sostituite 2 chiamate "nude" con il wrapper:
  ROI/area in `tlRoi*` + Esc clear in keyboard handler
- ✅ Le 4 select-by-* avevano già tlOnSelectionChange manuale → no toccate

**Verifica live richiesta a Matteo:**
- `/planning` → tasto S → drag area su 2-3 booking → bottone Bulk in
  toolbar deve diventare attivo (indigo + counter "(N)")
- Click Bulk → modal apre normalmente
- Esc per pulire → bottone torna disabled

**v3.5.0-alpha.47** — 7 maggio 2026 — Step 2 Cost Report → Billing flow: API endpoints

Step 2 del workflow billing concordato con Matteo. **9 endpoint API**
backend pronti, ancora niente UI (arriva in α.48-49).

Quick fix UI incluso: bottone `⛶ Finestra` in toolbar timeline ora
nascosto in `/planning/full` (era illogico).

**Endpoint creati** (`app/routers/billing.py`, prefix `/finance/api/billing`):
1. `POST /` transmit JCL maturate → BillingBatch (draft)
2. `GET /` lista con filtri
3. `GET /{id}` dettaglio + lines snapshot
4. `PATCH /{id}/lines/{lid}` manager edit importo (auto LossEntry)
5. `POST /{id}/approve` manager approva
6. `POST /{id}/invoice` emette Invoice + linka, JCL→billed
7. `POST /{id}/cancel` annulla batch (rilascia JCL→not_billed)
8. `PATCH /jcl/{id}/billing-status` override manuale stato
9. `GET /loss/project/{id}` sommario perso (rendicontazione)

**Logica chiave:**
- Auto-numero `BB-{anno}-{NNN}` (no riciclo cancelled)
- Snapshot immutabile (BatchLine cattura proposed al transmit)
- Loss tracking: edit manager < proposed → LossEntry
- Cap di sicurezza: approved ≤ proposed × 1.5
- JCL state machine: not_billed→in_batch→billed→paid (loss in caso di approved=0)
- Numero fattura MANUALE (no interferenza con gestionale fiscale esterno)
- VAT default 22% configurabile per chiamata
- RBAC: view_finance per read+transmit, manager+ per modifica/approve/invoice/cancel

**Verifica richiesta a Matteo:**
- Pull → app parte senza crash (auto-migrate α.46 + nuove tabelle già OK)
- Apri `http://localhost:8000/docs` → sezione `billing` → vedi 9 endpoint
- Flusso completo via /docs (oppure curl):
  1. POST `/finance/api/billing` con project_id, period_start, period_end
  2. GET `/finance/api/billing/{batch_id}` → vedi snapshot
  3. PATCH `/lines/{lid}` con total_approved ridotto → LossEntry generata
  4. POST `/{id}/approve` → status approved
  5. POST `/{id}/invoice` con number+date → Invoice creata + JCL=billed
  6. GET `/loss/project/{pid}` → totale perso
- Test bottone Finestra: apri `/planning/full` → toolbar non deve avere `⛶ Finestra`

**Bug ancora aperti:**
- Freeze Chrome Mac specifico (non bug MediaFlow, conferma da test PC OK)
- Light mode α.46.2 resta come safety net

**Prossimi step:**
- α.48: UI Cost Report con stati billing colorati + bottone "Trasmetti"
- α.49: UI `/finance` con batch list + edit manager + perso
- α.50: notifica fine mese auto + chiusura progetto + report finanziario

**v3.5.0-alpha.46.2** — 7 maggio 2026 — Modalità leggera timeline (vera causa freeze)

α.46.1 ipotizzava Bitwarden come causa principale del freeze Chrome.
Test Matteo in **incognito** (no estensioni) → freeze persiste.
Diagnosi sbagliata. Riapertura analisi trace.

**Vera causa:** vis-timeline con `stack: true` ricalcola overlap di
TUTTI gli items per evitarne la sovrapposizione. Algoritmo O(N²).
Con 30+ booking + 600+ background items (ferie/festa/weekend/punch
moltiplicati × 20 risorse) + zoom mese, ogni `requestAnimationFrame`
blocca 200+ms.

Numeri trace conferma:
- Top RunTask: 480ms, 416ms, 414ms, 396ms, 342ms, 337ms, 304ms (~3s
  congelati nei 7 task più lunghi)
- PageAnimator (single rAF): 225ms picco
- Layout: 92ms picco
- 18,761 Paint events

**Chiuso α.46.2:**
- ✅ Bottone `🪶 Light` in toolbar timeline (persistenza
  `localStorage.mf_tl_light_mode`)
- ✅ Light ON disabilita: `stack: false` + `stackSubgroups: false` +
  background items (ferie/festa/punch) + animazioni/transition CSS
  su `.vis-item`
- ✅ Toast informativo on toggle
- ✅ CSS `#tl-host[data-light="on"]` disabilita filter:hover, animation,
  transition (riducono i 18k Paint events)

**Verifica richiesta a Matteo:**
- Chrome (anche normale, non solo incognito) → `/planning` → click
  bottone `🪶 Light` in toolbar → diventa indigo evidenziato
- Zoom mese 30+ booking → deve scorrere fluido
- Trade-off: items sovrapposti visivamente (no impilamento). Per
  leggibilità precisa, zoom giorno/settimana o disattiva light mode

**Bug ancora possibili:**
- Se anche light mode freeza → vis-timeline 7.7.3 ha bug native pure
  senza stack. Soluzione finale: sostituzione libreria (Bryntum/DHTMLX),
  backlog Round 12

**v3.5.0-alpha.46.1** — 7 maggio 2026 — Mitigazione freeze Chrome (estensioni autofill)

Performance trace Chrome di Matteo ha identificato il colpevole: NON è
vis-timeline da solo (2.4s su 65s totali), ma Bitwarden + altre estensioni
autofill che osservano il DOM e scansionano migliaia di nodi creati da
vis-timeline durante zoom mese.

**Numeri dal trace `Trace-20260507T171123.json.gz`:**
- 24,124 chiamate a Bitwarden script (838ms)
- 41 callback `CollectAutofillContentService.handleMutationObserverMutation`
- 55 `setupOverlayOnField` schedule via setTimeout
- vs. solo 22ms global.js MediaFlow

**Chiuso α.46.1:**
- ✅ `data-bwignore` + `data-lpignore` + `data-1p-ignore` + `autocomplete="off"`
  su `#tl-host` e form modal booking → estensioni well-behaved skippano scan
- ✅ FAQ manuale aggiornata con workaround Chrome (incognito test, exclude
  localhost Bitwarden, Firefox, pagina standalone, heatmap off)

**Test richiesto a Matteo:**
- **Cmd+Shift+N** (incognito Chrome) → `localhost:8000/planning` → zoom
  mese 30+ booking. Se in incognito funziona fluido = causa CONFERMATA
  estensioni. Soluzione: Bitwarden Settings → Excluded Domains → aggiungi
  `localhost`. Allora anche Chrome normale funzionerà
- Verifica anche pull dei nuovi attributi `data-bwignore`: rebooting
  app + hard refresh

**Bug ancora aperti:**
- ⚠ Vis-timeline 7.7.3 da solo è pesante (2.4s su 65s del trace) ma non
  causa il freeze. Sostituzione libreria (Bryntum/DHTMLX) resta nel backlog
  ma NON è urgente con la mitigazione attuale
- ⚠ Cost Report flow: implementato solo Step 1 (modello dati α.46),
  prossimi step α.47-50 (API + UI)

**v3.5.0-alpha.46** — 7 maggio 2026 — Step 1 Cost Report → Billing flow: modello dati

Primo step del workflow Cost Report ↔ Fatturazione concordato con Matteo.
**Solo modello dati + migrazione**, niente API/UI nuove (arrivano in α.47-50).

**Workflow target (NON ancora attivo):**
1. Cost Report → "Trasmetti a fatturazione" (manuale + notifica fine mese)
2. BillingBatch creato (snapshot JCL maturate del periodo)
3. Manager in /finance rivede + può modificare importi (delta → LossEntry)
4. Approva → emette fattura → JCL.billing_status=billed
5. Pagata → JCL=paid
6. A chiusura progetto: producer click "Chiudi" → fattura finale + perso
   aggregato per rendicontazione finanziaria

**Chiuso α.46:**
- ✅ Enum: JCLBillingStatus, BillingBatchStatus, LossReason
- ✅ JobCostLine esteso: billing_status, billing_batch_id, billed_amount
- ✅ BillingBatch (code BB-{anno}-{NNN}, project_id, period, totali,
  audit transmit/approve, invoice_id)
- ✅ BillingBatchLine (snapshot immutabile JCL al transmit)
- ✅ LossEntry (importo, reason, project_id, audit user)
- ✅ Auto-migrate al boot in main.py per le 3 colonne JCL
- ✅ Script esplicito scripts/migrate_billing_flow.py
- ✅ Models __init__.py exporta i nuovi nomi

**Verifica Matteo dopo pull:**
- App parte senza crash (auto-migrate dovrebbe gestire ALTER TABLE)
- Se preferisce esplicito: `python scripts/migrate_billing_flow.py`
- Niente da testare in UI: tutto invariato dal punto di vista utente
- Cost report mostra ancora le stesse info di α.45 (i nuovi campi
  esistono ma non sono ancora esposti)

**Prossimi step concordati:**
- α.47: API trasmissione/approvazione/emissione fattura da batch
- α.48: UI Cost Report con stati colorati + bottone "Trasmetti"
- α.49: UI /finance con batch + modifica manager + perso
- α.50: notifica fine mese + chiusura progetto + report finanziario

**Bug ancora aperti:**
- ⚠ Freeze Chrome con 30+ booking + zoom mese (Firefox OK). Matteo sta
  facendo test debug. Workaround "modalità leggera" pronto da implementare

**v3.5.0-alpha.45** — 7 maggio 2026 — Bulk visibile + "Fatto" in fondo

Quick fix utenza dopo test α.44.1:

**Chiuso α.45:**
- ✅ Bottone "✏ Bulk" toolbar timeline sempre visibile (era display:none
  → Matteo "sparito"). Disabled+grigio se no selezione, attivo+indigo
  con counter (N) quando ha item selezionati
- ✅ Sort "Le mie" + "Per progetto": booking con execution_status terminale
  (done/not_done) vanno SEMPRE in fondo, prima i task ancora attivi.
  Modifica in `_cmpByPrioThenDate`

**Bug ancora aperti:**
- ⚠ **Freeze Chrome con 30+ booking + zoom mese PERSISTE** anche dopo
  α.44.1. NON era né heatmap né resize loop la causa primaria. Ipotesi
  residue:
  - vis-timeline 7.7.3 `stack:true` con O(N²) overlap detection
    esplode con N>30 + items larghi (zoom mese)
  - background items (ferie/festa/punch) raddoppiano il count
  - Bug Chrome rendering vis-timeline specifico
  Serve **Performance profile DevTools** da Matteo per puntare il
  problema. Possibile workaround: modalità "leggera" che disabilita
  stack/animazioni/background
- ⚠ Warning CSP "blocks eval" Chrome — collegato? Probabilmente no
  ma da indagare insieme

**v3.5.0-alpha.44.1** — 7 maggio 2026 — HOTFIX freeze Chrome 30+ booking

Test α.44 su Chrome/Mac con 30+ booking + 20+ risorse: timeline sfarfalla
da 2 settimane in su, sparisce griglia giorni a zoom mese, Chrome si
blocca. Firefox/Mac stesso scenario funziona.

**Diagnosi:** rangechanged callback ricostruiva via `tlBuildGroups()` +
`groupsDS.update()` TUTTI i groups foglia ad ogni evento. Dopo fix α.41
(heatmap cells come HTMLElement), 20 risorse × 30 giorni zoom mese =
**600+ DOM nodes ricreati ad ogni rangechanged**. Vis-timeline emette
rangechanged anche per piccoli movimenti pan → cascade DOM thrash →
main thread bloccato Chrome.

**Chiuso α.44.1:**
- ✅ Skip rangechanged update se `prefs.heatmap=false` (default α.44):
  nessun contenuto dinamico nei groups → niente rebuild necessario
- ✅ Dedup range signature `window._tlLastRangeSig` (skip se
  start+end identici al precedente)
- ✅ Throttle bumped 150→500ms su `_tlHeatTimer`
- ✅ Batch update: `groupsDS.update(arr)` invece di N call separate
- ✅ Anti-loop `_tlBindResize`: skip se delta height < 8px,
  throttle 250ms, tracking `window._tlLastHeight`
- ✅ `_doRenderTimeline` resetta `_tlLastRangeSig` + clearTimeout
  `_tlHeatTimer` per nuova istanza

**Verifica live richiesta a Matteo:**
- `/planning` su Chrome con 30+ booking. Zoom: settimana → mese.
  Non deve più sfarfallare né bloccare la pagina
- Ridimensiona finestra browser → no loop di resize
- Se attivi heatmap (📊 toolbar) e poi zoom mese: con questi fix il
  rebuild è throttled ma comunque presente. Su monitor lento può
  ancora pesare. Soluzione futura se persiste: rendere heatmap
  generata con CSS (background-image gradient) invece di N div

**Bug ancora aperti:**
- ⚠ Warning CSP "blocks eval" in Chrome — probabilmente vis-timeline
  7.7.3 usa `new Function()` interno. Non sembra causa del freeze (era
  ovunque, non solo > 30 booking). Da rivisitare se freeze persiste
- ⚠ Timeline nera in Chrome — separato. In attesa info DevTools

**Niente migrate, solo template planning.html + bump main.py.**

## v3.5.0-alpha.44 — Heatmap toggle + altezza dinamica + finestra standalone (7 maggio 2026)

Test live α.43 ha riportato 4 issue + 1 da indagare. Risolti: heatmap
"quadratini verdi" (era una feature pre-esistente che ora si vede grazie
al fix font α.41 — default cambiato a OFF), altezza fissa 600px che
sprecava monitor grandi e schiacciava 20+ risorse (ora dinamica viewport),
richiesta scorporo timeline in finestra dedicata (`/planning/full` standalone).

**Chiuso α.44:**
- ✅ Heatmap default OFF (`TL_PREFS_DEFAULTS.heatmap=false`) +
  bottone toolbar `📊 Heatmap` con sync popover ⚙
- ✅ Altezza timeline dinamica: `tlComputeHeight(host)` da viewport
  (`window.innerHeight - host.top - 24`, min 400px). Listener `resize`
  con debounce 150ms → `setOptions({height})` senza re-render
- ✅ Pagina `/planning/full`: nuovo route che render `planning.html`
  con `full_screen=True`. `base.html` condizionali skip sidebar+topbar.
  CSS `body.no-chrome`. Refactor helper `_planning_render` per
  condividere la logica con `/planning`. Bottone `⛶ Finestra` in toolbar
  che fa `window.open` con popup features (fallback tab)
- ✅ Cache-buster CSS bumpato a `?v=3.5.0-alpha.44`

**Verifica live richiesta a Matteo:**
- `/planning` → tab Timeline. Cella heatmap NON deve apparire più sotto
  i nomi (default OFF). Bottone `📊 Heatmap` in toolbar → click attiva,
  click di nuovo disattiva. Stato persiste in localStorage
- Ridimensiona finestra browser → la timeline si ridimensiona di
  altezza automaticamente (era fissa a 600px)
- Su monitor grande (es. 27" 4K) la timeline occupa tutto lo spazio
  utile, non solo 600px iniziali
- Bottone `⛶ Finestra` → si apre popup/tab a `/planning/full` senza
  sidebar e senza topbar. Solo card timeline + filtri sidebar interna
  (la `.pl-sidebar` di pagina)
- Sulla pagina /planning/full la stessa funzionalità (drag, multi-move,
  Ctrl+Z, Ctrl+B per sidebar — quest'ultimo nullo perché non c'è
  sidebar globale)

**Bug ancora aperto:**
- Timeline nera in Chrome (solo Chrome, Firefox OK su Mac). Da
  diagnosticare con info DevTools da Matteo: dove esattamente succede,
  console errors, tab Elements → background del `.vis-timeline`

**Niente migrate.**

## Storico recenti

**v3.5.0-alpha.43** — 7 maggio 2026 — Sidebar collassabile + Manuale d'uso wiki

Quality-of-life: sidebar collapse a 64px (toggle topbar + Ctrl+B + persistenza
localStorage), tooltip flottante hover 1s su icone collassate. Pagina /manuale
wiki interna con TOC sticky + content + search client-side + IntersectionObserver.
11 sezioni con bozze contenuti. Voce sidebar "Manuale" in nuova sezione "Aiuto".

**v3.5.0-alpha.42** — 7 maggio 2026 — Multi-move atomico + sticky multi-selection

Test live (2 booking ricorrenti split risorsa multipla) ha esposto 3
sintomi convergenti su unica root cause: `onMove` chiamava in sequenza 3
funzioni indipendenti, ognuna con suo PUT/POST + push undo + render
parziale. Sintomi: "booking spariscono" (render parziale), "14 undo per
ripristinare" (push frammentato), conflitti fantasma (check su stato
intermedio), click+drag deseleziona. Fix: endpoint atomico
`POST /planning/api/multi-move` con conflict check escludendo TUTTI gli
aids della transazione + all-or-nothing rollback; frontend
`_tlApplyMultiMove` (anchor + sibling + altri + loro-sibling con dedup)
con 1 push undo atomico + 1 renderTimeline finale; sticky multi-selection
con loop guard sincrono.

**v3.5.0-alpha.41** — 7 maggio 2026 — Font label timeline via HTMLElement (vis-timeline strippa style annidati)

α.40 ha messo inline styles brutali nelle stringhe HTML del content delle
label risorsa, ma il bold/font sui nomi operatore restava invisibile (header
reparto invece corretto). Diagnosi confermata da DOM dump Matteo: tutti i
class+style annidati spariti. Vis-timeline 7.7.3 sanifica gli HTML string
passati come `group.content` quando contengono nested elements. Fix: passare
HTMLElement detached (`document.createElement` + `style.cssText` +
`textContent`). Header reparto invariato (single `<span>` root).

**v3.5.0-alpha.40** — 6 maggio 2026 — Inline styles font + no-confirm multi-move + no race split

α.39 ha sistemato i tint colore-risorsa (visibili) ma il bold/font su
nome operatore + funzione restavano invisibili nonostante CSS
`!important`. La fix con inline styles brutali NON ha risolto (vedi α.41
per la diagnosi vera: vis-timeline strippa style+class annidati).
Restano validi gli altri due interventi: NO-CONFIRM multi-move +
tlPushUndo + NO RACE SPLIT.

**v3.5.0-alpha.39** — 6 maggio 2026 — Fix tint+font + multidrag bulk + render mutex

Tre bug bloccanti chiusi: tint sfondo via `_tlInjectResourceTints` (era
silenziato da `window.RESOURCES_SEED` undefined), multidrag refactor a
bulk-edit (1 round-trip), render serializzato via promise queue. Il
font/bold restava invisibile nonostante CSS aggressivo: chiuso in α.40
con inline styles.

**v3.5.0-alpha.38** — 6 maggio 2026 — Polish ROI/look + bulk-edit esteso + filtro orario

Round di rifiniture: rimosso bottone Seleziona, ROI selezione additiva,
look label timeline (font + tint colore-risorsa, ma con bug
`window.RESOURCES_SEED` che ha richiesto α.39 per essere visibile),
bulk-edit con orario assoluto + nuova data, filtro orario nei filtri.

**v3.5.0-alpha.37** — 6 maggio 2026 — Fix ROI: tasto S + selezione precisa per riga

α.36 ha portato l'overlay-div funzionante; due bug emersi al test live
chiusi: tasto S inerte (sostituita guardia ACTIVE_VIEW con check classe
`.active` su `#view-timeline`) e selezione che includeva righe
sottostanti (rimossa logica group-set buggata, sostituita con check
DOM rect per ogni item via `tlInstance.itemSet.items[id].dom.box`).

**v3.5.0-alpha.36** — 6 maggio 2026 — ROI overlay-based + scorciatoia tastiera "S"

Riscrittura totale del ROI dopo che α.35 non funzionava: vis-timeline
7.x usa Hammer.js su PointerEvents, mousedown capture-phase non basta.
Approccio definitivo: overlay-div trasparente sopra l'host. Aggiunta
scorciatoia tastiera `S`. Funzionante ma con due bug emersi al test
live (chiusi in α.37): tasto S inerte e selezione che includeva righe
sottostanti.

**v3.5.0-alpha.35** — 6 maggio 2026 — ROI rubber-band riabilitato + funzione sotto nome operatore

Primo tentativo di riabilitazione ROI (handler in-line + Alt-drag +
toggle persist-mode). Non funzionava per Matteo: vis-timeline/Hammer.js
intercettava i mouse events. Sostituito da α.36 con approccio overlay-div.
Resta valida la parte "funzione (role) sotto nome operatore" nelle
foglie risorsa della timeline (RESOURCES_SEED esteso + render
`tl-res-name` + `tl-res-role` font 10.5px italic muted).

**v3.5.0-alpha.34** — 6 maggio 2026 — Admin Export/Import dati

Tool admin per export/import completo (DB + memorie Claude + Excel
human-readable). Risolve sync PC↔Mac (memorie vivono fuori dal repo) +
funziona come backup/restore generico. Pagina dedicata in `/settings`,
solo admin.

**Chiuso α.34:**
- ✅ `app/services/data_export.py`: `build_export_zip()` con DB + metadata +
  README + Excel multi-sheet (listino/quotazioni) + memorie Claude (path
  mangled cross-OS), opt-in env/uploads/trash, AES-256 password via pyzipper
- ✅ `app/services/data_import.py`: `restore_from_zip()` con check major
  version, DB swap atomico (backup auto + rollback su errore), memorie
  ricalcola path mangled per macchina locale (non riusa quello sorgente)
- ✅ `app/routers/admin_data.py`: 4 endpoint sotto `/settings/admin/data/*`
  con dependency `_require_admin` (RBAC `is_admin`)
- ✅ Tab "Dati" in `/settings` (icona Lucide `database`), visibile solo se
  `is_admin(user)`. Card Export con 4 checkbox + password. Card Import con
  file upload + password + 3 restore flag + warning rosso
- ✅ JS `adminExportZip()` (window.location download) e `adminImportZip()`
  (confirm + summary actions/warnings)
- ✅ Dependency: `pyzipper>=0.3.6` aggiunto a requirements.txt

**Verifica live richiesta a Matteo:**
- Apri `/settings` come admin, vedi la nuova tab "Dati"
- Click "Scarica ZIP completo" senza opzioni opt-in: arriva ZIP base
  (~MB con DB + Excel + memorie)
- Click "Solo Excel listino" / "Solo Excel quotazioni": file `.xlsx`
- Su altra macchina (Mac): tab Dati → Import → carica lo ZIP →
  conferma → vedi summary con "DB ripristinato" e "Memorie Claude
  ripristinate (N file) in /Users/.../memory"
- Riavvia il server dopo restore

**Note operative**:
- Password ZIP cifra con AES-256 standard (apribile anche da 7zip/WinZip
  con la password — utile se vuoi consultare il contenuto manualmente)
- Backup DB precedente sopravvive: `mediaflow.db.backup-<timestamp>` in
  cartella progetto. Cancellabile a mano una volta verificato il restore
- Major version mismatch rifiutato: export α.34 in app α.34/35/36 ok,
  in app v4.x rifiuta (schema potrebbe essere cambiato)
- `.env` opt-in: di default NO. Se attivo, l'export contiene secrets
  (API keys, JWT secret, AI_KEY_ENCRYPTION_KEY) — non condividere

**v3.5.0-alpha.33** — 6 maggio 2026 — Capability copilot `propose_resource`

Nuova capability AI per creare risorse via copilot. Pattern coerente con
le altre 9 mutation: AI propone, utente conferma in drawer. Renderer
human-readable per la card.

**Chiuso α.33:**
- ✅ `ai_tools.py`: tool definition `propose_resource` (name+type required,
  6 ResourceType ammessi, dept_id|dept_name, role, tariffe, contatti)
- ✅ `ai_assistant.py`: handler `_h_propose_resource` con validazioni +
  resolve dept (id/name) + `_opt_num` per tariffe (0/None → NULL DB) +
  color sanitization
- ✅ Registrato in `_ACTION_HANDLERS` e `VALID_ACTION_TYPES` (recuperato
  anche `propose_booking` che mancava lì da α.20)
- ✅ `ASSISTANT_SYSTEM_PROMPT` aggiornato con schema della nuova capability
- ✅ `copilot.js`: label "Risorsa (nuova)", `summaryResource` + `summaryBooking`
  (anche quest'ultimo mancava — cadeva nel fallback "Nessun renderer")
- ✅ Cache-buster `copilot.js?v=3.5.0-alpha.33` in `components/copilot.html`

**Verifica live richiesta a Matteo:**
- Apri il copilot (FAB ⓘ in basso a destra) e chiedi: "Crea una risorsa
  freelance Mario Rossi colorist nel reparto DI"
- L'AI dovrebbe rispondere con un blocco action `propose_resource`
- La card di conferma dovrebbe mostrare riassunto leggibile (non JSON grezzo)
- Click "Applica" → la risorsa appare in `/resources` con i campi corretti
- Tariffe non specificate → restano vuote (non 0)

**Niente migrate**: solo codice di servizio.

**In coda Round 12**:
- 🔜 **Multiselect/multidrag** — desiderata forte (memoria
  `feedback_multiselect_multidrag.md`)
- 🔜 Test Mac+Chrome del branch `experiment/timeline-audit` (performance)
  → se OK merge in main come α.34

**v3.5.0-alpha.32** — 6 maggio 2026 — Cross-department: warning + badge persistente

Fix di un bug latente da α.23 (24 aprile): il warning cross-department
era silenziato da un TDZ JavaScript dentro un `try/catch(_) {}`. Aggiunto
in più il badge persistente ⚠ sull'item con bordo amber, così il mismatch
risorsa/task è visibile anche post-drop e tra sessioni.

**Chiuso α.32:**
- ✅ Backend `_booking_task_department_id(b)` + `_dept_mismatch_payload(...)`
  helpers in `app/routers/planning.py`
- ✅ Serializer `list_bookings` espone `cross_department: bool` per ogni
  assignment (calcolato server-side dal join cost_line.price_item.dept_id)
- ✅ Endpoint `PUT /api/booking-assignments/{id}` include
  `cross_department: {task/resource dept id+name}` nel response (informativo)
- ✅ Frontend fix bug TDZ in `onMove`: `orig`/`origBooking`/`assignmentId`
  spostati prima del check, `try/catch(_) {}` swallowing rimosso
- ✅ `tlBookingToItem()` aggiunge classe `tl-cross-dept` se mismatch +
  tooltip `⚠ Reparto risorsa (X) ≠ reparto task (Y)`
- ✅ `onMoving()` applica classe live durante drag preview (cleanup ad ogni
  frame per evitare stale state)
- ✅ CSS `.vis-item.tl-cross-dept`: bordo amber inset 4px + glow + ⚠ in
  alto a destra. Combinabile con tl-conflict / tl-tentative / tl-exec-*

**Architettura cross-department** (decisione 6/5/2026):
- A1 derivato (no schema change): `task_dept = cost_line.price_item.department_id`
- B2 + B3: confirm al gesto + badge persistente (visione d'insieme)
- C1 singolo dept per Resource (no multi-dept; rivalutare se emergono
  persone tuttofare nel team — Matteo confermato "no")

**Verifica live richiesta a Matteo:**
- Spostare un booking di Sara Conti (DI) su Davide Moretti (Audio):
  durante il drag dovrebbe apparire bordo amber + ⚠ live
- Al drop: confirm "Risorsa di reparto diverso dal task. Task → DI ·
  Risorsa target → Audio. Procedere comunque?"
- Al rifiuto: torna alla posizione originale
- All'accettazione: il booking si sposta e MANTIENE il badge ⚠ persistente.
  Refresh pagina → badge sempre lì
- Hover sul booking: tooltip include riga `⚠ Reparto risorsa ≠ reparto task`

**Niente migrate**: il dato `department_id` esisteva già su PriceItem e
Resource; il flag è derivato server-side al GET.

**Note operative**:
- α.31 saltata: branch isolato (`experiment/timeline-audit`) non mergato
  in main. Teniamo separato per il test performance Mac+Chrome
- Il branch audit ha fix performance (onMoving index, .tl-dragging CSS)
  NON ancora in main: se test Mac va bene, merge come α.33

**In coda Round 12** (priorità):
- 🔜 **Multiselect/multidrag** — desiderata forte di Matteo (vedi memoria
  `feedback_multiselect_multidrag.md`). Da affrontare strutturalmente
- 🔜 Capability copilot "crea risorsa"

Cache-buster `v=3.5.0-alpha.30` invariato (modifiche solo a planning.html
template + planning.py router; niente static asset toccato).

**v3.5.0-alpha.29** — 6 maggio 2026 — Round 11 (4/6): suoni soft

Suoni discreti via WebAudio (sintetizzati, zero file MP3). Toggle in
`/settings` → Aspetto. Default: notifiche ON, AI OFF (meno invasivo).

**Chiuso α.29 (4/6):**
- ✅ `playSound(name)` in global.js con WebAudio: `notify` due note sine
  880→1320Hz (stile macOS Tink, ~200ms), `ai_done` bell 660Hz + 3a armonica
  (~600ms)
- ✅ Throttle 800ms anti-spam, AudioContext lazy + auto-resume
- ✅ `toast()` invoca notify per type ≠ 'info'
- ✅ Copilot drawer invoca ai_done a risposta completa
- ✅ Card "🔔 Suoni" in `/settings` Aspetto con toggle + bottoni test
- ✅ Smoke test boot OK

**In coda Round 11 (2/6):**
- 🔜 α.30 — Migrazione completa icone Lucide
- 🔜 branch `experiment/timeline-audit`

Cache-buster `v=3.5.0-alpha.29` (global.js + copilot.js).

**v3.5.0-alpha.28** — 6 maggio 2026 — Round 11 (3/6): filmografia dedicata + campi estesi

La filmografia esce dalla scheda cliente. Pagina dedicata
`/clients/{id}/works` con vista a griglia di card e modal edit a 6
sezioni. `ClientWork` esteso con 6 nuovi campi.

**Chiuso α.28 (3/6):**
- ✅ Modello `ClientWork` esteso: synopsis, release_date, funding_public,
  cast_crew, external_links, awards (auto-migrate)
- ✅ Backend `_work_dict()` + PUT endpoint estesi con i nuovi campi (con
  sentinel di clearing)
- ✅ Nuovo route HTML `GET /clients/{client_id}/works`
- ✅ Nuovo template `client_works.html` con grid responsive di card +
  modal edit a sezioni + filtri live (testo/tipo/anno)
- ✅ Modal cliente pulito: tab Filmografia rimossa, ~268 righe di JS
  legacy cancellate, bottone "🎬 Filmografia" in footer linka alla pagina
- ✅ Smoke test boot: tutte e 6 le colonne presenti, app starts correctly

**Limiti noti α.28:**
- L'AI search ancora restituisce solo i campi base (title/year/kind/role/
  director/country). I 6 campi nuovi vanno compilati a mano post-import,
  oppure tramite un'estensione futura del prompt AI. Decisione: lasciare
  fuori dal cantiere α.28 per non gonfiarlo, valutare con Matteo se
  serve.

**Verifica live richiesta a Matteo:**
- Aprire una scheda cliente, cliccare "🎬 Filmografia" → si apre la
  nuova pagina con eventuali opere già presenti
- Aggiungere/modificare un'opera con i campi estesi (sinossi, cast & crew,
  finanziamenti, link, premi)
- Filtri (testo/tipo/anno) sulla griglia
- Verificare che la scheda cliente non abbia più la tab Filmografia

**In coda Round 11 (3/6):**
- 🔜 α.29 — Suoni soft notifiche + AI
- 🔜 α.30 — Migrazione completa icone Lucide
- 🔜 branch `experiment/timeline-audit`

Cache-buster `v=3.5.0-alpha.28`. Auto-migrate: 6 nuove colonne in
`client_works`.

**v3.5.0-alpha.27** — 6 maggio 2026 — Round 11 (2/6): optional + sezioni quote

Voci "opzionali" + etichette di sezione intra-categoria su `QuoteLine`.
Risolve due scenari del feedback Matteo: voci proposte ma non incluse nel
totale, e raggruppamento di deliverable per portale (SKY/NBCU/Beta Film…)
dentro la stessa categoria.

**Chiuso α.27 (2/6):**
- ✅ Modello `QuoteLine.is_optional` + `QuoteLine.section_label` con
  auto-migrate
- ✅ Backend `_recalc_quote()` esclude opzionali da subtotali; POST/PUT
  endpoint accettano i nuovi campi; GET espone `subtotal_optional`
- ✅ UI: badge "Opzionale" + bottoni `🏷` (sezione) e `○` (toggle opt)
  inline su ogni riga; section header + subtotale di sezione quando
  `section_label` cambia; blocco "Optional aggiuntivi" in fondo ai totali
- ✅ PDF: tabella principale solo billabili; tabella separata "OPTIONAL
  AGGIUNTIVI — non inclusi nel totale" amber-styled
- ✅ Bug-fix laterale: `_auto_migrate_columns()` print con `→` Unicode
  crashava su Windows charmap codec → sostituito `->` ASCII (latente da
  v3.4.27.1)
- ✅ Smoke test boot: lifespan + migrate OK, ambo le colonne presenti

**Verifica live richiesta a Matteo:**
- Aprire una quote esistente, marcare 1-2 righe come opzionali col bottone
  `○`, vedere il blocco "Optional aggiuntivi" sotto i totali
- Su righe della stessa categoria, settare `section_label` (es. "SKY",
  "NBCU") tramite bottone `🏷` → vedere mini-header + subtotale di sezione
- Esportare PDF → verificare tabella optional separata in fondo

**In coda Round 11 (4/6):**
- 🔜 α.28 — Pagina filmografia dedicata + campi estesi
- 🔜 α.29 — Suoni soft notifiche + AI
- 🔜 α.30 — Migrazione completa icone Lucide
- 🔜 branch `experiment/timeline-audit`

Cache-buster `v=3.5.0-alpha.27`. Auto-migrate: 2 nuove colonne in `quote_lines`.

**v3.5.0-alpha.26** — 6 maggio 2026 — Round 11 (1/6): rimozione matrice + kanban

Apertura Round 11 sui feedback Matteo del 6 maggio. 6 voci totali divise
per scope. Prima voce chiusa: l'area `/assignments` (matrice + kanban)
sparisce. Le assegnazioni si gestiscono solo da scheda progetto + timeline
planning. La matrice non convinceva e duplicava la gestione.

**Chiuso α.26 (1/6):**
- ✅ Cancellato `app/routers/assignments.py` + template + nav-item sidebar
- ✅ Modello `JobResourceAssignment` preservato (usato in scheda progetto)
- ✅ RBAC middleware aggiornato (`/assignments` rimosso da blocked prefixes)
- ✅ Smoke test import: `from app import main` OK con v3.5.0-alpha.26

**In coda Round 11 (5/6):**
- 🔜 α.27 — `is_optional` + `section_label` su QuoteLine (raggruppamento
  per deliverable: SKY/NBCU/Beta Film + voci opzionali fuori totale)
- 🔜 α.28 — Pagina filmografia dedicata `/clients/{id}/works` con campi
  estesi (funding pubblico, cast/crew, link esterni, sinossi, premi).
  Tab filmografia rimossa dalla scheda cliente.
- 🔜 α.29 — Suoni soft notifiche + AI risposta (royalty-free Pixabay,
  toggle in `/settings`)
- 🔜 α.30 — Migrazione completa icone Lucide (sostituzione emoji →
  SVG inline via macro Jinja, stroke 1.5px, currentColor)
- 🔜 branch `experiment/timeline-audit` — profiling vis-timeline + nostro
  codice. Sintomo Matteo: "lento già con pochi booking su 2 risorse".
  Probabile bottleneck nel custom JS (heatmap re-render, listener accumulo,
  force-redraw eccessivo). Se confermato → ottimizziamo gratis. Altrimenti
  porting su DHTMLX Scheduler GPL (free per uso interno) o Bryntum Scheduler
  Pro ($900) come ultima istanza.

Cache-buster `v=3.5.0-alpha.26`. Niente migrazione DB.

**v3.5.0-alpha.25** — 5 maggio 2026 notte tardi — Round 10 chiuso (7/7)

Chiuso anche il 7° punto: scheda cliente con filmografia AI, fonti pubbliche
italiane + IMDB/MyMovies, workflow propone+conferma, idempotente.

**Cantiere completato:**
- ✅ Modello `ClientWork` (tabella `client_works`, auto-create al boot)
- ✅ Service `app/services/filmography.py` con Tavily `include_domains` ristretto
- ✅ 5 endpoint CRUD + AI search (no scrittura DB nell'AI search, propone solo)
- ✅ Tab Filmografia nella scheda cliente con AI search + lista cards
- ✅ Modal candidati AI con checkbox, fonti cliccabili, badge confidence
- ✅ Modal edit opera con form completo + delete
- ✅ Idempotency su (title, year) — re-import safe

**Smoke test live:** ricerca su "RAI Documentari" → 14 fonti consultate, 6
opere proposte con confidence/source URLs valide.

Cache-buster `v=3.5.0-alpha.25`. Tabella `client_works` auto-creata.

**v3.5.0-alpha.24** — 5 maggio 2026 notte tardi — Round 10: planning UX refinement (6/7)

Terza tornata feedback Matteo post-test alpha.23. Chiusi 6 punti su 7. Il
7° (scheda cliente con filmografia AI) è in attesa di conferma piano:
proposta = `ClientWork` model + tab "🎬 Filmografia" + endpoint AI con
tool-use puntato a filmitalia.org / cinema.cultura.gov.it / IMDB / MyMovies.

**Chiusi:**
- ✅ Risorse duplicate sui booking: dedupe per `(booking_id, resource_id)`,
  badge "+N segmenti" nelle card, riga aggregata nel detail modal.
- ✅ Ferie/malattia/festività look uniforme (alpha 0.12, palette indigo
  MediaFlow).
- ✅ Hover ferie/malattia/festività: tooltip arricchito con periodo, durata
  giorni, risorsa, motivo, status.
- ✅ Hover job: aggiunti orari inizio/fine + icona semaforo priorità.
- ✅ Semaforo priorità più grande/distanziato in "Le mie" e "Per progetto".
- ✅ Pannello selezione "stile filtri" con 4 dropdown + glow animato sui
  selezionati (`tl-pulse-glow` ease-in-out infinite).

**In attesa conferma Matteo:**
- 🔜 Scheda cliente AI con filmografia (cantiere grosso). Proposta:
  - Modello `ClientWork(client_id, title, year, kind, our_role, director, sources_json)` — o JSON `clients.filmography`
  - Tab "🎬 Filmografia" in scheda cliente con bottone "🔍 Cerca con AI"
  - Endpoint `POST /clients/api/{id}/search-filmography` con AI tool-use
    + `web_search` (Tavily) puntato a filmitalia.org, cinema.cultura.gov.it,
    IMDB, MyMovies
  - Workflow "AI propone, utente conferma" — match candidati in cards di
    anteprima, utente seleziona quali importare
  - Import idempotente su (title, year)

Cache-buster `v=3.5.0-alpha.24`. Niente migrazione DB.

**v3.5.0-alpha.23** — 5 maggio 2026 notte — Round 9 chiuso (17/17 punti)

Round 9 sulla seconda lista feedback Matteo del 5 maggio chiuso interamente.
Push include `db_snapshots/snapshot-3.5.0-alpha.23.db` per porting test.

**Drag & drop timeline (5):**
- ✅ Cross-resource drag aggiorna cache locale + force re-render server-of-truth
- ✅ Multi-select drag — applica shift a tutti i selezionati con conferma
- ✅ Block drop su risorsa di reparto incompatibile (prompt conferma esplicita)
- ✅ Split-pause unit drag — sibling assignments shiftati insieme
- ✅ Shift+drag area vuota → modal nuovo booking pre-compilato (overlay verde con durata live)

**Settings (1):**
- ✅ Toggle "Mostra timbrature (ombra leggera)" in popover ⚙ Look timeline. Stile più sottile (10%/20% alpha).

**DB (1):**
- ✅ Snapshot DB committato in `db_snapshots/snapshot-3.5.0-alpha.23.db` per porting test su altra macchina. README istruzioni restore.

**In coda dopo test Matteo:**
- Test E2E della pausa pranzo + split overtime su edge cases
- Test del semaforo priorità in tutte le viste
- Verifica DB snapshot su Mac (porting effettivo)

Cache-buster `v=3.5.0-alpha.23`. Niente migrazione nuova.

**v3.5.0-alpha.22** — 5 maggio 2026 sera — Round 9 (parte 1/3)

Round 9 aperto sulla seconda lista feedback Matteo (5 maggio sera, 17 punti
totali). Diviso in 3 sotto-round per scope-bound. Questo bump chiude 9 punti.

**HR (3):**
- ✅ Ferie/malattia ora visibili in lista timbrature (default range = mese
  corrente sul page load `/hr` per popolare l'endpoint timeline)
- ✅ Block timbratura su giorno con ferie/malattia approvata + viceversa (409)
- ✅ Pausa pranzo opzionale in timbratura (default 60 min, opzioni 0..240 step
  15). Nuova colonna `time_punches.break_minutes` auto-migrate. Sottratta
  dalla durata e dall'engine `compute_overtime`/`compute_punch_breakdown`.

**Timeline UX (5):**
- ✅ Doppio click su item → apre modal edit booking
- ✅ Tooltip hover esteso con durata booking + ore lavorazione (totali/done)
- ✅ Priorità "semaforo" 3-dot in card "Le mie" / Per progetto + nel modal
  create/edit booking
- ✅ Booking detail arricchito (cliente, dipartimento per risorsa, ore done
  cumulato, audit count, last-edit)
- ✅ Sort priorità desc + data asc in "Le mie" e "Per progetto"

**Selezione & UX (1):**
- ✅ ROI Alt/Shift+drag disabilitato (UX confusa). Solo dropdown
  `☑ Seleziona ▾` resta attivo.

**Storyboard (1):**
- ✅ Opzione densità storyboard spostata dalla popover globale al toolbar
  della vista Storyboard.

**In coda (Round 9 part 2/3):**
- 🔜 Click+drag area vuota → modal nuovo booking pre-compilato con durata
- 🔜 Drag&move conflitti backend (cross-resource non riflesso al refresh)
- 🔜 Multi-select drag su altra risorsa
- 🔜 Block drop su risorsa di reparto incompatibile
- 🔜 Split-pause unit drag (entrambi i segmenti)
- 🔜 Settings toggle visualizzazione timbrature come ombra leggera in timeline
- 🔜 Push DB nel bundle

Cache-buster `v=3.5.0-alpha.22`. Migrazione DB auto: aggiunge colonna
`time_punches.break_minutes` al boot.

**v3.5.0-alpha.21** — 5 maggio 2026 — Round 8 (parziale)

Round 8 aperto su feedback Matteo dal test su altra macchina. 8/9 punti chiusi.

**Bug critici (8A):**
- ✅ Salvataggio Orari lavorativi: auto-create policy default al primo GET (`_ensure_default_policy`)
- ✅ Bulk modify lookup booking_id (campo a top-level non in extendedProps)
- ✅ ROI selezione area: aggiunto menu dropdown affidabile alternativo
  (Tutti visibili / Per Job / Per Risorsa / Per Date / Deseleziona)
- ✅ Permesso deprecato `edit_cost_actuals` rimosso
- ✅ RBAC orari: split `view_settings_global` (tutti) vs `manage_settings_global`
  (admin/manager). User vede ma non modifica.
- ✅ Matrice assegnazioni: banner istruzioni inline + legenda colori

**Feature (8B):**
- ✅ ProjectMilestone modello + CRUD + UI tab in /projects/{id}
- ✅ Timeline planning vista "Per progetto" (toggle in toolbar)
- 🔜 Form KDM in DAM (rinviato, cantiere medio)

**Tecnici:**
- `create_tables()` ora forza import app.models per registrare tutti i modelli
- Backend `/planning/api/bookings` espone `project_id/project_title/project_code/job_code/job_title`

Cache-buster `v=3.5.0-alpha.21`. Tabella `project_milestones` creata auto al boot.

**v3.5.0-alpha.20** — 5 maggio 2026 — Round 7D.2 + 7D.3: matrice assegnazioni + pagina Team

**Round 7 chiuso completamente** (12 punti su 12 del feedback Matteo del 5 maggio).
Sequenza alpha.16 → alpha.20 (5 versioni):
- alpha.16 → 7A (HR breakdown per-punch + ROI)
- alpha.17 → 7B (cost report lista + quote ricerca + export rendiconto/CSV/XLSX)
- alpha.18 → 7C (undo/redo planning + bulk-edit booking)
- alpha.19 → 7D.1 (AI settings registry + 3 tool generici)
- alpha.20 → 7D.2 (matrice assegnazioni scalabile) + 7D.3 (pagina /team unificata)

Sotto-round 7D.2 chiuso:
- `GET /assignments/api/matrix` server-filtered + client-filtered (ricerca live).
- Tabella matrice Risorsa × Job sticky-header + sticky-first-column.
- Cella verde = assegnata, arancione = ore booking ma no assignment (drift).
- Modal upsert con planned days/hours + role + tariffe.
- Toggle topbar Matrice/Kanban (kanban legacy preservata).

Sotto-round 7D.3 chiuso:
- Pagina `/team` con sidebar reparti drill-down (count + Senza reparto + Tutte).
- Main pane: griglia card auto-fill, ricerca live + filtri tipo/stato.
- Voce sidebar `/resources` → `/team`. Pagine `/resources` e `/departments`
  restano accessibili (link in topbar di /team).

Cache-buster `v=3.5.0-alpha.20`. Niente migrazione DB.

**v3.5.0-alpha.19** — 5 maggio 2026 — Round 7D.1: AI settings registry + tool generico

Sotto-round 7D.1 chiuso (cantiere architetturale "AI integrazione GUI/settings"
proposta A2). Discovery dinamica + patch generica → estendibile a tutto il
software senza nuove capability AI.

- `app/services/settings_registry.py`: `SettingsSchema` con read/write handlers,
  validation/coercion, RBAC. 2 schemi iniziali (`working_hours`, `tenant_settings`).
- 3 tool AI: `list_settings_schemas` + `read_setting` + `update_setting`.
- `apply_action` + `_exec_readonly` con iniezione opzionale di `user` via
  inspect.signature → handler che lo richiedono lo ricevono.
- Card mutation `update_setting` nel copilot con summary leggibile (area + diff).
- System prompt aggiornato con sezione "Settings".

Cache-buster `v=3.5.0-alpha.19`. Niente migrazione DB.

**v3.5.0-alpha.18** — 5 maggio 2026 — Round 7C: undo/redo planning + bulk-edit booking

Sotto-round 7C chiuso (2 punti):
1. **Undo/redo planning timeline**: stack max 50 + Ctrl+Y/Ctrl+Shift+Z per redo,
   2 bottoni toolbar persistenti `↶ Undo` / `↷ Redo`, undo per `remove_assignment`
   ora funziona via nuovo endpoint `POST /planning/api/bookings/{id}/assignments`.
2. **Bulk-edit booking**: bottone `✏ Bulk` toolbar (visibile su selezione ≥1),
   modal con shift orario (minuti) + cambio stato esecuzione, endpoint
   `PUT /planning/api/bookings/{id}/bulk-edit`. Snapshot pre-modifica per undo.

Cache-buster `v=3.5.0-alpha.18`. Niente migrazione DB.

**v3.5.0-alpha.17** — 5 maggio 2026 — Round 7B: cost report lista + ricerca + export

Sotto-round 7B chiuso (3 punti):
1. **Cost report da dropdown a lista filtrabile** (pattern come `/quotes`):
   nuovo `GET /cost-report/api/list` + ricerca live + 3 filtri (cliente, stato,
   margine over/under). Click riga apre dettaglio in toolbar; bottone "← Lista".
2. **Quote ricerca + filtri**: refactor `loadQuotes` in fetch+render filtrato,
   ricerca live + 3 filtri (cliente, stato, con/senza job) + counter.
3. **Export cost report cliente esteso**:
   - PDF con `?rendiconto=1` mostra Quotato/Maturato/Stimato + Over/Under per
     riga + totale finale (verde/rosso). Modalità stato storica resta default.
   - 2 endpoint nuovi: `client-csv` (UTF-8 BOM, `;` separatore) e `client-xlsx`
     (openpyxl, header indaco). Helper `_client_export_rows` condiviso.
   - Toggle "Modalità rendiconto" nella toolbar dettaglio cost report.

Cache-buster `v=3.5.0-alpha.17`. Niente migrazione DB.

**v3.5.0-alpha.16** — 5 maggio 2026 — Round 7A: HR breakdown per-punch + ROI riscritto

Aperto Round 7 su lista feedback Matteo del 5 maggio (12 punti, suddivisi in
sotto-round 7A bug puri / 7B-C feature medie / 7D cantieri di design).

Sotto-round 7A chiuso (4 punti):

1. **Straordinari per singola timbratura + nei totali** — nuovo servizio
   `compute_punch_breakdown` che distribuisce l'overtime giornaliero sui punch
   del giorno (last-in-first-out: le ore "in coda" diventano straordinario).
   Tabella `/hr` mostra colonna "Breakdown" con badge inline. Totali header
   ricalcolati sulle 9 categorie del rendiconto.
2. **Filtro Tipo in Le mie ore funzionante** — dropdown ora propone le 9
   categorie del breakdown (Regolari/Straordinari/Notturne/Festivo/Domenicali/
   Pausa/Ferie/Malattia/Permesso) invece dei raw `PunchKind` (che erano solo 6
   e non riflettevano il breakdown overtime). Filtro applicato uniformemente a
   tabella + totali via parametro `category` su `/api/timeline`.
3. **Ferie/malattia in tabella timbrature** — nuovo endpoint unificato
   `/hr/api/timeline` che fonde TimePunch + ResourceUnavailability approvate.
   1 riga sintetica per giorno per ogni record di unavailability, con bg
   colorato e durata = `daily_hours_threshold` della policy.
4. **ROI multiselect riscritto** — diagnosi: Hammer.js (vis-timeline) bypassa
   `stopPropagation` su capture-phase. Fix: `setOptions({moveable:false, zoomable:false})`
   durante il drag, trigger keys allargati a **Alt+drag** (default) +
   **Shift+drag** + toggle toolbar **"📦 Selezione area"** persistente.
   Rilevazione gruppi via scansione `.vis-label` invece di `[data-group-id]`.

Cache-buster `v=3.5.0-alpha.16`. Niente migrazione DB.

**v3.5.0-alpha.15** — 5 maggio 2026 — Round 6: ore festivo + ROI multiselect timeline

Chiusura dei 3 punti rimasti dal Round 5:
1. **Ore festivo/domenicali nel riepilogo "Le mie ore"** — aggiunte card "Festivo" (rosso) e "Domenicali" (arancione) accanto a Regolari/Straordinari/Notturne. Engine calcolava già `holiday_hours` + `sunday_hours` con multiplier dedicati ma la UI non li mostrava → 1 maggio restava "non riportato".
2. **Shift+drag ROI multiselect timeline** — implementazione custom (vis-timeline non supporta rect selection nativa). Capture-phase mousedown+Shift su area vuota traccia overlay floating, mouseup calcola intersezione [time, group]×items, `setSelection(ids)`. Si combina col bulk-delete di alpha.14.
3. **Formato data dd/mm/yyyy** — verifica: già di default via `fmtDate('it-IT')`. UI selezione formato in `/settings` rinviata.

Tasks 19-30 chiusi. 7 commit alpha sopra origin/main (alpha.9 → alpha.15).

**v3.5.0-alpha.14** — 5 maggio 2026 — Round 5: timezone timbratura + revert click + bulk cascade + UX

9 fix:
1. Timbratura timezone (9:00 → 7:00): toISOString rimosso, send raw local datetime-local.
2. Timbratura overlap: 409 se sovrapposta.
3. Timbratura ordine: ASC (calendario).
4. REVERT auto-open detail su timeline select (era v3.5.0-alpha.13 ma confliggeva).
5. Bulk delete cascade su tutti assignments del booking.
6. Cleanup aggressivo timeline pre-render (timeline duplicata post bulk delete).
7. CSS Stesso orario non copre risorsa #1.
8. Lista quote larghezza colonne min.
9. AI capability `update_quote` (modifica metadata quote esistente).

**Restano in coda (Round 6 prossimo)**:
- Shift+drag ROI multiselect timeline (custom rectangle selection — vis-timeline non supporta nativo)
- Ore straordinario 1° maggio non riportate (verifica holiday detection)
- Formato data globale dd/mm/yyyy + setting

**v3.5.0-alpha.13** — 4 maggio 2026 — Round 4: 3 bug critici + UX planning realtime + multiselect timeline

3 bug critici risolti:
1. Maturato fantasma su unità non-time (pc/lump/fix/lot/...): recompute_cost_line_actual ora setta `quantity_actual = len(bookings_done)`. + auto-reconcile silenzioso al load di /cost-report (fix retroattivo drift storici).
2. Timbratura: input fine turno non più cancellato durante digitazione (parseValue mfWrapDateTimeLocal non sovrascrive subs se hidden empty).
3. Filtro pianificazione "Per progetto" ora rispetta f-resource (project_bookings endpoint accetta resource_id csv).

5 feature UX:
- todoSetExec/Extend/Priority refresh la view attiva (refreshActiveView helper) — Fatto/Iniziato/etc. immediato qualunque sia la tab.
- Topbar planning: bottone "+ Booking" globale (visibile da tutte le viste).
- Click su booking apre il modal dettaglio in agenda + calendar + timeline (1 item) — uniforme con todo/project/storyboard.
- Timeline multiselect (Ctrl/Shift+click) + Delete/Backspace key per bulk-delete con conferma.
- Lista /quotes e cost report job-select mostrano titolo quote + titolo progetto.

1 quick win realtime:
- copilotApply dispatcha `mf:ai-action-applied` event → quotes.html ricarica la lista o l'editor automaticamente quando il copilot crea una quote.

**Lasciato fuori scope (chiarimento)**:
- "Suddivisione risorse per reparto" in pianificazione: la timeline già raggruppa per reparto via DEPARTMENTS_SEED. Servirebbe vista alternativa? Decidi cosa.
- "Caricamento documenti al copilot": cantiere grande (file picker + upload + parser AI per capitolato/post-prod schedule). Rimandato a session futura.

**v3.5.0-alpha.12** — 4 maggio 2026 — Round 3 chiuso: cost report popup booking + hardcost

Ultimi 2 issue di Round 3 chiusi.

1. Cost report: popup booking-detail su click riga (porting di `openLineDetail` da `job_detail.html`). Endpoint riusato `/jobs/api/{job_id}/cost-lines/{line_id}/detail`.
2. Hardcost dettagliato: `QuoteLine.hardcosts` esposto via detail endpoint (`hardcosts_unit`, `hardcosts_total`); blocco viola "Hardcost (materiali / spese vive)" nel popup, visibile solo se >0 e gated dietro `CAN_VIEW_FINANCE` in `job_detail.html`.

Round 1+2+3 chiusi (alpha.9 → alpha.12). 4 commit pronti dopo l'ultimo push: `2728c01` alpha.9, `eeb8189` alpha.10, `7e855ce` alpha.11, alpha.12 (in arrivo).

**v3.5.0-alpha.11** — 4 maggio 2026 — Round 3 (parziale): quote subtotali live + booking timeline UX

Sei fix raggruppati:
1. Quote `/quotes` editor: subtotale/sconto/netto per categoria live al save (prima freezing); nuova riga "Totale categoria al netto" verde se sconto > 0.
2. Resource→Project sync: hook `ensure_resources_assigned_to_job` aggiunto su `PUT /api/bookings/{id}` (replace-all assignments) e `PUT /api/booking-assignments/{id}` (reassign). Prima copriva solo il CREATE.
3. Booking done propagation: `todoSetExec` ora richiama `renderTimeline(true)` se la timeline è la view attiva. Toast: "completato (tutte le risorse del booking)".
4. Timeline highlight cross-resource: select su un item multi-risorsa applica `tl-link-highlight` (outline indaco) a tutti gli items con stesso `booking_id`.
5. Timeline copia multi-risorsa: `_tlDoDuplicate` riscritto — clona TUTTI gli assignments della sorgente (era 1 sola). Calcola offset temporale dal click point e shifta tutti.
6. Timeline drag overlay: floating box segue il cursore con start→end, durata, warning ferie/festivo. Si nasconde su drop / mouseup / Escape.

Cache-buster `base.html` → `global.js?v=3.5.0-alpha.11`. Niente migrazione DB.

**Restano in Round 3 (in coda)**:
- Cost report row → popup booking-detail (porting di `openLineDetail` da `job_detail.html` a `cost_report.html`)
- Cost report: hardcost dettagliati nel breakdown

**v3.5.0-alpha.10** — 4 maggio 2026 — Round 2: RBAC editor + ore lavorate sempre da booking

Decisione architetturale (Matteo, 4 maggio): le ore lavorate (`JobCostLine.quantity_actual`) corrispondono SEMPRE alle ore dei booking marcati `done`. Niente più override manuale dal cost line edit. La fatturazione di extra/scontistica/banca-ore forfait passerà dal flusso fatturazione dedicato (in roadmap), non da qui.

Backend rifiuta `quantity_actual` con 422 in `PUT /jobs/api/{id}/cost-lines/{lid}` e `PUT /cost-report/api/job/{id}/cost-lines/{lid}`. Permesso `edit_cost_actuals` marcato deprecato + rimosso da preset manager/accounting.

UI: campo `quantity_actual` editor sostituito da display read-only ("🔒 Derivate da booking done").

**RBAC editor (Luca Bianchi / operator)**: nuovo helper `can_create_booking` (= `edit_planning_all` OR `assign_resources`). Editor → false. Gate su `POST /planning/api/bookings` (redirige tlbSubmit lato client a richiesta) + nuovo endpoint `POST /planning/api/booking-requests` (chiunque autenticato → notifica `booking_request` action_required a producer/manager via `notify_permission("assign_resources")`).

Gate frontend in `planning.html` + `job_detail.html`: budget/costi/margine/€unitario/tot.previsto nascosti a chi non ha `view_finance`. Modal create booking → titolo "📩 Richiedi booking" / submit "Invia richiesta" per editor.

Gate `POST /cost-report/api/job/{id}/assign-resource` (e DELETE) con `can_assign_resources`. Editor → 403.

NotificationKind nuovo: `booking_request`.

Niente migrazione DB.

**v3.5.0-alpha.9** — 4 maggio 2026 — Round 1 fix post-test estensivo Matteo

Sei fix raggruppati emersi dal test del 3 maggio:
1. Cost report — `recompute_for_booking` agganciato a `DELETE booking`, `DELETE assignment`, `PUT booking (replace assignments)`, `PUT assignment` (drag/resize). Risolve il maturato fantasma post-eliminazione.
2. HR `/api/overtime` — degradazione graceful con 200+warning quando manca `WorkingHoursPolicy` default (era 400 e rompeva `/hr/`, side-effect: blocco UI timbratura).
3. Timepicker quick options — da 8 a 27 orari (07→23 + 00:00, mezz'ora sui passaggi giornata).
4. `openModal()` helper — refresh `mfApplySearchable` + `mfApplyTimePickers` sui figli del modal (fix generico al sintomo "campo non si vede" dopo `select.value=`; risolve il reparto mancante nel modal risorsa).
5. Pagina 403 + scheda pubblica error — centratura corretta (body globale ha `display:flex` per sidebar, override con `display:block` + `width:100%`).
6. `propose_quote.lines` accetta `price_item_id` (eredità dal listino) — già in alpha.4, non tocco.

Cache-buster `base.html` → `global.js?v=3.5.0-alpha.9`.

**Versioni intermedie 3.5.0-alpha.x** (3-4 maggio 2026):
- alpha.1: AI tool-use nativo Anthropic — Slice 1 foundation
- alpha.2: hotfix persistenza storia conversazione
- alpha.3: hotfix errore Apply visibile + ordine azioni AI
- alpha.4: `propose_quote.lines` con price_item_id
- alpha.5: riordino sezioni sidebar (drag&drop ⠿ header)
- alpha.6: hotfix tool_use orfani + sanitizer difensivo
- alpha.7: cestino quote (Slice 1+2+3)
  - alpha.7.1-7.5: hotfix vari
- alpha.8: cestino Project + retention auto (Slice 4+5)
- **alpha.9: Round 1 fix post-test (questa versione)**

**v3.5.0-alpha.8** — 3 maggio 2026 — Cestino Project (Slice 4) + Retention auto (Slice 5)

Cantiere "cestino" chiuso completamente. Soft-delete framework esteso da Quote a Project con stesso pattern (`_SOFT_DELETE_MODELS` + filter automatico via SQLAlchemy event listener). Retention configurabile (`trash_retention_days`, default 30, env `TRASH_RETENTION_DAYS`); 0 = disabilitato. Bottone "⏱ Purga scaduti" in `/admin/cestino` (solo admin).

**Versioni intermedie 3.5.0-alpha.x** (tutte 3 maggio 2026):
- alpha.1: AI tool-use nativo Anthropic — Slice 1 foundation (loop tool_use, mutation gated da Apply, readonly inline)
- alpha.2: hotfix persistenza storia conversazione (tool_state non azzerato a ogni end_turn)
- alpha.3: hotfix errore Apply visibile (api() helper cerca `detail`) + ordine azioni AI
- alpha.4: `propose_quote.lines` accetta `price_item_id` (eredità da listino)
- alpha.5: riordino sezioni sidebar (drag&drop maniglia ⠿ sull'header)
- alpha.6: hotfix tool_use orfani + sanitizer difensivo (`_sanitize_messages`)
- alpha.7: cestino quote Slice 1+2+3 (soft-delete framework, UI quotes, admin trash)
  - alpha.7.1: hotfix SyntaxError JS in /quotes (no JSON.stringify in onclick)
  - alpha.7.2: hotfix escapeHtml not defined (script in `block scripts` non `block content`)
  - alpha.7.3: hotfix collisione numero quote dopo soft-delete (bypass UNIQUE)
  - alpha.7.4: tool result più espliciti (created/message) per evitare allucinazioni AI
  - alpha.7.5: rinomina inline di title e number quote nell'editor
- alpha.8: cestino Project + retention auto (Slice 4+5)

Da testare sul Mac: copilot end-to-end con Sonnet (Cattleya/Gomorra/ISIDE flow); cestino quote con HARD-BLOCK booking; cestino progetto con HARD-BLOCK quote attive; pulizia totale admin per quote e progetti; retention banner in /admin/cestino.

Avviato il refactor del copilot da blocchi markdown ```action``` a **tool-use nativo** dei provider AI. Cantiere "feedback non torna al modello": Tavily girava ma i risultati restavano in UI senza rientrare nel modello → l'AI non poteva proseguire dopo le azioni applicate.

**Decisione architetturale (Matteo)**: Anthropic + OpenAI + Gemini con tool-use nativo (Slice 1+4); Ollama + Perplexity restano sul path legacy markdown. Tool readonly per DB lookup in Slice 5. Streaming in Slice 6.

**Slice 1 chiusa in questo bump** (solo Claude end-to-end):
- `app/services/ai_tools.py` nuovo — registry 9 capability con JSON Schema canonico + converter per i 3 formati provider
- `AIProvider.chat_with_tools()` astratto + implementato su `ClaudeProvider` (Messages API tool_use)
- `app/services/ai_loop.py` nuovo — `advance_loop()` (mutation gated da Apply, readonly eseguite inline) + `resume_after_action()` (riprende dopo Apply/Reject)
- `AIConversation.tool_state` + `AIAction.tool_use_id` (auto-migrate)
- Router `/api/chat`, `/apply`, `/reject` cabolati al nuovo loop con fallback legacy
- Frontend: `copilotApply` mostra la `continuation` come nuova bubble assistant

**Slice rimanenti**: 2 (test E2E), 3 (rifinitura UI), 4 (OpenAI + Gemini), 5 (readonly DB tools), 6 (streaming), 7 (cleanup legacy).

**v3.4.56** — 3 maggio 2026 — Conferma assegnazione risorse + warning quote approved senza risorse + workflow docs

Completati i 2 TODO della v3.4.55:
1. **Pre-save confirm** in modal booking: prima del save, GET `/planning/api/jobs/{id}/resource-coverage` → se ci sono risorse non ancora in `JobResourceAssignment`, dialog di conferma. Cancel = abort.
2. **Notify `quote_approved_no_resources`** (non bloccante): hook in PUT status → approved, se job ha 0 assignment notify a `assign_resources` (admin/manager/producer).

Aggiunti **3 documenti workflow** in `docs/`:
- `workflow.md` — 5 diagrammi Mermaid (state Quote, state Booking, flow forward/reverse/phantom, fonti Maturato, vincoli HARD-BLOCK)
- `data-model.md` — erDiagram entità + classDiagram con flag/stati + tabella decisioni
- `permissions-matrix.md` — matrice permesso × ruolo + permessi gate-keeper

Niente migrazione DB.

**v3.4.55** — 3 maggio 2026 — Fix sistemico: integrità Quote↔JobCostLine↔Booking, vista lavorazione read-only, auto-assignment risorse, allineamento man-hours

Cambio strutturale dopo 5 paradossi segnalati da Matteo. Sintesi:
1. **HARD-BLOCK** sulla delete di QuoteLine/JobCostLine se booking attivi (no più soft-detach silenzioso che produceva booking orfani senza lavorazione)
2. **Vista lavorazione read-only** (`modal-line-detail` + `GET .../detail`): KPI Quotato/Maturato + Origine quote + Risorse + Booking. Bottone "Modifica" solo per `view_finance`.
3. **Auto-assignment Resource → Job** via hook in POST booking (`app/services/resource_assignment_sync.py`, idempotente)
4. **Man-hours canonico**: `cost_line_sync._booking_hours` ora somma durate assignments (era shell-duration), allineato con `reverse_quote`. Fix maturato sottostimato per booking multi-risorsa.
5. Mantenuto lock `quantity_actual` per non `edit_cost_actuals` (v3.4.54).

Niente migrazione DB.

**v3.4.54** — 3 maggio 2026 — Project filter nel booking + cost-line RBAC (no override maturato per editor)

Due fix critici post-test v3.4.53:
1. **Project filter prima della Quote** nel modal booking (restringe ambito, evita ambiguità nomi). Picker progetto sopra il picker quote, filtro automatico QUOTES_SEED.
2. **Cost-line RBAC + lock del maturato**: editor non può più modificare `quantity_actual` (sballava cost report). Permesso nuovo `edit_cost_actuals` (admin/manager/accounting; producer/operator NO). Backend gate POST/PUT/DELETE cost-lines su `view_finance`; PUT extra-gate su `edit_cost_actuals` per `quantity_actual`. Frontend job_detail.html: input read-only + badge se non autorizzato; bottone "Aggiungi extra" nascosto a non-finance.

Maturato canonico = sync dai booking `done` (cost_line_sync v3.4.41). Override manuale è eccezione gestita da finance, non default.

**v3.4.53** — 3 maggio 2026 — Booking parla quote+lavorazione (Job nascosto), filtro reparto risorse

Modal booking riscritto: il campo "Job" diventa "Quotazione" (autocomplete `QUOTES_SEED` con stati draft|sent|approved). La lavorazione è obbligatoria e filtrata per dipartimento delle risorse selezionate (ricarico automatico al cambio risorse). Job resta nel DB ma invisibile.

Backend: `GET /quotes/api/{id}/booking-lines?dept_ids=...` (cost_line per approved, quote_line per pending) + `POST /quotes/api/{id}/promote-line-to-cost-line` (approva implicit + ensure Job + crea JobCostLine, idempotente, notifica AM). `tlbSubmit` lato client: se kind=quote_line, promuove prima del save booking.

Caso d'uso target: emergenza cliente con quote in trattativa → bookings attaccano lavorazioni alla quote draft/sent con approvazione implicita.

**v3.4.52** — 3 maggio 2026 — Reverse-flow v2: booking → QuoteLine + approvazione implicita / phantom quote

Riformulazione architetturale dopo discussione con Matteo. Il driver canonico è la **Quote**, non il Job. Reverse: booking su progetto senza quote attiva → 2 modalità: (1) **attach_existing** alla quote draft/sent con approvazione implicita + notifica account managers (`edit_quotes`); (2) **create_phantom** = nuova `Quote(is_phantom=True, status=approved)`. In entrambi i casi il forward-flow standard `_create_job_from_quote` crea il Job. Niente più qty/prezzo manuali: tutto da `booking_hours` + voce listino.

Aggiunto `Quote.is_phantom` (auto-migrate). Nuovo `NotificationKind.quote_reverse_approval`. Service `app/services/reverse_quote.py`. Endpoint `POST /quotes/api/reverse-attach`. `GET /projects/api/{id}/job-context` esteso (approved/pending/phantom quotes + suggested_flow). Sub-modal `modal-tlb-reverse-quote` con anteprima riga calcolata. Eliminati: `app/services/job_extras.py` + `POST /jobs/api/reverse-extra` (defunti dalla v3.4.51).

**v3.4.51** — 3 maggio 2026 — Reverse-flow: job extra da booking su progetto senza quote

Cambio architetturale: un Job non nasce mai dal nulla con valore commerciale arbitrario. Forward (Quote.approved → Job) o Reverse (Booking su progetto senza quote → modal blocking → Job extra creato/riusato + JobCostLine extra + price_item). Service `app/services/job_extras.py`. Endpoint `GET /projects/api/{id}/job-context` + `POST /jobs/api/reverse-extra`. Sub-modal `modal-tlb-extra-job` in /planning con CTA in fondo al job-search. ProjectType `internal` come label. Bonifica seed: rimosso Job Sky orfano con budget arbitrario. Niente migrazione DB.

**v3.4.50.3** — 2 maggio 2026 — Elimina progetto (solo se senza quotazioni)

Tasto 🗑 in colonna azioni `/projects` accanto a "Apri →". Visibile a `can_view_finance`. Disabilitato + tooltip se `quotes_count > 0`. Backend `DELETE /projects/api/{id}` ora richiede permesso e blocca se `p.quotes` (oltre al pre-esistente check su `p.jobs`).

**v3.4.50.2** — 2 maggio 2026 — Modal scrollabile con header/footer fissi

Fix UX globale: i `.modal` ora si capano all'altezza viewport (`max-height: calc(100vh - 40px)` + flex column), header/footer fissi, body interno scrollabile. Risolve scheda cliente troppo alta (anagrafica+dati fiscali+sede+referente+note+filmografia+progetti+fonti AI) e tutti i modal con tanti campi. Approccio generico — niente toppe per-pagina.

**v3.4.50.1** — 2 maggio 2026 — Audit pre-push: 3 micro-fix

Bug fix emersi durante audit completo: (1) `seed_demo` tenant idempotente (`reset_business_data` preserva tenants → seed_demo doveva fare upsert); (2) `seed_demo` Booking ora crea `Booking + BookingAssignment` coerenti col modello multi-risorsa v3.4.16+; (3) `new_version_quote` ora pulisce suffisso `-vN` finale dal root number (no più `-v1-v2`).

**v3.4.50** — 2 maggio 2026 — Resource presets + sync orario tra risorse

Modal multi-risorsa booking: (1) preset di selezione `ResourcePreset(name, resource_ids JSON, …)` — CRUD su `/planning/api/resource-presets`, dropdown "📁 Carica preset…" + bottone "💾 Salva preset" (nome via prompt), apply con dedup + riempimento righe vuote + ereditarietà start/end dalla 1ª riga; (2) checkbox "🔗 Stesso orario per tutte le risorse" — propaga start/end della 1ª riga alle altre, preferenza in localStorage `mf_tlb_sync_times`. Tabella `resource_presets` auto-creata al boot.

**v3.4.49** — 2 maggio 2026 — Reset business data script

Nuovo `scripts/reset_business_data.py` (voce `[O]` su strumenti). Cancella tutte le entità "business" (clienti/progetti/quote/job/booking/risorse/timbrature/fatture/asset/notifiche/AI conversazioni) preservando configurazione (utenti/ruoli/reparti/listino/policy/AI settings/tenant/delivery_templates/tags). Idempotente in transazione, reset sqlite_sequence. Per il giro di test cumulativo del setup aziendale da scratch.

**v3.4.48.2** — 2 maggio 2026 — Look timeline: famiglia font + colore testo

Pannello ⚙ esteso: "Famiglia font" (auto/DM Sans/Inter/System/Serif/Mono) e "Colore testo" (auto/white/soft/amber/dark/indigo). Apply via `data-font-family` e `data-text-color` su `#tl-host` su items+label+time-axis. Auto eredita dal tema globale o dal bg variant.

**v3.4.48.1** — 2 maggio 2026 — Hotfix colore sfondo timeline

`data-bg` ora applicato a `.vis-timeline` (figlio dell'host) per superare il gradient hardcoded della libreria. Reset trasparente su `.vis-panel/.vis-foreground/.vis-background`. Variant "paper" con palette chiara (testo/grid/label invertiti).

**v3.4.48** — 2 maggio 2026 — Look timeline tweaks (bg + 3D items + dept fix)

Pannello ⚙: rimossa "Densità", aggiunta "Colore sfondo" (7 preset: default/dark/darker/warm/cool/forest/paper). Items: radius 7→9 + box-shadow multi-layer per effetto 3D bevel (inset highlight top + inset depth bottom + drop close+ambient). Fix accent "Per reparto": `DEPARTMENTS_SEED` ora include `color`, `tlBuildGroups` aggiunge className `tl-dept-{id}`, `tlPrefsApply` genera CSS dinamico per ogni reparto (gradient + border + filter brightness). Helper `_hexToRgba`.

**v3.4.47** — 2 maggio 2026 — Filtri planning multi-select

I 4 filtri autocomplete (Cliente, Progetto, Job, Risorsa) ora multi-tag con chips. Hidden value `comma-separated` ids. Backend helper `_parse_id_list` su `/planning/api/jobs|bookings|unavailabilities` accetta single, comma-separated, list. Active filters bar: "N selezionati" se >1. Backspace su input vuoto rimuove l'ultimo chip.

**v3.4.46** — 2 maggio 2026 — Look timeline customization (preferenze locali)

Pannello ⚙ in topbar `/planning?view=timeline`. Settings: densità (compact/normal/comfort), font items (11/11.5/12/13), accent reparto (indigo/mono/dept), storyboard density, toggle animazioni/heatmap/today-glow/weekend-bg. Persisted in `localStorage` `mf_tl_prefs`. Applicati via `data-*` su `#tl-host` + CSS reactive + `<style id="tl-prefs-dynamic">` per font-size. Niente backend, niente migrazione.

**v3.4.45.1** — 2 maggio 2026 — Hotfix `/planning` 500 (UserRole.code)

Fix critico: `cur_user.role.code` non esisteva (User.role è l'enum legacy UserRole). Sostituito con `is_producer(user)` da `app.services.rbac` in `planning_hub` e `project_bookings`. /planning/ ora 200.

**v3.4.45** — 2 maggio 2026 — Look timeline: deep restyle + Storyboard view

C4a: pass CSS su vis-timeline (time axis tipografato, items radius/padding/glow, drag handles fade-in, today line con dot+glow, group nesting più contrastato, heatmap container con radius). C4b: nuova tab `🎬 Storyboard` settimanale, 7 colonne giorno (Lun→Dom), navigazione settimana, cards booking ordinate per ora con badge risorsa colorato, click → modal dettaglio. Responsive (1100px → 4 col, 720px → 1 col).

**v3.4.44** — 2 maggio 2026 — Ore lavorate + drilldown + view per progetto

#6: indicatori execution_status sui booking timeline (in_progress=pulse arancione, done=bordo verde+✓, not_done=tratteggiato rosso) via classi `tl-exec-*` in `tlBookingToItem`. #7a: cell ore in `/planning?view=jobs` cliccabile → modal drilldown con lista prenotazioni del job. #7b: tab "📂 Per progetto" in `/planning` visibile a admin/manager/producer/edit_planning, dropdown progetti + cards "Le mie" raggruppate per risorsa. Endpoint `GET /planning/api/project-bookings?project_id=X`.

**v3.4.43** — 2 maggio 2026 — Duplica quote con scelta progetto + Sposta progetto

#4: `POST /quotes/api/{id}/duplicate` accetta `project_id` opzionale (riallinea client_id al progetto target). UI: modal `Duplica quotazione` con dropdown searchable progetti (vuoto = stesso progetto). Nuovo endpoint `PUT /quotes/api/{id}/move-to-project` per spostare una quote `draft` senza job a un altro progetto. Bottone "🚚 Sposta" nell'editor, visibile solo per draft.

**v3.4.42** — 2 maggio 2026 — Undo paste timeline + Le mie con dettaglio booking + note

#1: `tlPasteAt` ora pusha undo `paste_batch` con gli id dei booking creati → annullamento bulk via DELETE. #8: card "Le mie" e dashboard "I miei booking di oggi" cliccabili (su title/meta) → modal `Dettaglio booking` con Quando/Job/Lavorazione/Stato/Risorse/Note/Motivazione. Note del booking ora visibili inline sulla card. Endpoint nuovo `GET /planning/api/bookings/{id}/detail`.

**v3.4.41** — 2 maggio 2026 — Bug fix triplo (paste su ferie + Chrome timbratura + cost report ore done)

#2: paste timeline planning ora hard-block su risorse in ferie/malattia (toast con counter bloccati). #3: Chrome `::-webkit-calendar-picker-indicator` soppresso su input time non-opt-out + `.mf-dt` grid con `minmax(0, …)` per layout robusto in modali stretti. #5: nuovo servizio `cost_line_sync.py` aggancia `JobCostLine.quantity_actual` + `total_accrued` ai booking `done` (hook in execution/extend + endpoint `POST /cost-report/api/job/{id}/reconcile-actuals` per fix retroattivo).

**v3.4.40** — 2 maggio 2026 — Searchable dropdowns + Time picker popup

Helper trasversali in `global.js`: ogni `<select>` non-multiple e senza `data-no-search` viene trasformato in combobox cercabile (input ricerca + dropdown filtrabile, keyboard ↑↓EnterEsc, sync programmatico via `select._mfSsRefresh()`). Ogni `<input type="time">` riceve popup HH:MM step 15min con quick-pick row. Ogni `<input type="datetime-local">` viene splittato in due input affiancati (date + time) con il time-picker custom applicato al sub-time. Stile coerente con palette indigo. Cache-buster `?v=3.4.40`.

**v3.4.39** — 2 maggio 2026 — Quote: duplica + versioning + Floating Jobs

Due funzioni distinte: (1) `📋 Duplica` semplice (clone indipendente, scenari/template), (2) `📐 Versione` (legata via `parent_quote_id`, numero `-v2`/`-v3`, eredità righe via `QuoteLine.parent_line_id`). Endpoint `migrate-job` per migrazione del Job tra versioni con preview righe orfane/sforamenti e scelta `orphan_strategy` (`keep_as_extra` o `floating_job`). Nuovo enum `QuoteStatus.superseded`. Sezione "⚠ Anomalie" in `/finance` con 3 card (Job orfani, Sforamenti, Extra) + badge counter sulla tab. Migrazione `[N]` idempotente, auto-applicata al boot.

**v3.4.38** — 1 maggio 2026 notte profonda — Round 3 Audit: hardening logico (3 round completati)

Audit logico completo (R1+R2+R3). R3.1 invariante count_in_costs↔execution_status. R3.2 RBAC edit_quotes su update_quote. R3.3 reset original_end_datetime su shortening (booking accorciato sotto soglia → overtime_status=none). R3.4 FSM transizioni JobStatus con matrice esplicita. R3.5 cleanup Timesheet legacy nel cost report (rimossi hours_cost/hours_cost_legacy_timesheet/timesheet_summary, fonte canonica = Booking).

**v3.4.37** — 1 maggio 2026 notte profonda — Round 2 Audit: barra avanzamento job

Round 2 di 3 dell'audit. Endpoint `/planning/api/jobs/{id}/progress` + flag `?include_progress=true` su lista jobs. Colonna "Avanzamento" in `/planning?view=jobs` con barra CSS color-coded. Algoritmo: ore booking `done` / ore booking totali (esclusi cancelled e pool not_done).

**v3.4.36** — 1 maggio 2026 notte profonda — Round 1 Audit: lifecycle Quote↔Job sano

Round 1 di 3 dell'audit logico richiesto. Chiude i bug critici lifecycle (B1, B3, B4, B5, C2): cancellare/modificare/aggiungere righe quote dopo approvazione del job ora sincronizza correttamente JobCostLine. Soft-detach Booking/TimePunch su delete JobCostLine. Migrazione cleanup `[M]` per orfani esistenti. Round 2 (job progress bar) e Round 3 (hardening RBAC/FSM/invariants) restano da fare.

**v3.4.35** — 1 maggio 2026 notte tarda — Undo stack + Salva su /quotes editor

Stack undo client-side per add/delete/reorder voci e reorder categorie. Bottone "↺ Annulla" in topbar + toast post-azione con annulla cliccabile (5s). Bottone "💾 Salva" cosmetico (auto-save resta attivo).

**v3.4.34.5** — 1 maggio 2026 notte tarda — Fix drag&drop listino→voci (regressione v3.4.34 multi-tbody)

**v3.4.34.4** — 1 maggio 2026 notte tarda — Listino allargato +35% (480→650px, 440→600px sotto 1400)

**v3.4.34.3** — 1 maggio 2026 notte tarda — Critical Assumptions reagisce al toggle Listino

Fix: la topbar (con Critical Assumptions inline) ora si stringe correttamente quando il pannello Listino flottante è aperto. Classe `.with-pricelist` applicata sull'intero wrapper `#quote-editor` (non solo sul body).

**v3.4.34.2** — 1 maggio 2026 notte tarda — Listino flottante + same-height top + IVA in Riepilogo

Listino ora `position:fixed` (sempre visibile durante scroll, non più sticky). Riepilogo e Stato&azioni hanno stessa altezza (align-items:stretch). IVA spostata da Stato a Riepilogo (editabile inline). Note/Termini compatti rows=1 espandibili al focus.

**v3.4.34.1** — 1 maggio 2026 notte tarda — Layout editor /quotes: Stato a sinistra, Listino sticky

"Stato & azioni" spostato nella colonna sinistra accanto a "Riepilogo economico" (grid 2 col). Colonna destra = solo pannello Listino sticky che resta a posizione fissa durante lo scroll della pagina (scroll interno alla lista risultati).

**v3.4.34** — 1 maggio 2026 notte tarda — Refactor layout editor /quotes (Critical Assumptions compatto, riepilogo sopra, riordino categorie)

Riorganizzazione UX dell'editor quotazione su richiesta Matteo: Critical Assumptions in topbar inline, bottone "+ Aggiungi voce" rimosso (lascia solo "📋 Listino"), Riepilogo economico sopra le voci, Stato & azioni sopra il Listino, riordino categorie con drag&drop (multi-tbody + SortableJS, persistito in `Quote.category_order` JSON nuovo).

**v3.4.33.1** — 1 maggio 2026 notte tarda — Pannello "Aggiungi voce" laterale persistente

Chiarimento UX listino /quotes. Il vecchio modal `#modal-add-line` e il mini-pannello `#side-pricelist` (v3.4.29) sostituiti da un singolo pannello laterale persistente `#side-add-line` (480px, GUI ricca con sidebar categorie + ricerca + risultati grandi cliccabili E draggable). Resta aperto fino click ✕. Aggiunta voce non chiude il pannello (multi-aggiunta in fila).

**v3.4.33** — 1 maggio 2026 notte — Cost report v2 (fonte Booking) + PDF cliente + listino /quotes default open

Cantiere "Cost Report doppio" avviato dopo conferme strategiche (Q1 fonte=Booking, Q2 una pagina + bottone export, Q3 ReportLab, Q4 fuori scope).

**v3.4.32.2** — 1 maggio 2026 notte — Patch v3.4.32.1 (timeline align + paste GUI + governance overtime + scaglioni CCNL)

Quattro fix raggruppati: (1) allineamento timeline label↔group ripristinato (rimossi min-height conflittuali); (2) paste GUI con click-to-paste + right-click "Incolla qui" + barra arancione in modalità incolla + Esc per annullare; (3) auto-approve overtime ammesso solo a manager+admin (NO producer) + notifica info agli altri manager per visibilità governance; (4) scaglioni overtime CCNL configurabili (`overtime_brackets` JSON + `ccnl_label`) — engine già pronto, UI in `/settings#hours`, compilazione preset via AI è iter successiva (capability `propose_working_hours_policy`).

**v3.4.32.1** — 1 maggio 2026 sera — Patch v3.4.32 dopo test locale (multi-risorsa, drop festivo, look timeline, temi/font)

Sei fix raggruppati: (1) override permessi su booking multi-risorsa con cascade ristretto; (2) bottoni durata `−30/−15/+15/+30`; (3) auto-approve overtime se chi estende ha permesso + 3 icone notifica nuove; (4) drop su festivo → soft block + workflow overtime invece di hard block; (5) timeline altezza riga uniforme + font label più chiari; (6) 5 temi colori nuovi + 6 varianti font.

**v3.4.32** — 1 maggio 2026 — Booking esecutivo (priorità + stato + workflow overtime + pozzo not_done)

Cantiere "booking come unità operativa". Trasformato il booking da pura intenzione di pianificazione a oggetto governabile dall'operatore: priorità (3 livelli low/normal/high) visibile per colore, ciclo di vita planned→in_progress→done|not_done con motivazione, modifica durata adattiva con cascade intra-day, workflow approvazione straordinari basato su WorkingHoursPolicy, sezione cost report dedicata + pozzo ore non maturate.

**Decisione architetturale chiarita** (memoria `project_costreport_vs_timesheet.md`): cost report = quotazioni + booking + hardcost (lente cliente/finance/fatturazione). Timesheet = HR + amministrazione (lente consulente del lavoro/buste paga). Due binari separati comunicanti solo nel planning per disponibilità risorse.

**Decisione strategica** (memoria `project_normativa_ccnl.md`): ferie/malattia → normativa italiana per ora. Straordinari → CCNL caricabili in impostazioni (Matteo cerca i CCNL applicabili al post-prod).

Sessione 1 maggio sera (commit unico): chiusa v3.4.32 dopo discussione completa di scope + 4 domande chiave (priorità a 3 livelli ✓, default normal/planned ✓, cascade intra-day con workflow overtime su sforamento ✓, pozzo come sezione del cost report progetto ✓).

## In corso

**Sessione 5 maggio — Round 7 aperto su lista feedback Matteo (12 punti).**

Lista feedback ricevuta:

**Round 7A (chiuso in alpha.16 — 4 bug puri):**
- ✅ Straordinari nella lista timbrature per singola riga + nel totale
- ✅ Filtro Tipo in "Le mie ore" funzionante (categorie breakdown invece di raw kinds)
- ✅ Ferie/malattia visibili nella tabella timbrature
- ✅ Shift+drag ROI riscritto + Alt+drag + toggle "Selezione area" toolbar

**Round 7B (chiuso in alpha.17):**
- ✅ Cost report: dropdown → searchable + filtri + lista default (pattern come `/quotes`)
- ✅ Quote ricerca + filtri simmetrici al cost report
- ✅ Cost report cliente PDF: opzione "rendiconto" (quotato/maturato/stimato + over/under) + export CSV/XLSX

**Round 7C (chiuso in alpha.18):**
- ✅ Undo/redo planning timeline (stack max 50 + bottoni toolbar persistenti + undo per `remove_assignment`)
- ✅ Bulk modify bookings (modal con shift orario + cambio stato esecuzione, endpoint `bulk-edit`)

**Round 7D (chiuso):**
- ✅ 7D.1 — AI integrazione GUI/settings (alpha.19): registry `settings_registry.py`
  + 3 tool AI generici (list/read/update). 2 schemi iniziali (working_hours,
  tenant_settings). Estendibile a tutto il software via add di nuovi schemi.
- ✅ 7D.2 — Menu assegnazioni risorse a 200 progetti (alpha.20): vista Matrice
  Risorsa × Job + filtri server-side + ricerca client-side + modal upsert cella.
  Toggle Matrice/Kanban (kanban legacy preservata).
- ✅ 7D.3 — Risorse + reparti a 500/30 (alpha.20): pagina `/team` con sidebar
  reparti drill-down + griglia card. Voce sidebar `/resources` → `/team`.

**Sessione 4 maggio chiusa — Round 1 fix post-test del 3 maggio chiuso (v3.5.0-alpha.9).** Working tree pulito dopo commit alpha.9. Round 2 e Round 3 in attesa di green-light Matteo + riapertura.

### Issue identificati nel test estensivo Matteo del 3 maggio

**Round 1 (chiuso in alpha.9)** — fix integrità + UX bloccante:
- ✅ Cost report maturato fantasma post-delete booking/assignment
- ✅ HR overtime 400 → 200+warning (sblocca pagina /hr e modal timbratura)
- ✅ Timepicker quick options estese (07→23, mezz'ora)
- ✅ openModal refresh searchable wrappers (fix dept mancante in modal risorsa)
- ✅ Pagina Accesso Negato centrata

**Round 2 — RBAC editor (chiuso in alpha.10)**:
- ✅ Editor non vede prezzi/budget in `/jobs/{id}` + tabella jobs di `/planning` + modal job-detail
- ✅ Editor non può creare booking direttamente — modal create diventa "📩 Richiedi booking" → POST `/api/booking-requests` → notifica `booking_request` a producer/manager
- ✅ Editor non può assegnare risorse a progetto/job (`POST /cost-report/api/job/{id}/assign-resource` gated)
- ✅ Override manuale `quantity_actual` rimosso dovunque (decisione: ore = booking done, sempre)

**Round 3 — UX/feature (chiuso: 9/9 in alpha.11+alpha.12)**:
- ✅ Quote editor: subtotali categoria live + nuova riga "Totale categoria al netto" sotto lo sconto (alpha.11)
- ✅ Add resource a booking esistente / job esistente → auto-assign al progetto (hook esteso a PUT booking + PUT assignment, alpha.11)
- ✅ Booking done propaga a tutte le risorse (refresh timeline su todoSetExec, alpha.11)
- ✅ Timeline highlight cross-resource su click di un booking multi-risorsa (alpha.11)
- ✅ Timeline overlay con orario corrente durante drag/resize (alpha.11)
- ✅ Timeline copy multi-risorsa (era singolo, alpha.11)
- ✅ UX `quantity_actual` lavorazione: rimosso edit completo (Matteo decisione 4 maggio, alpha.10)
- ✅ Cost report row: popup booking-detail (porting di `openLineDetail` da `job_detail.html`, alpha.12)
- ✅ Cost report: hardcost (`QuoteLine.hardcosts`) esposti nel popup detail come blocco "Hardcost (materiali / spese vive)" (alpha.12)

### Domande aperte chiuse in questa sessione

- ✅ Override manuale `quantity_actual` → Matteo: rimuovi completamente. Fatto in alpha.10.
- 🟡 Modifica nome lavorazione: oggi richiede `view_finance`. Restringere a `edit_quotes` (più stretto)? — non ancora deciso.

### Cantieri chiusi nella sessione del 3 maggio

1. ✅ **Reverse-flow v1** — job extra da booking su progetto senza quote (v3.4.51)
2. ✅ **Reverse-flow v2** — booking → QuoteLine + approvazione implicita / phantom quote (v3.4.52)
3. ✅ **Booking parla quote+lavorazione** (Job nascosto), filtro reparto risorse (v3.4.53)
4. ✅ **Project filter nel booking** + cost-line RBAC (`edit_cost_actuals`, lock `quantity_actual` per non finance) (v3.4.54)
5. ✅ **Fix sistemico integrità Quote↔Job↔Booking** — HARD-BLOCK delete con booking attivi, vista lavorazione read-only, auto-assignment Resource→Job, man-hours canonico (v3.4.55)
6. ✅ **Conferma assegnazione risorse + warning quote approved senza risorse** + 3 docs Mermaid `workflow.md`/`data-model.md`/`permissions-matrix.md` (v3.4.56)

**Sessione 3 maggio chiusa — 6 commit (v3.4.51 → v3.4.56) NON ancora pushati su origin/main** (8 commit ahead totali). Working tree pulito.

### Cantieri chiusi nella sessione

1. ✅ **Reverse-flow v1** — job extra da booking su progetto senza quote (v3.4.51)
2. ✅ **Reverse-flow v2** — booking → QuoteLine + approvazione implicita / phantom quote (v3.4.52)
3. ✅ **Booking parla quote+lavorazione** (Job nascosto), filtro reparto risorse (v3.4.53)
4. ✅ **Project filter nel booking** + cost-line RBAC (`edit_cost_actuals`, lock `quantity_actual` per non finance) (v3.4.54)
5. ✅ **Fix sistemico integrità Quote↔Job↔Booking** — HARD-BLOCK delete con booking attivi, vista lavorazione read-only, auto-assignment Resource→Job, man-hours canonico (v3.4.55)
6. ✅ **Conferma assegnazione risorse + warning quote approved senza risorse** + 3 docs Mermaid `workflow.md`/`data-model.md`/`permissions-matrix.md` (v3.4.56)

### Da testare sul Mac (priorità sessione 3 maggio)

1. **Reverse-attach quote draft/sent**: booking su progetto con quote in trattativa → modal `modal-tlb-reverse-quote` → sceglie attach_existing → quote diventa `approved` (implicit), job creato, `JobCostLine` allineata, AM riceve notifica `quote_reverse_approval`
2. **Phantom quote**: booking su progetto senza quote → modal → sceglie `create_phantom` → nuova `Quote(is_phantom=True, status=approved)` + job + JobCostLine
3. **Booking parla quote+lavorazione**: modal mostra "Quotazione" non "Job"; ricerca filtra per departments delle risorse; promote-line-to-cost-line transparent al save
4. **HARD-BLOCK delete QuoteLine**: prova a cancellare riga con booking attivo → 409 con elenco; cancella i booking, poi riprova → 204
5. **Vista lavorazione read-only**: editor/operator clicca riga in `/jobs/{id}` → vede KPI + booking + risorse, nessun bottone Modifica. Con view_finance vede bottone.
6. **Auto-assignment**: crea booking di una risorsa nuova su un job → `JobResourceAssignment` apparso (controlla in `/jobs/{id}` tab risorse); pre-save dialog conferma se ci sono missing.
7. **Man-hours**: 2 colorist × 8h booking done → JobCostLine.quantity_actual = 2 (giornate-colorist), non 1.
8. **Cost-line RBAC**: editor/operator entra in PUT cost-line → `quantity_actual` read-only badge "richiede edit_cost_actuals"; admin/manager/accounting può editare.
9. **Notifica quote_approved_no_resources**: approva quote senza assignment → admin/manager/producer ricevono notifica `severity=action_required`.
10. **Workflow docs**: apri `docs/workflow.md` su GitHub o IDE con preview Mermaid → 5 diagrammi renderizzati (state Quote, state Booking, flow forward/reverse/phantom, fonti Maturato, vincoli HARD-BLOCK).

### Da testare sul Mac (priorità)

Setup pulito con `[O] reset_business_data`:
1. Crea clienti, progetti, risorse, listino già pronto (preservato)
2. Quote → cambio progetto / duplica con progetto / nuova versione / migrate-job
3. Booking multi-risorsa con preset + sync orario
4. Booking done → cost report mostra ore maturate
5. Filtri multi (cliente/progetto/job/risorsa) sulla timeline
6. Storyboard week view
7. Pannello ⚙ look timeline (bg/font/colore testo/accent reparto)
8. Anomalie in /finance (job orfani / sforamenti / extra)
9. Le mie + dettaglio booking
10. Tab "Per progetto" (manager+)

### Riapertura

Parola chiave: **"Riprendi da v3.5.0-alpha.8 — apri con il tuo ultimo commento"**.

### Sessione 3 maggio 2026 — push completato

21 commit ahead origin/main → push eseguito su richiesta esplicita di Matteo.
Sequenze:
- Mattino: v3.4.51→v3.4.56 (reverse-flow, invarianti integrità Quote↔Job↔Booking, workflow docs Mermaid)
- Pomeriggio/sera: v3.5.0-alpha.1→alpha.8 (AI tool-use nativo Anthropic + Cestino quote+project con retention auto)

### Carry-over sessione 2 maggio (test ancora non eseguiti)

Setup pulito con `[O] reset_business_data` e batteria test descritta nelle versioni v3.4.39→v3.4.50.1 (vedi storico più sotto).

### Cantieri proposti, non avviati (backlog)

Da testare per **v3.4.40**:
- Ogni `<select>` non-multiple → click apre dropdown con input "Cerca…" + lista filtrabile. ↑↓ Enter Esc.
- Modali (es. nuova fattura, nuovo booking, nuova quote, modifica utente) con select popolati async → display deve aggiornarsi al value (auto-refresh su click `[onclick*="openModal"]` con setTimeout 80ms).
- `<input type="time">` (es. /settings#hours, modal multi-risorsa /planning) → click apre popup grid HH:MM con quick-pick.
- `<input type="datetime-local">` (es. nuova timbratura /hr) → splittato in `[date] [time]` affiancati. Il time apre il popup custom. Submit deve continuare a inviare il datetime composto.
- Nessun layout shift / regressione su select esistenti.

Da testare per **v3.4.39**:
- Migrazione `[N]` (auto al boot, opzione strumenti per fallback esplicito)
- `/quotes` lista: bottoni `📋` e `📐` accanto a "Job ✓"
- Editor: "📋 Duplica" e "📐 Versione" in topbar; sezione "Versioni" appare quando catena > 1
- Crea V2 di una quote approvata con job → vai su V2, modificala (rimuovi una riga, modifica una quantità sotto consuntivo) → "↪ Migra Job a questa versione"
- Preview deve elencare orfane con badge ⚠ (se hanno quantity_actual), sforamenti, fresh
- Conferma con `keep_as_extra` → vecchia diventa "superseded", nuova "approved", job ribindato. JobCostLine orfane diventano extra.
- Conferma con `floating_job` → job.quote_id=NULL → appare in `/finance > Anomalie > Job orfani`
- `/finance` tab "⚠ Anomalie": 3 card popolate, badge rosso sulla tab

**Sessione 1 maggio notte profonda chiusa — 17 versioni v3.4.32→v3.4.38 + push su origin/main `60b2e09..e735495`.** Working tree pulito, audit logico completo (3 round).

**Sessione 1 maggio notte chiusa.** v3.4.32→.32.2 + .33 da testare sul Mac al prossimo pull (o continua il test locale).

Da testare per **v3.4.33**:
- `/quotes`: pannello listino aperto di default quando entri nell'editor di una quote (prima nascosto)
- `/cost-report`: 8 KPI (compresi "Costo ore (booking)" e "Margine stimato")
- `/cost-report`: bottone "📄 Esporta PDF cliente" → apre PDF ReportLab con lavorazioni quote + extra + ore breakdown, niente hardcost/margine/rate
- Verifica numeri: ore nel cost report ora vengono dai Booking, NON più dai Timesheet (HR resta separato)

Da testare per **v3.4.32→.32.2** (carry-over):
- Migrazione `[L]` (solo se DB esistente) — già auto-applicata al boot
- `/planning` tab "Le mie": card interattive con bordo priorità, bottoni `−30/−15/+15/+30`, `▶ Inizia / ✓ Fatto / ✗ Non fatto`
- Booking multi-risorsa: l'operatore può estendere; cascade non spinge le altre risorse del cascade
- Drop su giorno festivo nella timeline → confirm dialog "Sarà richiesta approvazione straordinario"
- Estensione overtime: producer → sempre pending; manager/admin → auto-approved con notifica info agli altri admin/manager
- Paste GUI: Ctrl+C poi Ctrl+V → barra arancione "Modalità incolla" → click sulla timeline incolla. O right-click area vuota → "Incolla qui (N)"
- `/settings#aspect`: 9 temi colori + 6 varianti font
- `/settings#hours`: scaglioni overtime (test: prime 2h al 1.30, oltre al 1.60)

Da testare ancora dalla v3.4.31 (carry-over):
- Fix sidebar `/settings#sidebar`
- Notifica `job_deadline_approaching` (strumenti `[T]`)
- Listino laterale + drag&drop in `/quotes`
- Calendario complessivo in `/hr`
- Scheda tecnica progetto + link pubblico

Cantieri rimasti aperti (precedenti):

### A) Cost Report doppio — sospeso a v3.4.21
- ✅ v3.4.21 — Soglie overtime + moltiplicatori in `WorkingHoursPolicy`, engine `compute_overtime()`, endpoint `/hr/api/overtime`, UI settings
- 🔜 Cost report **interno** `/jobs/{id}/cost-report`: rate × (regular + overtime×mult) + hardcost + booking interni
- 🔜 Cost report **esterno cliente**: solo ore + extra, bottone "→ Genera quote v2"
- 🔜 Pagina HR riepilogo sett/mese per risorsa + export CSV

### B) RBAC + UX (chiuso v3.4.22 → v3.4.24)
- ✅ v3.4.21.1 — Auth guard + UX login + topbar utente
- ✅ v3.4.22 — RBAC base + workflow ferie + timbratura semplificata + login centrato + look timeline polish
- ✅ v3.4.23 — Permessi configurabili + pannello admin utenti/ruoli + auto-User da Resource
- ✅ v3.4.24 — Fix `escapeHtml` globale (sblocca /admin/users + /admin/roles), rimozione scelta manuale overtime, ferie/malattia in "Le mie ore" + nel conteggio ore, anteprima permessi nel modal utente

### C) Backlog feedback Matteo (in attesa)
- ⏸ **Scheda tecnica progetti + link pubblico cliente** — Matteo allegherà PDF (quello del 30/04 era erroneamente `quote_Q-LFSB-1.pdf`, una quotazione)
- ✅ ~~Dove fa staff le richieste ferie?~~ Risolto in v3.4.24: form inline in `/planning/` tab "Le mie".

Cantiere **Core Planning** (6 fasi confermate dopo analisi top vendor — Float/Runn/Resource Guru/Productive/Mosaic/Ftrack):

- ✅ E1 — v3.4.14 — Editing diretto (drag/resize/delete + PUT API + snap adattivo + conflict viz + undo + Alt=duplica)
- ✅ E2 — v3.4.15 — Click&drag crea + ghost + tooltip durata + capacity heatmap + menu contestuale Sposta/Duplica/Annulla cross-resource
- 🔜 E3 — v3.4.16 — WorkingHoursPolicy globale+override + split smart + pausa rigida + ferie/malattia bloccanti + holiday Italia auto (lib `holidays`)
- 🔜 E4 — v3.4.17 — Multi-select + modifier keys completi + saved views + conflict viz live evoluto + bulk paste + snap line
- 🔜 E5 — v3.4.18 — Booking ricorrenti + tentative bookings (legati a quote draft/sent → committed quando approved) + audit log
- 🔜 E6 — v3.4.19 — AI auto-suggest assegnazione (capability `propose_booking`)

Cancellati dalla roadmap (gold plating o ridondante con altri vendor del mercato): cursori real-time, GraphQL, full-Gantt+critical-path, review/approval workflow Ftrack-style.

Cantiere "overlay prenotato vs effettivo + adeguamento" (era v3.4.15 nel plan precedente) → riassorbito in E5/E6 dopo E3 ferie e con tentative status.

## Prossimo step concordato

> **🔖 ULTIMO COMMENTO (11 mag 2026 notte tarda) — punto di riapertura**

**Sessione 11 maggio chiusa (estesa terza fase)**: **29 commit α.66.14 → α.66.17.3
pushati su origin/main**. Audit profondo + consolidamento + R10 AI tracking
+ R6 split ai_assistant + capability registry + R7 MVP.

Terza estensione sessione (Matteo: "vai avanti e finisci se puoi. Push alla fine"):
aggiunti 2 commit oltre i 26 precedenti:
- α.66.17.2 — R6 Step 2 capability decorator registry (drift handler/types chiuso 23=23)
- α.66.17.3 — R7 MVP: deprecated POST duplicate (estrazione diag/unav/bookings rimandata)

Estensione precedente (R10+R6 Step 0+1):
- α.66.16.4 — R10 AI token tracking (modello AIUsageLog + endpoint `/ai/api/usage`)
- α.66.17.0 — R6 Step 0 estrai `ai_context.py` (ai_assistant 2339→1899)
- α.66.17.1 — R6 Step 1 estrai `ai_legacy_parser.py` (ai_assistant 1899→1785)

### Cosa è stato fatto

| Sprint | Versioni | Cosa |
|---|---|---|
| **Audit profondo** | (no commit) | 5 agenti paralleli su modelli/router/services/frontend/AI |
| **M1 Quick Wins** | α.66.14 → .14.9 | 11 quick win (modal a11y, light mode, auth fail-closed, tenant filter AI, upload security, permission gate quote, slice-lock AI, prompt caching, numbering service, soft-delete bypass, CSS extract planning) |
| **R1 Tenant scope DI** | α.66.15.0 → .15.2 | tenant_id ai 4 modelli orfani + app/context.py DI helper + tenant filter su query critiche (quotes/jobs/cost-report/dam) |
| **R2 Soft-delete framework** | α.66.15.3 → .15.4 | _SOFT_DELETE_MODELS esteso (5 modelli) + helper is_unique_or_deleted_aware + fix Project.code create |
| **R3 Permission gate sweep** | α.66.16.0 | 27 mutator senza gate protetti (76/76 totale 100%): finance/pricelist/resources/dam/ai/planning |
| **R4 Booking mutation gate** | α.66.16.1 → .16.3 | app/services/booking_mutate.py + AI handlers + planning router migrati. 7/7 call site SLICE_LOCK centralizzati. Pattern systemico O chiuso |
| **R10 AI token tracking** | α.66.16.4 | Modello AIUsageLog + tabella prezzi 14 modelli + endpoint /ai/api/usage. Hook in ClaudeProvider + ai_loop. Cost analytics user/model/day |
| **R6 Split ai_assistant.py** | α.66.17.0 → .17.1 | Estratto ai_context.py (516 righe) + ai_legacy_parser.py (156 righe). ai_assistant 2287→1785 righe (-23%). Pattern G iniziato |
| **R6.2 Capability registry** | α.66.17.2 | Decorator @ai_capability + ai_capability_registry.py. _ACTION_HANDLERS + VALID_ACTION_TYPES derivati auto. Drift 23 vs 13 chiuso. Pattern N audit chiuso |
| **R7 MVP deprecate dup** | α.66.17.3 | POST /planning/api/clients deprecated (duplicato). Estrazione diag/unav/bookings rinviata a R7.x dedicati (helper condivisi richiedono attenzione) |

### Audit chiuso

12 problemi HIGH dell'audit + 6 dei 7 pattern systemici (A tenant scope,
B soft-delete, C numbering, D permission gate, F single-mutation gate
per Booking, O slice-lock unificato, parte di G file giganti).

### Backlog rimanente (sprint successivi)

- **R5** Split planning.html partial Jinja + JS moduli (PR2/PR3 audit)
- **R6.3** Split capability handlers (`_h_propose_*`) in
  `ai_capabilities/` package per dominio (clients/projects/quotes/
  pricelist/bookings/billing/settings). Il decorator registry α.66.17.2
  rende il refactor mechanical: importi i moduli e il registry si popola.
- **R7.x** Split planning.py 4265 righe (estrazione diag, unavailabilities,
  bookings) — richiede attenzione su helper condivisi e variabili globali
- **R8** Float→Decimal soldi (EUR `Decimal('0.01')` ROUND_HALF_EVEN)
- **R9** Datetime tz-aware (UTC ovunque + ZoneInfo display)
- **R10.2** Hook usage_* anche su OpenAI/Gemini/Ollama chat_with_tools;
  rate limit per-user; UI dashboard `/settings#ai-usage`
- **R4 follow-up**: PUT booking + bulk-edit usano già `_assert_no_blocking_slice`
  che è migrato internamente, ma il call site potrebbe usare anche
  `assert_no_overlap_after` per uniformare conflict-check inline

### Cosa fa Matteo quando riapre domani

1. **Pull**: `git pull origin main` — 25 commit pronti (chunk α.66.14 → α.66.17.1)
2. **Restart server** — ALTER TABLE auto al boot:
   - `tenant_id` su 4 nuovi modelli (Quote/Job/JobCostLine/Asset)
   - `ai_usage_logs` tabella nuova (creata da `create_tables()`)
3. **Hard-refresh browser** per cache-buster `?v=3.5.0-alpha.66.14` su global.js
4. **Test smoke focus**:
   - **Modal a11y**: apri qualsiasi modal → Tab cicla solo dentro,
     Esc chiude solo top, focus restored al close
   - **Planning**: light mode auto-on se >80 booking; vis-timeline gira
   - **AI copilot**: prova il prompt cache (turno 2 dovrebbe essere
     più veloce; logger Anthropic `[anthropic cache] read=N create=N`
     in console server) → poi `GET /ai/api/usage?period_days=1` ritorna
     totals con cost_usd e cache_hit_ratio
   - **Mutator quote/finance/pricelist/resources con utente non-admin**:
     viewer/operator deve vedere 403 sui mutator
   - **AI move/resize via copilot** dentro slice billed → blocked con
     messaggio chiaro
5. **Verifica** che le 76/76 protezioni mutator non rompano flussi reali
6. **Riportare bug** trovati → faccio hotfix prima di proseguire R5+

### Riapertura

Parola chiave: **"Riprendi da v3.5.0-alpha.66.17.3 — apri con il tuo
ultimo commento"**.

Audit + M1+R1+R2+R3+R4 + R6 Step 0-1 + R10 chiusi e pushati. Prossimo:
- **R5** split planning.html (basso rischio, alto valore manutenzione)
- **R6.2+** split capability handlers in `ai_capabilities/` (decorator registry)
- **R7** split planning.py 4265 righe
- **R8** Float→Decimal soldi
- **R9** Datetime tz-aware
- **R10.2** OpenAI/Gemini/Ollama hook usage + rate limit + UI dashboard
- Oppure **feature backlog α.66.14+**: kanban deliverable, copilot QC,
  AI cost derivation

---

**Sessione 10 maggio (storico precedente)**: 8 commit α.66.6→α.66.13 **pushati su origin/main**.
Cantiere "Listino & Deliverable" sostanziale:
- Snapshot listino persistenti (UI in `/pricelist` 📦 Snapshot)
- Listino lean 43 voci con descrizione modulare (preset built-in al boot)
- Modelli `JobDeliverable` + `PhysicalAsset` (separati, ortogonali archive/delivered)
- Cost-rate Resource (employee/freelance/studio/external) con UI live preview
- Cost report **split** cliente vs interno (cliente non vede ore deliverable)
- Pagina `/physical-assets` CRUD completa
- Branding aziendale completo (tagline + brand_color + powered_by toggle)

**Quando riapri domani**:

1. **Pull** `git pull origin main` (8 commit attesi).
2. **Restart server** — ALTER TABLE auto al boot:
   - `pricelist_snapshots` nuova
   - `job_deliverables`, `physical_assets` nuove
   - `bookings.job_deliverable_id`
   - `assets +7 col` (job_deliverable_id, is_internal_archive, is_delivered_external, delivered_at/to/method/tracking)
   - `resources +7 col` (cost_type, monthly_gross_salary, annual_bonus_months, cost_multiplier_oneri, annual_working_hours, freelance_hourly_cost, studio_hourly_cost)
   - `tenants +4 col` (tagline, brand_color, show_powered_by, document_header)
3. **Test estensivo sul Mac** — DB era vuoto, ricostruisci dati da zero (suggerito `seed_demo` per partire con il listino lean 43 voci):

   ### Flusso end-to-end consigliato
   - **A. Listino**: `/pricelist` → 📦 Snapshot → 🎁 Preset built-in → vedi 2 preset (legacy 79 + lean 43). Carica lean come snapshot, poi tab Lista → Ripristina (Replace, auto-backup creato).
   - **B. Branding**: `/settings#company` → blocco "🎨 Branding documenti" → tagline + colore primario (color picker) + intestazione + checkbox powered_by → Salva. Carica logo (50x50 .png).
   - **C. Cost-rate Resource**: `/resources` → ✏️ una risorsa → "💰 Costo interno" → Dipendente €2800/mese → preview live €27.51/h. Salva → riapri → valori persistiti.
   - **D. Asset fisici**: sidebar → "Asset Fisici" → + nuovo LTO 12TB archivio interno (condizione "verified", location "Cassaforte"). Poi nuovo HDD consegnato a cliente (courier + tracking).
   - **E. Deliverable**: `/jobs/{id}` → blocco "Consegne" → + nuovo deliverable → seleziona preset "ISDCF DCP (cinema)" → spec tecniche (resolution 2K, audio 51, lang it, territory IT) → vedi live preview file_naming = `MareNostrum_FTR-F_IT-it_51_2K_RAI_20260612_TPRBerlin_IOP_OV` → quantity=3 → 3 deliverable separati con suffix (1/3) (2/3) (3/3).
   - **F. Booking attribuiti**: crea booking 4h attribuito a deliverable DCP + booking 8h attribuito a JCL Color grading day senza deliverable → torna in `/jobs/{id}` → card KPI viola "Hardcost ore deliverable INTERNO" mostra €110.04 (4h × €27.51) + 1 deliverable.
   - **G. PDF cliente**: `/cost-report/{job}` → 📄 Esporta PDF cliente → vedi:
     - Header con logo + tagline + titolo "RENDICONTAZIONE" nel brand_color scelto
     - Document header opzionale sotto la HR
     - "Riepilogo ore lavorate" mostra **solo 8h** (no 4h DCP — cliente non vede)
     - Footer **senza** "Generato con MediaFlow" se hai disattivato powered_by
   - **H. PDF quote**: apri una quote → PDF → header con logo (3 colonne se presente) + tagline + titolo "QUOTAZIONE" nel brand_color.
   - **I. PDF fattura**: emetti fattura → PDF → footer toggleable "Generato con MediaFlow".

4. **Riporta cosa funziona / cosa rotto**. Se trovi bug, faccio hotfix prima di proseguire con α.66.14+.

### α.66.14+ rinviati (dopo green-light test)

- **Kanban deliverable** in `/jobs/{id}`: drag tra colonne stato (planned → in_production → file_attached → qc_passed → delivered → accepted) con SortableJS. Edit modal completo con bridge DAM (link asset digital o physical).
- **Tool generazione nomi file completo**: regole, validazione conflitti, batch rename, preset custom salvabili dall'utente. Oggi solo 9 preset built-in.
- **Copilot QC**: nuova capability `propose_qc_check` con ffprobe + LLM contro `spec_json` del deliverable. Verifica res/framerate/audio/durata/codec automaticamente.
- **Cost report split UI completa**: oggi backend espone i campi internal (`deliverable_hardcost_internal`, `unit_is_time_based` per riga). Manca colonna dedicata in tabella `/cost-report` + filtro "Solo voci time" / "Solo voci deliverable".
- **AI derivazione costi amministrativi** (post α.66.10): capability `propose_resource_cost_update` legge visura/bilancio per proporre cost_rate aggiornati.
- **Edit modal deliverable completo**: oggi solo create. Manca edit (cambio status, link asset, QC report viewer, breakdown hardcost per risorsa).

### Riapertura

Parola chiave: **"Riprendi da v3.5.0-alpha.66.13 — apri con il tuo ultimo commento"**.

---

**Sessione 3 maggio (storico)**: chiusi tutti gli invarianti d'integrità (v3.4.55) + i 2 TODO + workflow docs (v3.4.56). 8 commit ahead di origin/main.

Le opzioni naturali per la prossima sessione, in ordine di valore:

1. **Test estensivo sul Mac** sulla batteria sopra elencata (sessione 3 maggio + carry-over sessione 2 maggio). Se Matteo trova bug, hotfix.
2. **Push su origin/main** dopo green light dei test (criterio: push solo a major bump per memoria, ma 8 commit con cambio strutturale può giustificare un v3.5.0 se i test passano).
3. **Cantieri ancora rinviati** (in ordine di backlog):
   - Cost report doppio (interno con rate × ore + hardcost; esterno cliente con solo ore + extra + bottone "→ Genera quote v2")
   - Overlay "prenotato vs effettivo" (booking vs TimePunch) + report delta producer
   - E5 booking ricorrenti + tentative bookings (legati a quote draft/sent → committed quando approved) + audit log
   - E6 capability AI `propose_booking` (skill match + availability + storico)
   - Multi-valuta con cambio automatico ECB
   - Cestino per-tenant con retention configurabile

**Vecchio backlog (legacy):**
- ~~E5 v3.4.19~~:
- Booking ricorrenti minimi: every weekday, every Mon, every Tue, ecc.
- Tentative bookings (`is_tentative` flag, viz tratteggiata) legati a quote draft/sent → committed quando approved
- Audit log su modifiche booking (estende pattern AIAction)

**E6 — v3.4.20 — AI auto-suggest assegnazione**:
- Capability `propose_booking` nel copilot
- Skill match + availability + storico

**Backlog UI**:
- Pagina `/settings#working-hours` con form policy editabile (mattina, pomeriggio, giorni, paese festività)
- Override policy per-risorsa nella pagina `/resources/{id}`
- Form ferie/malattia in `/resources/{id}` (oggi solo via API)

**Vecchio E4 — v3.4.18 — Polish + multi-select**:
- Modello `WorkingHoursPolicy` (globale + per-risorsa override): start_time, end_time, lunch_start, lunch_end, working_days
- Engine `split_booking_smart(start, end, policy) → list[Slot]` che ritaglia weekend, orario non-lavorativo, pausa pranzo rigida (es. 13-14)
- Modello `ResourceUnavailability` evoluto: ferie/malattia come fasce bloccanti, drag/drop su quelle = HARD block (popup, no warning)
- Holiday calendar Italia predefinito (libreria Python `holidays.IT()`) + custom holidays
- Pagina `/settings#working-hours` per configurare policy
- Toggle "Smart split" nel modal create (default ON), preview "creerà N booking"
- Migration script idempotente
Verifiche sul Mac sospese (cumulative):
- v3.4.5 modal "Aggiungi voce"
- v3.4.6 booking multi-tenant
- v3.4.7 sezione HR + calendario integrato
- v3.4.8 flusso Quote → Job auto
- v3.4.8.1 hotfix STATUS_LABEL e FullCalendar CSS
- v3.4.9 dettaglio job
- v3.4.9.1 hotfix finance budget
- v3.4.10 aggregazione ore per lavorazione (colonne Pian./Lavor. in `/jobs/{id}`)
- v3.4.11 hub `/planning/` con 5 viste (Tabella, Calendario, Trimestre, Agenda, Le mie) + 9 filtri trasversali
- v3.4.12 Resource Timeline vis-timeline (tab #6, zoom Giorno/Sett/Mese/Trim, raggruppata per reparto, riusa filtri)
- v3.4.13 UX cleanup: tasto Oggi parte da oggi, selettore data Vai-a, label settimana/mese, zebra rows, filtri collassabili, vista Trimestre rimossa, voce sidebar Calendario rimossa
- v3.4.13.1 hotfix: filtri collassabili stabili (flex+min-width:0), click su timeline → modal nuovo booking pre-popolato (risorsa+ora+job+lavorazione)
- v3.4.14 E1 editing diretto: drag/resize/delete, snap adattivo 15/30/60min, conflict border rosso live, undo toast 5s, Alt+drag duplica, doppio click vuoto = nuovo
- v3.4.15 E2: click&drag crea con ghost+durata, capacity heatmap %/giorno, menu contestuale Sposta/Duplica/Annulla cross-resource, pan disabilitato (scroll/bottoni)
- v3.4.15.1 hotfix: drag pan ripristinato, Shift+drag = nuovo booking, right-click menu su item (Modifica/Duplica/Sposta/Elimina) e vuoto, heatmap robusto (update foglie)
- Test E2E AI search-first (v3.4.4)

Per testare #5 servono prompt reali al copilot con provider AI attivo (Sonnet 4.6 consigliato, ma anche Ollama 8b dovrebbe funzionare grazie a SEARCH-FIRST esplicito nel system prompt).

Casi suggeriti:
1. **1 match chiaro** → `"aggiungi a Q-2026-001 due giorni di Color HDR"` deve produrre `propose_quote_line` con `price_item_id` e prezzo ereditato dal listino
2. **Match multipli** → `"aggiungi a Q-2026-001 del color"` deve elencare in markdown le 3+ voci color (SDR/HDR/dailies) e chiedere quale
3. **Voce esplicitamente nuova** → `"aggiungi a Q-2026-001 una nuova voce Foley editing, listino 350/giorno categoria Audio"` deve produrre `propose_new_item_and_line`
4. **0 match con domanda** → `"aggiungi a Q-2026-001 un Beauty fix"` (voce inesistente) deve elencare in markdown opzioni (a) voce libera vs (b) scenario C

Dopo conferma test sul Mac, passare a **#4 server-side abort**.

## Backlog (in ordine concordato)

**Cantiere Calendario / Pianificazione (chiuso parzialmente)**:
- ✅ **D** Booking multi-tenant (v3.4.6)
- ✅ **Timbrature/idle Opzione 2** — sezione HR `/hr` con `TimePunch` separato + integrazione calendario (v3.4.7)
- 🔜 **A** UX calendario (editable, drag/resize, click→modal edit/cancel, banded unavailability, filtro server-side) — rinviato dopo il re-design Quote→Job
- 🔜 **B** UI `/resources/{id}` tab Disponibilità (CRUD `ResourceUnavailability`)
- 🔜 **C** Riconciliare Assignment kanban ↔ Booking (potrebbe sparire del tutto in favore del flusso quote→job→booking)
- 🔜 **E** Capability AI `propose_booking` + `propose_time_punch`
- 🔜 **F** Gantt per job

**Cantiere Quote → Job → Cost Report (sospeso)**:
- ✅ **v3.4.8** Auto-promote Quote → Job + bug fix planning + rimosso job manuale
- ✅ **v3.4.8.1** Hotfix STATUS_LABEL + FullCalendar CSS
- ✅ **v3.4.9** Pagina `/jobs/{id}` con lavorazioni first-class
- ✅ **v3.4.9.1** Hotfix finance.budget → finance.budget_quoted
- ✅ **v3.4.10** Booking legati a lavorazione + booking interni
- 🔜 **v3.4.13** Ferie/malattia come fasce bloccanti nel calendario
- 🔜 **v3.4.14** Cost report interno arricchito (rate × ore + hardcost + booking interni)
- 🔜 **v3.4.15** Cost report esterno cliente (solo ore + extra, bottone "→ Genera quote v2")
- 🔜 **UX calendario** (modal "+ Booking" aggiornato, redesign visuale)

**Cantiere Visualizzazioni Pianificazione (in corso)**:
- ✅ **v3.4.11** Hub `/planning/` 5 viste + 9 filtri trasversali (Tabella, Calendario, Trimestre, Agenda, Le mie)
- ✅ **v3.4.12** Resource Timeline (vis-timeline, righe verticali risorse raggruppate per reparto, zoom giorno/sett/mese/trim)
- ✅ **v3.4.13** UX cleanup: Oggi=da-oggi, Vai-a, label sett/mese, zebra rows, filtri collassabili, drop Trimestre + voce sidebar Calendario
- ✅ **v3.4.13.1** Hotfix filtri (flex+min-width:0) + click vuoto timeline → modal nuovo booking pre-popolato
- ✅ **v3.4.14** E1: editing diretto timeline (drag/resize/delete + PUT/restore API + snap 15/30/60min adattivo + conflict viz live + undo toast 5s + Alt+drag duplica + doubleClick vuoto = nuovo)
- ✅ **v3.4.15** E2: click&drag crea + ghost rect + tooltip durata + capacity heatmap %/giorno (live update con zoom) + menu contestuale Sposta/Duplica/Annulla cross-resource
- ✅ **v3.4.15.1** Hotfix: drag pan ripristinato (era preferenza utente) → Shift+drag per nuovo. Right-click menu su item e vuoto. Heatmap update solo foglie (preserva nesting).
- 🔜 **v3.4.16** E3: WorkingHoursPolicy + split smart + pausa pranzo rigida + ferie hard-block + holiday Italia auto
- 🔜 **v3.4.15** Prenotato vs effettivo overlay + adeguamento + report delta producer
- 🔜 **post-15** Kanban per stato job (SortableJS) + Gantt per job (`/jobs/{id}`, Frappe Gantt)

**Sezione HR — sviluppo successivo**:
- Aggregazioni avanzate (ore per progetto/risorsa/mese, export CSV/PDF cedolino)
- Auto-timbratura via topbar per chi è loggato ("🟢 Inizio turno" / "🔴 Fine turno")
- Orari standard per tipo risorsa (full-time / part-time / freelance) per calcolo straordinari automatici

**Backlog "altri"**:
1. **#4 server-side** Abort lato server per Ollama/Claude (oggi è solo client-side `AbortController`). Ollama supporta `client.abort()` best-effort. Anthropic SDK richiede una `Cancelable` request.
2. **#1** Multi-valuta con cambio automatico ECB. Migrazione DB (`Quote.currency`, `exchange_rate`, `currency_locked`, `exchange_rate_date`) + servizio `app/services/fx.py` con cache JSON + UI dropdown valuta + capability AI `propose_quote_currency`. Conversione solo a display/PDF/export, EUR canonico in DB.
3. **F2** Gestione utenti + RBAC configurabile + link Resource→User con email password temp.
4. **F3** Cestino per-tenant con retention configurabile.

## Decisioni prese

- **Multi-valuta**: API ECB exchangerate.host (gratis, no key). EUR canonico in DB, conversione solo display/export.
- **Search-first AI**: priorità a match listino esistente. Fallback a scenario "C" (crea voce + linea in singola transazione) solo se utente conferma "non trovato".
- **Stop thinking**: tentare anche server-side abort (Matteo: "per evitare possibile sovraccarico richieste").
- **Esporta da copilot (#2 originale)**: skipped per ora.

## Bug aperti

- ✅ **#6 LLM matching listino** risolto in v3.4.4 (voci listino nel context AI + REGOLA SEARCH-FIRST nel system prompt). Da verificare con test E2E sul Mac.
- ✅ ~~**Modal multi-risorsa: leggibilità >5 risorse**~~ risolto in v3.4.20.2 (scroll interno + badge numerazione + counter).

## Procedura riavvio (se la sessione muore)

1. Apri nuova istanza Claude Code nella cartella `mediaflow_fase1bis`.
2. Comincia con: **"leggi docs/STATO.md e procedi"**.
3. Se git è inizializzato, Claude usa `git status`/`git diff` per vedere cosa è non committato.
4. Per recuperare il filo verbatim della sessione precedente: `/recall:session <session-id>`. Il session-id si trova:
   - subito quando esci da `claude` (lo stampa)
   - oppure `claude --sessions` da terminale esterno
   - oppure il `.jsonl` più recente in `~/.claude/projects/C--Users-frico-OneDrive-Documents-Claude-Projects-mediaflow-fase1bis/`

---

*Ultimo aggiornamento: 10 maggio 2026 sera — chiusa sessione "Listino & Deliverable": 8 commit α.66.6→α.66.13 push completato a origin/main (autorizzato da Matteo nonostante alpha). DB di Matteo era completamente vuoto a inizio sessione. Test estensivo end-to-end pianificato per domani 11 maggio. Riapertura: "Riprendi da v3.5.0-alpha.66.13 — apri con il tuo ultimo commento" (sezione "Prossimo step concordato" sopra).*

*Ultimo aggiornamento precedente: 3 maggio 2026 — chiusa v3.4.56 (conferma assegnazione + warning quote-no-resources + 3 docs Mermaid). Sessione 3 maggio: 6 commit (v3.4.51→v3.4.56).*

**v3.4.55+v3.4.56**: chiusi 5 invarianti sistemici (eliminazione HARD-BLOCK con booking attivi, vista lavorazione read-only, auto-assignment Resource→Job, man-hours canonico, Job nascosto in booking) + 2 TODO (pre-save confirm risorse non assegnate, notifica `quote_approved_no_resources`). Aggiunti `app/services/resource_assignment_sync.py` + 3 docs Mermaid in `docs/` (workflow / data-model / permissions-matrix). Niente migrazione DB.

**v3.4.51→v3.4.54**: cantiere reverse-flow (job extra da booking su progetto senza quote → reverse v2 con QuoteLine + approvazione implicita / phantom quote → booking parla quote+lavorazione con Job nascosto → project filter + cost-line RBAC con permesso `edit_cost_actuals`).

---

*Versione precedente: 1 maggio 2026 sera — chiusa v3.4.32 (Booking esecutivo). 37 commit ahead origin/main. Push da concordare.

**v3.4.32**: 5 colonne nuove su `bookings` (priority/execution_status/not_done_reason/count_in_costs/overtime_status/original_end_datetime) + 3 NotificationKind nuovi (`booking_status_changed`, `booking_overtime_pending`, `booking_overtime_resolved`) + permesso `approve_overtime` su admin/manager/producer. Servizi nuovi `app/services/booking_cost.py` (engine costo per fascia oraria) + `app/services/booking_cascade.py` (cascade intra-day + split overtime giorno successivo). 6 endpoint nuovi su `/planning/api/`: priority, execution, extend, overtime, count-in-costs, my-bookings. 2 endpoint nuovi su `/cost-report/api/job/{id}/`: booking-summary, not-done-pool/{bid}/discard. UI: `/planning` "Le mie" card interattive (bordo priorità, drag handle ±, bottoni stato, modal motivazione), Dashboard "I miei booking di oggi" + colonne stato in tabella generica, Cost report sezione "Ore booking per fascia" + "Pozzo ore non maturate".

**Distinzione architetturale fissata in memoria**: Cost report (quote+booking+hardcost) ≠ Timesheet (HR/buste paga). Due binari separati. Il vecchio cost_report.py basato su Timesheet resta come legacy, conviverà col nuovo finché si farà rifacimento completo.

---

*Versione precedente: 30 aprile 2026 notte tarda — sessione maratona 12 commit (v3.4.21→v3.4.27). **Push eseguito**: tutto su origin/main su richiesta esplicita di Matteo. Aggiunto sistema notifiche generico (cantiere riusabile per booking_conflict, quote_status_changed, job_deadline_approaching, ecc.).

**v3.4.27** (ultimo): modello Notification + servizio notifications.py + router /notifications/api/* + 3 hook ferie (create pending → manager, approve/reject → richiedente) + UI campanella topbar con badge + drawer laterale + polling 30s + card "Richieste in attesa" in /hr/. Pattern una-row-per-destinatario. NotificationKind estendibile (4 valori riservati per cantieri futuri).

**Direttiva strategica Matteo (memorizzata)**: sempre approccio generico riusabile, mai tappare buchi singoli. Esplorare in-depth conseguenze. Proposte ampie. Domande quando servono.

---

*Versione precedente: 30 aprile 2026 notte — riapertura post-test sul Mac, chiuso v3.4.24 con i 4 punti emersi (3 dei quali collassati su un singolo bug `escapeHtml` non globale). 27 commit ahead origin/main.

**v3.4.24**: (1) `escapeHtml` spostato in `global.js` → /admin/users e /admin/roles tornano funzionanti, l'auto-User da Resource era già OK ma sembrava rotto a causa del crash render lista; (2) modal timbratura senza scelta manuale "straordinario" (calcolo deterministico via policy); (3) "Le mie ore" planning ora ha card riepilogo ore (regolari+straordinari+notturne+ferie+malattia+totale) + form richiesta ferie/malattia + lista delle proprie con stato; `/hr/api/overtime` esteso con campi `unavailability` e `grand_total_hours` per la rendicontazione amministrativa; nuovo endpoint `/planning/api/my-unavailabilities`; (4) anteprima badge permessi sotto dropdown ruolo nel modal `/admin/users`.

---

*Versione precedente: 30 aprile 2026 sera — sessione lunghissima 5 commit (v3.4.21 → v3.4.21.1 → v3.4.22 → v3.4.23). 26 commit ahead origin/main. Aperto cantiere Cost Report (overtime engine), poi pivot su feedback Matteo → RBAC pesante. v3.4.22: ruolo producer + service rbac + sidebar conditional + auth guard blacklist + scope HR/planning + workflow approvazione ferie + timbratura semplificata (no job per staff) + overlay timbrature timeline + bug fix booking modal + login centrato + look timeline polish. v3.4.23: sistema permessi configurabili (modello Role + 23 permessi granulari + 6 preset built-in admin/manager/producer/accounting/operator/viewer), pannello /admin/users e /admin/roles con matrix permessi, auto-User da Resource personale, fix bug /hr/ 500 + drag inerziale timeline + nuovo progetto staff. Migrazioni nuove [I][J] in strumenti. Working tree pulito. Prossima sessione: testare RBAC + permessi sul Mac, poi proseguire cost report O scheda tecnica progetti (manca doc).*
