# Calendario — Eventi Google editabili da Claqo — Design

> Segue Fase A (OAuth foundation, α.239), Fase B/B.1 (calendario locale, α.240/241), Fase C (sync bidirezionale Claqo→Google + overlay read-only, α.242). Questo documento NON è ancora approvato da Matteo — è la proposta da presentare.

## Obiettivo

Oggi l'overlay Google in `/calendar` è **sola lettura**: mostra gli eventi degli altri calendari Google dell'utente (`list_google_events`), ma `calendar_page.js` li marca sempre `editable: false`. L'obiettivo è permettere all'utente di **modificare ed eliminare** questi eventi reali direttamente da Claqo, quando ne ha il permesso su Google (calendario di cui è owner/writer), senza rompere:
- il modello di sync esistente (Claqo→calendario "Claqo" via `calendar.app.created`, mirror one-way, mai toccato da questa feature);
- il principio best-effort dell'overlay (un fallimento Google non deve mai rompere `/calendar`);
- least-privilege sugli scope OAuth.

## Stato attuale accertato (evidenza da codice)

- `app/services/oauth_providers.py`: `PROVIDERS["google"]["scopes"]` = `openid email profile gmail.send drive.file calendar.app.created calendar.readonly`. `GMAIL_SCOPES` esiste come bundle opt-in incrementale, richiesto via `GET /auth/oauth/google/start?scopes=email` (`app/routers/oauth.py:68`) che passa `extra_scopes=GMAIL_SCOPES` a `authorization_url()`, la quale aggiunge `include_granted_scopes=true` quando `extra_scopes` è presente (`oauth_providers.py:133-154`). Pattern riusabile as-is per un nuovo bundle scritture calendario.
- `app/services/google_calendar.py`: `list_google_events()` itera `/users/me/calendarList` (che include nativamente `accessRole` per calendario, non ancora letto/propagato) e per ognuno (escluso il calendario Claqo) chiama `/calendars/{cid}/events`. `_normalize_google_event()` produce oggi `{id, title, start, end, all_day, calendar, read_only: True}` — **fisso**, non condizionato al permesso reale.
- `app/routers/calendar.py`: `GET /calendar/api/google-overlay` (righe 233-243) fa `try: ... except Exception: return {"events": []}` — inghiotte tutto, **zero log**, indistinguibile da "utente non connesso" o "errore transitorio Google".
- `app/static/js/calendar_page.js`: riga 39, ogni evento Google → `editable: false, classNames: ['cal-google'], extendedProps: { google: true }` incondizionatamente. `eventClick` (riga 110) esce subito se `extendedProps.google`. `eventDrop`/`eventResize` → `_calPutTimes` (righe 82-89), che guarda solo `extendedProps.marker`, non `google` (oggi non rilevante perché FullCalendar non droppa un evento con `editable:false` a livello di evento, ma se diventa condizionale va gestito esplicitamente).
- `app/static/js/event_modal.js`: unica fonte di scrittura eventi, hardcoded su `/calendar/api/events` (locale). Nessun concetto di "evento esterno".
- `CalendarEvent` (model, `models.py:4888-4918`) ha già tutte le colonne sync (`source`, `external_calendar_id`, `external_event_id`, `sync_state`, `last_synced_at`, `sync_error`) — pensate per il mirror one-way Claqo→Google, non per importare eventi Google altrui.
- `UserOAuthToken.scopes` (Text) contiene la stringa scope realmente concessa da Google al momento del consenso (`save_token`, `oauth_providers.py:242`) — **può essere più ampia** di quanto richiesto (evidenza: il token di user_id=1 ha già scope `calendar` pieno). Non si può assumere per tutti gli utenti.
- `app/static/js/settings_account.js` (righe 37-44): pattern già in produzione per "opt-in incrementale visibile in UI" — badge se lo scope è già presente in `p.scopes`, altrimenti link `/auth/oauth/google/start?scopes=email`. Stesso pattern riusabile per il write-scope calendario.

---

## Domanda 1 — Scope: bundle base pieno vs opt-in incrementale

