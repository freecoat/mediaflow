# Design — Mail context-menu + drag-to-label + select-all + redesign modale contatti

**Versione target:** v3.5.0-alpha.172.263
**Data:** 2026-07-17
**Pattern:** Sonnet-plan / Opus-exec, TDD + smoke browser reale.

## Contesto

Richiesta Matteo (/remote-control):
1. `/mail`: menu tasto destro (Gmail-like) con cancella, archivia, svuota trash, ecc.
2. `/mail`: drag&drop email nelle label.
3. `/mail`: select all.
4. `/contacts`: menu inserimento separato (pop-up/modal) — **rifare il look** (il modale
   esiste già da α.246, va ridisegnato più completo/bello).

Stato attuale rilevante (già presente, da riusare):
- `gmail.py`: `apply_action(thread_ids, action, label_id)` batch, `modify_thread(add,remove)`,
  `trash_thread`/`untrash_thread`, ACTION map (`archive`→remove INBOX, `label`, `trash`, `untrash`).
- `routers/mail.py`: `POST /mail/api/threads/action` (batch), CRUD label, prefs.
- `mail.js`: `_mailSel` (Set multi-select), checkbox per riga (`.mail-sel`), actionbar
  (`mfMailSyncActionbar`), quick-buttons archivia/trash per riga, `dragover` listener globale.
- `contacts.html`: `modal-contact-new` funzionante (apre da `contacts-btn-new`), campi
  name/company/email/phone/role. `contacts.js` lo wire-a a `openModal`.
- Scope: bundle base least-privilege; Gmail opt-in `gmail.modify`+compose+settings.basic+contacts.

## Decisioni prese (brainstorming)

- **Svuota trash / elimina definitivo**: richiede scope PIENO `https://mail.google.com/`
  (gmail.modify NON può cancellare, solo cestinare). → nuovo opt-in incrementale `mail_full`.
- **Drag → label**: semantica **sposta** (aggiungi label **+ rimuovi INBOX**), come Gmail.
- **Contatti**: **redesign** del modale esistente (più completo + sleek). Import/export = fuori scope.
- **Voci menu**: Archivia, Cestino, Segna letto/non letto, Star, Sposta in etichetta▸, Spam,
  + (dietro scope pieno) Elimina definitivamente, Svuota cestino.
- **Una sola versione** α.263 (feature coese e piccole).

## Fuori scope (esplicito)

- Import/export contatti (CSV/vCard) — slice separata futura.
- Azioni calendario, ricerca semantica.
- Undo delle azioni (Gmail ha "Annulla"): non incluso; toast semplice.

## A. Context menu mail

**Componente** `mfMailContextMenu` (mail.js). Un solo `<div id="mail-ctxmenu">` riusato,
posizionato assoluto al cursore, chiuso su click-fuori/Esc/scroll.

**Target dell'azione**:
- Se `contextmenu` parte da una riga **già in `_mailSel`** → azione su tutto `_mailSel`.
- Altrimenti → azione sulla **singola riga** sotto il cursore (senza alterare `_mailSel`).

**Voci** (ognuna → `POST /mail/api/threads/action` con `ids` + `action`):
| Voce | action | note |
|------|--------|------|
| Archivia | `archive` | remove INBOX |
| Sposta in cestino | `trash` | |
| Segna come letto | `read` | remove UNREAD |
| Segna come non letto | `unread` | add UNREAD |
| Speciale (star) | `star` / `unstar` | toggle in base allo stato riga |
| Sposta in etichetta ▸ | `label` (+`label_id`) submenu | move: add label **+ remove INBOX** |
| Segna come spam | `spam` | add SPAM, remove INBOX |
| — separatore — | | |
| Elimina definitivamente | `delete_forever` | **gate scope pieno** |
| Svuota cestino | (endpoint dedicato) | **gate scope pieno**, solo vista TRASH |

- Voci gated: se `!has_mail_full_scope` → renderizzate **disabilitate** con sottotesto
  "Attiva gestione avanzata" che apre `/settings` (o lancia direttamente l'opt-in
  `/auth/oauth/google/start?scopes=mail_full`). Nessuna chiamata parte.
- "Svuota cestino" visibile solo quando `currentLabel === 'TRASH'`.
- Il submenu etichette riusa l'albero già caricato (`mfMailLabels`), escludendo label di sistema.

## B. Drag & drop → etichetta

- Righe `.mail-row` → `draggable="true"`; `dragstart` setta payload = id riga (o `_mailSel`
  se la riga è selezionata). Aggiunge classe `dragging` per feedback.
- Voci etichetta in sidebar → dropzone: `dragover` (preventDefault + classe hover),
  `drop` → azione **move** `label` con `label_id` (add label + remove INBOX) su tutti gli id
  trascinati → toast → `mfMailLoad(reset)` per riflettere l'archiviazione.
- Solo label utente (non SENT/DRAFT/TRASH/SPAM di sistema) sono dropzone valide.

## C. Select all

