# Sotto-fase 2a — Email client: azioni & organizzazione (Gmail-native)

**Data:** 2026-07-11
**Ramo:** `feat/mobile-responsive-email`
**Versione target:** v3.5.0-alpha.172.249
**Programma:** parte 2a di 4 (Email client core). Vedi `2026-07-11-calendar-my-calendars-design.md` per il programma.

---

## Contesto

`/mail` (α.244–247) è un **proxy stateless** su Gmail (nessun DB locale). Legge thread,
compone, allega, ricerca. Manca tutta l'operatività di un client (stato messaggi,
organizzazione, bulk). Matteo vuole un client "come Thunderbird" **sincronizzato con
Gmail** → architettura Gmail-native: ogni azione si riflette sul vero account.

## Obiettivo 2a

Azioni di stato + organizzazione base, tutte via Gmail API:
letto/non-letto, stella, archivia, cestino, sposta/etichetta, multi-select+bulk,
conteggi non-letti, paginazione, rispondi-a-tutti.

## Non-obiettivi (2b/2c/2d)

- Creare/rinominare/annidare etichette (cartelle/sottocartelle) → 2b.
- Rich-text compose, firma, bozza live → 2c.
- Rubrica dedicata, filtri Gmail, auto-reply → 2d.

---

## Scope OAuth

`GMAIL_SCOPES` (opt-in email) cambia:
- `gmail.readonly` → **`gmail.modify`** (include lettura; aggiunge scrittura label/stato/archivia/cestino/sposta).
- Aggiunge **`gmail.settings.basic`** (serve in 2d; incluso ora per riconnessione unica).
- Restano `gmail.compose`, `contacts.readonly`, `contacts.other.readonly`.

`gmail.modify` è **restricted** (Google security assessment per la produzione; uso interno OK dopo re-consenso).

Fix `mail_status`: "connesso" se `gmail.modify` **o** `gmail.readonly` presente
(`_GMAIL_READ_SCOPES = ("gmail.modify", "gmail.readonly")`).

---

## Backend

### `app/services/gmail.py`

- `modify_thread(db, user_id, thread_id, add_labels=None, remove_labels=None) -> bool`
  - `POST /threads/{id}/modify` body `{addLabelIds, removeLabelIds}`. Best-effort → bool.
- `trash_thread(db, user_id, thread_id) -> bool` → `POST /threads/{id}/trash`.
- `untrash_thread(db, user_id, thread_id) -> bool` → `POST /threads/{id}/untrash`.
- `apply_action(db, user_id, thread_ids, action, label_id=None) -> dict`
  - Mappa azione → (add, remove) o trash/untrash; loop su thread_ids; ritorna `{ok, failed}`.
  - Azioni: `read`(-UNREAD), `unread`(+UNREAD), `star`(+STARRED), `unstar`(-STARRED),
    `archive`(-INBOX), `trash`, `untrash`, `spam`(+SPAM,-INBOX),
    `move`(+label_id, -INBOX), `label`(+label_id), `unlabel`(-label_id).
- `list_labels(db, user_id, counts=False)`: se `counts`, per ogni label `GET /labels/{id}`
  → aggiunge `threads_unread`. Best-effort per-label.

### `app/routers/mail.py`

- `POST /mail/api/threads/action` Form: `thread_ids` (csv), `action`, `label_id` (opz).
  → `gmail.apply_action`. Ritorna `{ok, failed}`.
- `GET /mail/api/labels` param `counts: bool = False` → passa a `list_labels`.

---

## Frontend

### `mail.html`

- Riga thread: aggiungere `<input type="checkbox" class="mail-sel">` + icona stella `.mail-star`.
- **Barra azioni** `#mail-actionbar` (nascosta di default, appare con ≥1 selezione):
  bottoni Letto / Non-letto / Stella / Archivia / Cestino / Sposta-in (dropdown etichette).
- Pulsante **"Carica altro"** `#mail-loadmore` in fondo alla lista (visibile se `next_page_token`).
- Pannello lettura: bottone **Rispondi a tutti** accanto a Rispondi/Inoltra.
- CSS: barra azioni, checkbox, stella, badge conteggio in nav.

### `mail.js`

- `mfMailLoadThreads`: render checkbox + stella per riga; usa `t.labelIds`/`t.unread`/`t.starred`
  (arricchire `_thread_headers` con `starred` = `'STARRED' in labelIds`).
- Selezione: set `_mailSel` (Set di thread id); toggle da checkbox; mostra/nascondi actionbar + conteggio.
- `mfMailAction(action, labelId?)`: POST `/mail/api/threads/action` con `[..._mailSel]` (o singolo id) → refresh.
- Azioni rapide riga (hover): stella, archivia, cestino su singolo thread.
- `mfMailLoadLabels`: `?counts=1`; mostra `(n)` non-letti accanto a etichetta; dropdown "Sposta in".
- `_mailNextPage` → bottone "Carica altro" (append, non reset).
- Reply-all: in `mfMailOpenThread` aggiungere bottone `data-mail-replyall`; handler compone
  `to = m.from`, `cc = destinatari di m.to/m.cc esclusa la propria email` (best-effort: usa tutti tranne account_email da `/mail/api/status`).

### i18n (5 lingue)

`mail.markRead`, `mail.markUnread`, `mail.star`, `mail.archive`, `mail.trash`,
`mail.moveTo`, `mail.selected` (`{n} selezionati`), `mail.loadMore`, `mail.replyAll` (esiste).

---

## Test

- `test_mail_actions.py`:
  - `modify_thread` invia add/remove corretti (mock `_gmail_request`, cattura body).
  - `apply_action` mappa ogni azione → add/remove attesi; bulk su più id; `spam` = +SPAM/-INBOX.
  - `trash_thread`/`untrash_thread` chiamano l'endpoint giusto.
  - `list_labels(counts=True)` arricchisce `threads_unread`.
  - Endpoint `POST /mail/api/threads/action` → `{ok,...}` (mock servizio).
- `mail.js` parse (node --check); nomi funzioni/chiavi i18n verificati.
- Smoke reale = Matteo (Gmail connesso, gmail.modify concesso).

## Prereq utente

Riconnettere account Google (`/settings → Account`) per il nuovo scope `gmail.modify`
+ `gmail.settings.basic`. Senza, le azioni ritornano errore best-effort (nessun crash).

## Rischi

- `gmail.modify` restricted → verifica Google per produzione (non blocca uso interno).
- Conteggi non-letti = N chiamate `labels.get` → limitare a system labels + label utente mostrate; best-effort.