**Opzioni:**
- (a) Sostituire `calendar.readonly` con `calendar` pieno nel bundle base `PROVIDERS["google"]["scopes"]`.
- (b) Nuovo bundle **`calendar.events`** (non `calendar` pieno), richiesto **on-demand** via un nuovo parametro `scopes=calendar_write` sul flow esistente `GET /auth/oauth/{provider}/start`, esattamente come `GMAIL_SCOPES`/`scopes=email` oggi.

**Trade-off:** `calendar` pieno concede anche creazione/eliminazione/condivisione di calendari interi (oltre agli eventi) — più del necessario: Claqo deve editare *eventi* su calendari di cui l'utente è owner/writer, mai gestire i calendari stessi. `calendar.events` ("View and edit events on all your calendars") è lo scope minimo che copre esattamente il caso d'uso, e resta comunque un aumento di superficie rispetto a `calendar.readonly` — per questo va tenuto **opt-in**, non nel bundle base: un utente che collega Google solo per l'overlay/sync locale non deve accettare permessi di scrittura che non userà.

**Raccomandazione: (b), opt-in incrementale.** Nuova costante `CALENDAR_WRITE_SCOPES = "https://www.googleapis.com/auth/calendar.events"` in `oauth_providers.py`, riusando `extra_scopes` + `include_granted_scopes=true` (già implementato). In `oauth.py::oauth_start`, estendere il mapping esistente (`scopes=email` → `GMAIL_SCOPES`) con `scopes=calendar_write` → `CALENDAR_WRITE_SCOPES`.

**Impatto su utenti già collegati:** `include_granted_scopes=true` fa sì che Google **unisca** il nuovo scope a quelli già concessi, senza richiedere un nuovo collegamento completo — è lo stesso meccanismo che oggi fa funzionare l'opt-in Gmail su un account già connesso per Calendar/Drive. L'utente clicca un bottone "Attiva editing calendario" in `/settings`, passa dal consent screen (mostra solo il nuovo permesso, Google lo sa perché riconosce lo stesso client+account con scope già presenti), torna, e `UserOAuthToken.scopes` ora contiene anche `calendar.events`. Nessun re-consent forzato per chi non lo richiede esplicitamente, nessuna rottura per chi ha già uno scope più ampio (case user_id=1: `calendar` pieno **include** già `calendar.events` come sottoinsieme funzionale — va trattato come "write abilitato" anche se la stringa esatta `calendar.events` non compare, vedi helper sotto).

**Conseguenza implementativa:** un helper `has_calendar_write_scope(row: UserOAuthToken) -> bool` che verifica `"calendar.events" in (row.scopes or "")` **oppure** `"/auth/calendar " in (row.scopes or "") or (row.scopes or "").rstrip().endswith("/auth/calendar")` (per intercettare lo scope pieno `calendar`, che è un superset). Centralizzato in `google_calendar.py` (unico punto, riusato da router + normalizzazione overlay).

---

## Domanda 2 — Modello: import come `CalendarEvent` vs overlay "virtuale"

**Opzioni:**
- (a) Import: alla prima vista/edit, materializzare l'evento Google come riga `CalendarEvent` con `source='google'`, `external_event_id`, poi riusare **verbatim** il CRUD locale (`/calendar/api/events`), `event_modal.js`, RBAC, sync.
- (b) Overlay resta **virtuale** (mai persistito): un nuovo percorso di scrittura minimale che parla direttamente con Google in lettura/scrittura al momento dell'azione, senza mai creare una riga `CalendarEvent`.