- Nell'header lista (sopra le righe) un checkbox `#mail-selall` + label conteggio.
- `change`: se checked → aggiunge **tutti i thread caricati** a `_mailSel`; se unchecked → li rimuove.
- Stato indeterminato quando la selezione è parziale (`indeterminate=true`).
- Riusa `mfMailSyncActionbar` esistente. Su `mfMailLoad(reset)` il checkbox si resetta.

## D. Scope pieno opt-in

- `oauth_providers.py`: `MAIL_FULL_SCOPES = "https://mail.google.com/"`.
- `routers/oauth.py`: ramo `scopes == "mail_full"` → `extra = MAIL_FULL_SCOPES`.
- `gmail.py`: `has_mail_full_scope(row)` → True se `row.scopes` contiene `https://mail.google.com/`.
- `/settings`: card/bottone "Attiva gestione avanzata mail (elimina definitivo)" che lancia l'opt-in,
  accanto agli opt-in esistenti (email, calendar_write). i18n.
- **Nota sicurezza**: `https://mail.google.com/` è ampio (accesso totale mailbox). È opt-in
  esplicito, mai nel bundle base, mai forzato. Chi non lo attiva perde SOLO elimina-definitivo/
  svuota-cestino; tutto il resto (cestina, archivia, spam, label) resta su gmail.modify.

## Backend nuovo

`gmail.py`:
- Estendere ACTION map / `apply_action` con verbi: `read` (remove UNREAD), `unread` (add UNREAD),
  `star` (add STARRED), `unstar` (remove STARRED), `spam` (add SPAM, remove INBOX).
- `delete_thread_forever(db, user_id, thread_id)` → `DELETE users/me/threads/{id}` (scope pieno).
- `empty_trash(db, user_id)` → lista thread label TRASH → `delete_thread_forever` su ciascuno
  (o `messages.batchDelete`); ritorna conteggio.
- `has_mail_full_scope(row)`.

`routers/mail.py`:
- `POST /mail/api/threads/action`: accettare i nuovi verbi. Per `delete_forever` → gate
  `has_mail_full_scope` (403 altrimenti).
- `POST /mail/api/trash/empty` → gate scope pieno → `empty_trash` → `{deleted: n}`.

`routers/oauth.py`: ramo `mail_full`.

## Frontend nuovo/modificato

- `mail.js`: `mfMailContextMenu`, handler drag/drop, select-all, chiamate ai nuovi verbi,
  gating UI voci avanzate. Nessun `JSON.stringify` in onclick (usa data-attr, regola progetto).
- `mail.html`: contenitore `#mail-ctxmenu`, checkbox `#mail-selall`, `draggable` sulle righe.
- `main.css` (+ `sleek.css`): stile context menu, dropzone hover, dragging, select-all.
- `settings` template + js: bottone opt-in `mail_full`.

## E. Redesign modale contatti

- `modal-contact-new` ridisegnato: campi **sezionati** (Anagrafica: nome; Azienda/Ruolo;
  Contatti: email, telefono) + nuovo campo **Note** (`textarea`). Estetica sleek coerente
  (spaziature, label, radius). `max-width` adeguato.
- `Contact.notes` (Text, nullable) **esiste già** in `models.py:4843` → **nessuna migrazione**,
  solo UI + wiring API.
- `contacts.js`: leggere/scrivere `notes`. API create/update già form-based → aggiungere campo.
- Verificare che il router contatti (create/update) accetti già `notes` come `Form(...)`;
  se no, aggiungerlo (empty multipart = None: gestire con sentinel se serve svuotare).

## i18n

Tutte le stringhe nuove (voci menu, tooltip, select-all, opt-in, note, sezioni modale) in
`it/en/fr/de/es` in `i18n.js`, stesso commit. `data-i18n`/`data-i18n-attr` nei template.

## Test

- **Unit** (`.venv` pytest): nuovi verbi `apply_action` (read/unread/star/unstar/spam →
  add/remove label corretti); `has_mail_full_scope` (True solo con scope pieno, False con
  gmail.modify); `delete_forever`/`empty_trash` gate 403 senza scope; opt-in `mail_full`
  in authorization_url; drag-move = label+archive (add label, remove INBOX).
- **Smoke browser reale** (DB copia scratch, mai reale; Gmail reale in lettura; azioni
  distruttive **stubbate** per non toccare la mailbox vera): context menu compare, voci
  gated disabilitate senza scope pieno, drag&drop su label, select-all, modale contatti
  ridisegnato apre e salva. 0 errori console. Grep dei nomi funzione prima del commit
  (smoke backend non cattura ReferenceError JS).

## Rischi / trappole note

- Permanent delete è **irreversibile** su Google: doppio `confirm()` nativo (come delete
  eventi calendario α.248). "Svuota cestino" idem.
- Empty multipart = None (sentinel se serve pulire campi contatto).
- Template su OneDrive: restart prima dello smoke. Cache-buster `?v=` per mail.js/contacts.js.
- Righe draggable non devono rompere il click d'apertura thread né il checkbox (già gestito
  `if (t.closest('.mail-sel')) return`). Distinguere click vs dragstart.
