# Client Email — Sotto-fase 1: `/mail` webmail standalone — Design

> Data: 2026-07-07. Programma "Client email" (Google), due vie, decomposto in sotto-fasi.
> Questa spec copre **solo la Sotto-fase 1**: client webmail standalone (lettura + invio), senza integrazione CRM.

## Contesto e decomposizione

Matteo vuole un "client email" completo integrato in Claqo: leggere e inviare email dei clienti, con l'AI che estrae contenuto (evoluzione dell'incolla-email di Acquisizioni Fase 2). Feature ampia → decomposta:

- **Sotto-fase 1 (questa spec)** — Pagina `/mail`: webmail standalone (leggi + invia + cerca + compose), sopra le fondamenta Gmail (OAuth + service layer). Nessuna integrazione CRM.
- **Sotto-fase 2** — Integrazione CRM: tab Email nel detail cliente/trattativa, pin thread (`EmailLink`, pattern `DocumentLink` di Fase D), bottone "Estrai con AI" (riusa estrazione Fase 2 → `propose_activity/contact/update_client`), log come `Activity`, anteprima corpo inline.
- **Sotto-fase 3** — Auto-flow: auto-associazione in ingresso per indirizzo, threading, AI propone next-action senza pin manuale, notifiche.

Ogni sotto-fase = spec → plan → implementazione a sé (come A/B/C/D calendario).

## Decisioni prese (brainstorming)

- **Scope Gmail**: `gmail.readonly` + `gmail.compose`. `compose` copre bozze + invio (non serve `gmail.send` separato). **Opt-in**: connessione Gmail separata e spenta di default in `/settings` (come la card Drive di Fase A/D). Restricted scopes Google → per uso interno/test users OK; verifica app necessaria solo se pubblicata.
- **Segna-letto/archivia/elimina/etichetta** (richiedono `gmail.modify`, più invasivo) **fuori da Fase 1**. Fase 1 gira con soli read+compose.
- **Modello dati**: `/mail` è un **proxy stateless** verso Gmail. Nessuna tabella nuova, nessuna migrazione. Lo stato (thread, bozze, label) vive su Gmail.
- **Accesso**: ogni utente vede la PROPRIA casella (personale). Il contenuto email non è tenant-scoped né condiviso tra utenti dello stesso tenant.
- **Provider**: solo Google in questa fase (Microsoft/IMAP fuori scope, coerente con card "Prossimamente" di Fase A).

## Architettura

Riusa il pattern dei layer HTTP isolati di Fase A/C/D (`oauth_providers.py`, `google_calendar.py`, `google_drive.py`).

### Service `app/services/gmail.py`
- Layer HTTP isolato via `urllib.request`, unico `_gmail_request(method, url, token, body=None, params=None) -> dict` = punto di mock nei test (come `_drive_request`/`_google_request`).
- Token via `get_valid_access_token(db, user_id, "google")` (auto-refresh, da `oauth_providers`).
- API Gmail v1 REST base `https://gmail.googleapis.com/gmail/v1/users/me`.
- Funzioni:
  - `list_threads(db, user_id, *, query=None, label_ids=None, page_token=None, max_results=25) -> dict` → `{threads:[{id, snippet, ...}], next_page_token}`.
  - `get_thread(db, user_id, thread_id) -> Optional[dict]` → thread con messaggi normalizzati: per messaggio `{id, from, to, cc, subject, date, snippet, body_html, body_text, attachments:[{id, filename, mime_type, size}]}`. Estrae/decodifica le parti MIME (base64url), preferisce `text/html`, fallback `text/plain`.
  - `send_message(db, user_id, *, to, subject, body_html, cc=None, bcc=None, in_reply_to=None, thread_id=None, attachments=None) -> dict` → costruisce MIME (email.message.EmailMessage stdlib), base64url, POST `/messages/send` (o `/messages/send` con `threadId` per reply-in-thread + header `In-Reply-To`/`References`).
  - `save_draft(...) / list_drafts(...) / get_draft(...) / delete_draft(...)` → drafts API.
  - `list_labels(db, user_id) -> list[dict]` → label di sistema + utente (per la nav).
  - `get_attachment(db, user_id, message_id, attachment_id) -> Optional[dict]` → `{data(bytes), ...}` (base64url decodificato) per il download.
- **Best-effort**: token assente / 401 / 403 / rete → ritorno vuoto/`None`, mai eccezione propagata al render (pattern Fase C/D). Log warning senza token.

### Router `app/routers/mail.py`
- `CURRENT_TENANT` non rilevante (contenuto per-utente, non tenant-scoped). Auth via `current_user(request)` (401 se assente).
- Endpoint (JSON per le API di lettura; Form per le scritture, coerente col progetto):
  - `GET /mail` → pagina HTML (`mail.html`).
  - `GET /mail/api/threads?label&q&page_token` → lista thread + `next_page_token`.
  - `GET /mail/api/thread/{thread_id}` → thread normalizzato con messaggi.
  - `GET /mail/api/labels` → label per la nav.
  - `POST /mail/api/send` (Form + eventuali file multipart) → invia (nuovo/reply/reply-all/forward via campi `thread_id`,`in_reply_to`,`to`,`cc`,`bcc`,`subject`,`body`).
  - `POST /mail/api/draft` / `GET /mail/api/drafts` / `DELETE /mail/api/draft/{id}` → bozze.
  - `GET /mail/api/attachment/{message_id}/{attachment_id}` → StreamingResponse/Response con `Content-Disposition: attachment` + mime.
  - `GET /mail/api/status` → `{connected: bool}` (Google connesso + scope gmail presente) per degrado grazioso UI.