**Trade-off (a):** riuso massimo di codice/RBAC/modale, ma introduce una classe di problemi che oggi non esiste: conflitto tra "riga Claqo che rappresenta un evento altrui" e il mirror one-way Fase C (`maybe_autosync_event`/`sync_user_pending` presumono che ogni `CalendarEvent` locale sia **posseduto** da Claqo e destinato al calendario "Claqo" — un `source='google'` importato romperebbe quell'invariante o richiederebbe una seconda logica di sync parallela con conflict-resolution vera, mai costruita, per capire chi vince se l'evento cambia sia su Google che (teoricamente) su Claqo). Rischio concreto di duplicazione (l'evento appare sia come riga importata sia come overlay se non disaccoppiato con cura) e di far west sulle differenze semantiche (l'evento Google può avere ricorrenze, allegati, conferenceData che `CalendarEvent`/`event_modal.js` non modellano — importarlo "a metà" crea uno stato bugiardo).

**Trade-off (b):** nessuna nuova tabella, nessun rischio di doppia fonte di verità, coerente con l'architettura "Claqo è l'unica fonte di verità per gli eventi Claqo" già scritta nel design Fase C. Costo: ogni edit richiede un round-trip live a Google (nessuna cache locale) — accettabile perché l'overlay è **già** live-fetched ad ogni `refetchEvents()`, non c'è regressione di UX.

**Raccomandazione: (b), overlay virtuale.** Nessuna riga `CalendarEvent` creata per eventi Google esterni. Nuovo percorso di scrittura dedicato (Domanda 3) che opera solo su richiesta esplicita dell'utente (click su un evento overlay editabile), mai in background, mai in `sync_user_pending`. Il modello `CalendarEvent`/`source='claqo'` resta intatto e dedicato al mirror Fase C.

---

## Domanda 3 — Scrittura: dove vive il codice, quali endpoint, gestione conflitti/errori

**Dove:** in `app/services/google_calendar.py` (stesso layer HTTP di `push_event`/`delete_event`/`list_google_events`, unico punto di mock `_google_request`), **non** in `calendar_sync.py` (quel modulo orchestra solo il mirror Claqo→Google in blocco/autosync; questa è un'azione singola, sincrona, iniziata dall'utente — wiring diverso, va tenuto separato per non confondere le due semantiche).

**Nuove funzioni (`google_calendar.py`):**
- `get_external_event(db, user_id, calendar_id, event_id) -> Optional[dict]` — `GET /calendars/{cid}/events/{eid}`, normalizza + include `etag` grezzo (per il conflict check). Usata per idratare il modale con i dati più freschi possibili **appena prima** di aprirlo in edit (mitiga, non elimina, le race).
- `update_external_event(db, user_id, calendar_id, event_id, *, title=None, start_at=None, end_at=None, all_day=None, location=None, etag=None) -> dict` — `PATCH` (non `PUT`: `PATCH` aggiorna solo i campi inviati, `PUT` sovrascriverebbe l'intera risorsa e rischierebbe di cancellare `recurrence`/`conferenceData`/`attendees` che Claqo non modella). Se `etag` è passato, header `If-Match: {etag}`.
- `delete_external_event(db, user_id, calendar_id, event_id, *, etag=None) -> dict` — `DELETE`, stesso header opzionale.
- Estensione di `_google_request` con un parametro `extra_headers: Optional[dict] = None` (oggi headers hardcoded a 2 chiavi) — modifica minima, retrocompatibile.

Tutte ritornano `{"ok": bool, "error": Optional[str], "http_status": Optional[int]}` invece di sollevare, coerente con lo stile best-effort già usato da `push_event`/`delete_event` (che ritornano `bool` + settano `sync_error` su un oggetto ORM — qui non c'è un ORM da annotare, quindi il dict di ritorno è il canale d'errore verso il router).

**Conflitti — raccomandazione: If-Match opportunistico, non un vero merge.** Google Calendar API supporta `If-Match` con l'`etag` della risorsa. Flusso: apertura modale su evento overlay editabile → `GET` fresco (via `get_external_event`) per popolare form + etag → submit → `PATCH`/`DELETE` con `If-Match`. Se nel frattempo l'evento è cambiato su Google, l'API risponde **412 Precondition Failed** → il router lo mappa a un errore applicativo dedicato (non 500) → il frontend mostra "Evento modificato nel frattempo su Google, ricarico" e fa `refetchEvents()` invece di sovrascrivere alla cieca. Non si costruisce un merge a 3 vie: è un guardrail contro il caso più comune (due dispositivi), non una feature di collaborazione.

**Errori da gestire esplicitamente nel router (mappa HTTP Google → risposta Claqo):**
- `404` → evento già cancellato su Google (da un altro client) → trattare come successo idempotente per DELETE (stesso pattern già usato in `delete_event` locale, riga 127 di `google_calendar.py`), come errore "evento non più disponibile" per PATCH → refetch.
- `403` → il token non ha lo scope, o l'utente non è più writer su quel calendario (permessi cambiati lato Google dopo l'ultimo `calendarList` fetch) → messaggio esplicito, mai un 500 generico.
- `409`/`412` → conflitto, vedi sopra.
- Qualunque altro errore → log + messaggio generico, mai propagare uno stack trace al frontend.

**Calendari di sola lettura (es. "Kalenderwochen", festività, calendari condivisi in lettura):** la fonte di verità è `accessRole` restituito da `/users/me/calendarList` per **ogni singolo calendario** (`owner`, `writer`, `reader`, `freeBusyReader`). Va letto e propagato — oggi non lo è affatto (Domanda 4). Nessuna euristica sul nome del calendario: è l'unico segnale corretto e già disponibile gratis nella stessa chiamata che l'overlay fa già.

**Scope aggiuntivo fuori target esplicito (scelta di riduzione, non omissione):** eventi ricorrenti (`recurrence` presente o `recurringEventId` valorizzato — cioè sia la master series sia una singola istanza) restano **sempre non editabili da Claqo**, indipendentemente da `accessRole`. Editare "questa occorrenza" vs "tutta la serie" è una UX/logica RRULE che `event_modal.js` non ha e non deve acquisire in questa iterazione — è un buco reale ma va dichiarato esplicitamente fuori scope, non lasciato a un bug latente.

---

## Domanda 4 — Permessi: propagare `accessRole` all'UI

`accessRole` è già nel payload di `/users/me/calendarList` (nessuna chiamata aggiuntiva). `list_google_events` oggi lo ignora. Estendere:

```
for cal in cal_list.get("items", []):
    access_role = cal.get("accessRole")   # owner|writer|reader|freeBusyReader
    ...
    out.append(_normalize_google_event(g, cal.get("summary") or cid, cid, access_role, write_scope_ok))
```

`_normalize_google_event` guadagna: `calendar_id`, `access_role`, `editable` (bool calcolato: `access_role in ("owner", "writer") and write_scope_ok and not is_recurring(g)`), `etag`. Il campo `editable` **per-evento** è la singola fonte di verità che il frontend userà — niente logica di permesso duplicata lato JS, il server decide.

`write_scope_ok` è calcolato **una volta per utente** (via `has_calendar_write_scope`, Domanda 1) e passato come parametro, non ricalcolato per evento.

---

## Domanda 5 — UI: distinzione visiva, riuso modale, drag&drop