- Registrazione in `app/main.py` (`include_router`) vicino a `documents_router`.

### Frontend `app/templates/pages/mail.html` + `app/static/js/mail.js`
- Layout Gmail-like a 3 pannelli: **nav label** (Inbox/Inviati/Bozze/+ label utente) | **lista thread** (mittente, oggetto, snippet, data; load-more via `next_page_token`) | **pannello lettura** (conversazione: messaggi del thread, header, corpo).
- **Compose modal**: Nuovo / Rispondi / Rispondi a tutti / Inoltra. Campi to/cc/bcc/oggetto/corpo + allega file. Bottoni Invia / Salva bozza. Precompila destinatari/oggetto/quote-thread per reply/forward.
- Ricerca: input query → passthrough a `q` (sintassi Gmail).
- Helper globali (`api`, `escapeHtml`, `toast`, `mfT`) da `global.js`/`i18n.js`, non ridefiniti. No `JSON.stringify` in onclick → `data-*`. Cache-buster `?v={app_version}` sui JS nuovi.
- i18n 5 lingue (`it/en/fr/de/es`) chiavi `mail.*` + `data-i18n`, stesso commit.
- **Voce menu** sidebar: "Email" (sezione Records o nuova). Visibile solo se utente Google connesso con scope gmail (via `/mail/api/status` o flag server-side); altrimenti la pagina mostra CTA "Collega Gmail in Impostazioni".

### Impostazioni `/settings`
- Estende la card Google (Fase A): aggiunge la richiesta scope Gmail come **connessione/opt-in separata** (badge scope, toggle o bottone "Abilita email"). Spenta di default. Revocabile. Riusa il flusso OAuth esistente (`make_oauth_state`/callback), aggiungendo gli scope gmail alla richiesta quando l'utente opt-in.

## Sicurezza

- **Rendering corpo HTML** = principale superficie XSS. Il corpo va reso in **iframe sandboxed** (`sandbox=""` senza `allow-scripts`) via `srcdoc`, con CSP restrittiva. Nessuno script dell'email eseguito.
- **Immagini remote bloccate di default** (anti tracking-pixel/privacy) con toggle esplicito "Mostra immagini" per messaggio.
- **Invio**: conferma esplicita prima dell'invio (no invio accidentale). `gmail.compose` invia solo dall'account autenticato dell'utente.
- **Token**: mai il refresh token verso il client; le API server-side usano `get_valid_access_token`. Nessun token nei log.
- **Link nel corpo**: aperti con `rel="noopener noreferrer"` (l'iframe sandboxed già isola).
- **Allegati**: `Content-Disposition: attachment` (mai inline-render di tipi arbitrari); limite dimensione in invio.

## Error handling / degrado grazioso

- Google non connesso o scope gmail assente → pagina `/mail` mostra CTA "Collega Gmail", nessun errore. `/mail/api/status` guida la UI.
- Chiamata Gmail fallita (401/403/rete) → lista/thread vuoti + toast, mai 500 (best-effort come Fase C/D).
- Invio fallito → toast errore, la bozza/compose resta aperta (nessuna perdita del testo).

## Testing

- `tests/test_gmail_service.py` — parse/normalizzazione MIME (html/text/attachments, base64url), costruzione MIME invio (reply headers `In-Reply-To`/`References`, `threadId`), best-effort su token assente/403 (mock `_gmail_request`).
- `tests/test_mail_api.py` — endpoint threads/thread/send/draft/labels/attachment/status con `_gmail_request` mockato + auth override (pattern fixture di `test_documents_api.py`: monkeypatch su `app.routers.mail.current_user`). Casi: non connesso → status `connected:false`; send costruisce MIME atteso; attachment stream mime/nome.
- `tests/test_mail_page.py` — `mail.html` contiene i pannelli + `mail.js`; `mail.js` definisce le funzioni globali; i18n ha le chiavi `mail.*`.
- Smoke browser (uvicorn no-reload, `127.0.0.1`): `/mail` rende (CTA se non connesso, o lista se connesso con mock/live), compose modal apre, 0 errori console.

## Incluso vs rimandato (confine Fase 1)

**Incluso**: lettura inbox + conversazione + ricerca + nav label + scarica allegati; compose Nuovo/Rispondi/Rispondi-a-tutti/Inoltra + allegati in invio + bozze; invio via `gmail.compose`; iframe sandbox + blocco immagini remote.

**Rimandato**: integrazione CRM (Sotto-fase 2); segna-letto/archivia/elimina/etichetta (`gmail.modify`); filtri/regole, firme rich, snooze, spam, editor rich-text avanzato, autocomplete contatti; provider non-Google.

## Versioning / chiusura

- Bump `app/main.py` `3.5.0-alpha.172.243` → `.244` a fine fase + CHANGELOG + STATO, commit stesso giro. `.env.example`: eventuale nota scope Gmail (nessuna nuova var — riusa `GOOGLE_OAUTH_CLIENT_ID`/`SECRET`; le Gmail API vanno abilitate nel progetto Google Cloud). Ramo dedicato `feat/mail-client-phase1`.