- **Visiva:** classe FullCalendar aggiuntiva `cal-google-editable` (bordo pieno, non tratteggiato) accanto a `cal-google` (bordo tratteggiato, tono smorzato — invariato per i non editabili). Nessun nuovo colore semantico da inventare: riusa la palette esistente, solo lo stile del bordo cambia.
- **`calendar_page.js` — mapping overlay:** `editable: !!g.editable`, `classNames: g.editable ? ['cal-google','cal-google-editable'] : ['cal-google']`, `extendedProps: { google: true, editable: g.editable, calendar_id: g.calendar_id, event_id: g.id }`.
- **`eventClick`:** oggi esce sempre se `extendedProps.google`. Nuova condizione: se `google && !editable` → esce (comportamento invariato, sola lettura); se `google && editable` → apre `event_modal.js` in una nuova modalità "esterna" (vedi sotto), passando `calendar_id`/`event_id` invece di un `id` locale.
- **`event_modal.js`:** aggiunge un ramo `opts.external = {calendar_id, event_id}`. In quel ramo: (1) fa `GET /calendar/api/google-events/{cal}/{eid}` per idratare form + etag prima di mostrare il modale (Domanda 3); (2) nasconde i campi che non hanno senso su un evento Google grezzo (link ad acquisition/project/client, campo "Stato" che è un enum Claqo-specifico — Google ha solo `confirmed|tentative|cancelled` diverso semanticamente, va mappato o nascosto, si raccomanda nascosto in questa iterazione); (3) al salvataggio, POST/PATCH a `/calendar/api/google-events/{cal}/{eid}` invece di `/calendar/api/events/{id}`; (4) il bottone elimina richiede un secondo step di conferma esplicito (Domanda 7), diverso dal `confirm()` nativo usato oggi per gli eventi locali.
- **Drag & drop (`eventDrop`/`eventResize` → `_calPutTimes`):** FullCalendar non permette il drag su un evento con `editable:false` a livello di evento, quindi i Google read-only sono già protetti gratuitamente lato client. Per i Google editabili, serve però smistare `_calPutTimes` verso l'endpoint giusto: oggi fa sempre `PUT /calendar/api/events/{id}`. Nuova logica: se `info.event.extendedProps.google`, chiama invece `update_external_event` via il nuovo endpoint con solo `start_at`/`end_at` (niente etag su un drag rapido — micro-conflitto accettabile e comunque rilevato server-side se Google risponde 412, con `info.revert()` sul fallimento, esattamente come già avviene oggi per il fallimento locale).

---

## Domanda 6 — Diagnosticabilità dell'overlay

Il bare `except Exception: return {"events": []}` in `google_overlay` (router) oggi non logga **nulla** — diverso da `list_google_events`, che già fa `log.warning` sui fallimenti per-singolo-calendario. Il problema è specificamente nel router.

**Raccomandazione: non introdurre un 502.** Cambierebbe un contratto che il frontend e il design Fase C trattano esplicitamente come best-effort ("Overlay in errore (o non connesso) → `{"events": []}`, il calendario locale funziona comunque" — dal design doc Fase C). Un 502 romperebbe quell'invariante per un guadagno di diagnosticabilità ottenibile in modo meno invasivo:

1. `list_google_events`/le nuove funzioni loggano già (o logeranno) con `log.warning`/`log.exception` — sufficiente per il debug server-side.
2. Il router logga esplicitamente l'eccezione prima di ritornare (oggi non lo fa):
   ```python
   except Exception as e:
       log.warning(f"google_overlay fallito user={u.id}: {e}")
       return {"events": [], "error": True}
   ```
3. La risposta guadagna un campo opzionale `error: true` (assente = tutto ok) **distinto** da "non connesso" (`{"events": []}` senza `error`, comportamento invariato per l'utente senza Google collegato — quello non è un errore, è uno stato normale). Il frontend, se vede `error: true`, può mostrare un piccolo indicatore non bloccante (es. un'icona ⚠ accanto al checkbox "Mostra Google") — non un toast invasivo, perché l'overlay è un contorno, non il cuore della pagina.

Risultato: stesso contratto HTTP (200, mai propaga eccezioni al client), ma ora **osservabile in log** e **distinguibile in UI** tra "nessun account collegato" e "Google ha rifiutato/è irraggiungibile".

---

## Domanda 7 — Rischio di cancellazione irreversibile

Un evento eliminato via Google Calendar API è **permanente**: non esiste soft-delete/trash per singoli eventi lato Google (a differenza di Gmail). Nessun modo per Claqo di offrire un "recupera" dopo il fatto.

**Guardrail raccomandati (proporzionati, non un cassetto di controlli inutilizzati):**
1. **Conferma a due passi, non `confirm()` nativo.** L'eliminazione di un evento Claqo locale oggi usa `confirm()` del browser (`event_modal.js:179`, riga `_onDelete`) — accettabile lì perché il locale non è mai distruttivo verso l'esterno (l'evento resta soft-deleted). Per un evento Google esterno, il modale mostra invece un pannello di conferma inline con il titolo dell'evento interpolato e un secondo bottone esplicito "Elimina definitivamente da Google" (rosso, distinto dal primo click "Elimina"), sullo stile dei gate di distruzione già presenti nel progetto (TPN/archivio) — stesso principio, scala ridotta.
2. **Nessuna eliminazione di gruppo.** L'azione resta single-event, iniziata da un click esplicito sull'evento nell'overlay. Niente multiselect/bulk-delete su eventi Google in questa iterazione (multiselect è desiderata generale del progetto ma qui aumenterebbe il raggio d'azione di un'operazione irreversibile senza un bisogno dimostrato).
3. **RBAC invariato ma esplicito nel log.** L'endpoint resta dietro `manage_calendar` (stesso gate degli eventi locali) — non si inventa un permesso più stringente ad hoc, sarebbe incoerente col resto del progetto. In compenso ogni `update_external_event`/`delete_external_event` logga (livello `info`, non solo `warning` sugli errori) `user_id`, `calendar_id`, `event_id`, azione — non una tabella di audit dedicata (over-engineering per il bisogno reale), ma una riga di log strutturata sufficiente a ricostruire "chi ha toccato cosa" se Matteo chiede spiegazioni.
4. **Eventi ricorrenti sempre non editabili** (Domanda 3) elimina il caso peggiore: cancellare per sbaglio un'intera serie ricorrente scambiandola per un evento singolo.
5. **Etag/If-Match** (Domanda 3) riduce il rischio di eliminare/sovrascrivere una versione diversa da quella vista dall'utente.

---

## Rischi generali e limiti noti

- **Quota API Google Calendar:** ogni apertura di edit fa un `GET` extra (fetch etag fresco); su un utente con molti calendari/eventi resta trascurabile (azione manuale, non polling), ma va tenuto a mente se in futuro si volesse automatizzare.
- **`event_modal.js` diventa più complesso** (due modalità: locale vs esterno). Va tenuto in un unico file per non duplicare markup/i18n, ma con branching chiaro — rischio di leggibilità se non isolato bene in funzioni dedicate (`_onSaveExternal`, `_onDeleteExternal` separate da `_onSave`/`_onDelete`).
- **Nessuna localizzazione del fuso orario esplicita** oltre a quanto FullCalendar/Google già gestiscono con `dateTime` ISO — invariato rispetto a oggi, non introdotto da questa feature.
- **Scope `calendar.events` non copre calendari "domain-wide delegated"** o organizzazioni con Workspace policy particolari — fuori controllo di Claqo, va solo gestito l'errore 403 pulito (già previsto).

## Fuori scope (YAGNI, esplicito)

- Creazione di **nuovi** eventi direttamente su calendari Google esterni (solo edit/delete di eventi esistenti; creare nuovi eventi Claqo continua a passare dal mirror Fase C verso il calendario "Claqo").
- Editing di ricorrenze (singola occorrenza vs intera serie).
- Merge/conflict resolution vera (si rileva il conflitto, non lo si risolve automaticamente).
- Audit trail strutturato in tabella dedicata (basta il log).
- Gestione `attendees`/inviti/`conferenceData` (Meet/Zoom embed) su eventi Google esterni — il modale Claqo non li tocca né li mostra, `PATCH` invia solo i campi che modifica quindi non li cancella accidentalmente.
- Multiselect/bulk actions su eventi Google.
- Microsoft/Outlook (resta "Prossimamente").

## Self-review

- Placeholder: nessun TBD lasciato aperto nelle 7 domande.
- Consistenza con l'architettura esistente: `google_calendar.py` resta l'unico layer HTTP mockabile; `calendar_sync.py` resta scoperto da questa feature (azione singola sincrona, non orchestrazione in blocco); router = wiring + mapping errori; frontend = due modalità nello stesso modale condiviso, non un modale duplicato.
- Ambiguità del prompt originale risolte con raccomandazione esplicita e motivata in ognuna delle 7 sezioni, non solo elencate come opzioni.
- Decisione di riduzione di scope dichiarata esplicitamente (ricorrenze sempre read-only) invece di lasciata come edge case implicito.
