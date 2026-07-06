# Calendario Fase B.1 — Editing eventi + leggibilità — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendere gli appuntamenti creabili/modificabili/eliminabili via un modal condiviso, con vista calendario settimanale leggibile e lista appuntamenti leggibile nel tab acquisizioni.

**Architecture:** Un modulo JS autonomo `event_modal.js` (unica fonte di verità per la scrittura eventi: POST/PUT/DELETE) inietta il proprio modal nel DOM ed espone `openEventModal({event, prefill, onSaved})`. `calendar_page.js` passa a vista settimana e apre il modal su click/select/resize. Il tab Appuntamenti in `acquisitions.html` renderizza righe leggibili con ✎/🗑 e usa lo stesso modal. Nessuna modifica backend.

**Tech Stack:** Vanilla JS, FullCalendar 6 (già caricato via CDN), Jinja2, i18n client-side (`window.MF_I18N`).

## Global Constraints

- **Nessuna modifica backend.** `app/routers/calendar.py` (α.172.240) espone già `GET` (serializza title/start/end/all_day/location/meeting_url/status/acquisition_id/project_id/client_id), `POST`, `PUT`, `DELETE` Form-based.
- **Helper globali, non ridefinire:** `openModal(id)`/`closeModal(id)` (toggle classe `.open` su `.modal-overlay#id`), `toast(msg,'success'|'error')`, `escapeHtml(s)`, `mfT(key)` (1 arg, ritorna `key` se la chiave manca → **ogni chiave usata DEVE esistere in i18n.js**), `applyI18n(root)`. Tutti in `global.js`/`i18n.js`.
- **Form-based:** il modal invia `FormData` a POST/PUT/DELETE.
- **Cache-buster:** ogni `<script src>` static con `?v={{ app_version }}`.
- **i18n 5 lingue** (it/en/fr/de/es) per ogni chiave nuova, stesso commit. Senza accenti "esotici" dove i valori esistenti li evitano (coerenza col file: es. "Debut", "Loschen").
- **Anti-XSS:** `meeting_url` reso come link solo se `/^https?:\/\//i`.
- **Markup modal:** segue il pattern del progetto — `<div class="modal-overlay" id="..."><div class="modal"><div class="modal-header"><span class="modal-title">…</span><button…>&times;</button></div><div class="modal-body">…</div><div class="modal-footer">…</div></div></div>`. Classi form: `form-group`, `form-row`, `form-label`, `form-input`, `form-select`.
- **Interprete test:** `.venv/Scripts/python.exe -m pytest ...`. Commit via `git commit -F <file>` (heredoc bloccato da hook; costruisci il messaggio con `printf` bash, non PowerShell, per evitare BOM).
- **Versione attuale:** `3.5.0-alpha.172.240` → `.241` (Task 4).

---

### Task 1: `event_modal.js` — modal evento condiviso + chiavi i18n

**Files:**
- Create: `app/static/js/event_modal.js`
- Modify: `app/static/js/i18n.js` (nuove chiavi, vicino alle `cal.event.*` esistenti ~riga 1008)
- Test: `tests/test_calendar_editing.py` (parte i18n)

**Interfaces:**
- Produces: globale `window.openEventModal(opts)` dove `opts = { event?, prefill?, onSaved? }`.
  - `event`: oggetto serializzato dal backend (`{id, title, start, end, all_day, location, meeting_url, status, acquisition_id, client_id, project_id}`) → modalità edit (PUT, mostra Elimina).
  - `prefill`: `{ start?, end?, acquisition_id?, client_id?, project_id? }` → modalità create (POST).
  - `onSaved`: callback dopo save/delete riusciti.
- Consumes: helper globali; API `/calendar/api/events` (POST/PUT/DELETE).

- [ ] **Step 1: Write the failing test (i18n keys present)**

```python
# tests/test_calendar_editing.py
import pathlib


def test_i18n_has_event_modal_keys():
    src = pathlib.Path("app/static/js/i18n.js").read_text(encoding="utf-8")
    for key in ("cal.event.allday", "cal.event.status", "cal.event.status.confirmed",
                "cal.event.status.tentative", "cal.event.status.cancelled",
                "cal.event.cancel", "cal.event.new", "cal.event.edit",
                "cal.event.deleteConfirm", "cal.event.linkedTo", "cal.event.saved",
                "cal.event.err.title", "cal.event.err.range"):
        assert key in src, key
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_calendar_editing.py::test_i18n_has_event_modal_keys -v`
Expected: FAIL (chiavi assenti).

- [ ] **Step 3: Add the i18n keys**

In `app/static/js/i18n.js`, subito dopo `'cal.event.delete': …` (~riga 1008):

```javascript
  'cal.event.new':     {it: 'Nuovo appuntamento', en: 'New appointment', fr: 'Nouveau rendez-vous', de: 'Neuer Termin', es: 'Nueva cita'},
  'cal.event.edit':    {it: 'Modifica appuntamento', en: 'Edit appointment', fr: 'Modifier le rendez-vous', de: 'Termin bearbeiten', es: 'Editar cita'},
  'cal.event.allday':  {it: 'Tutto il giorno', en: 'All day', fr: 'Toute la journee', de: 'Ganztags', es: 'Todo el dia'},
  'cal.event.status':  {it: 'Stato', en: 'Status', fr: 'Statut', de: 'Status', es: 'Estado'},
  'cal.event.status.confirmed': {it: 'Confermato', en: 'Confirmed', fr: 'Confirme', de: 'Bestatigt', es: 'Confirmado'},
  'cal.event.status.tentative': {it: 'Provvisorio', en: 'Tentative', fr: 'Provisoire', de: 'Vorlaufig', es: 'Provisional'},
  'cal.event.status.cancelled': {it: 'Annullato', en: 'Cancelled', fr: 'Annule', de: 'Abgesagt', es: 'Cancelado'},
  'cal.event.cancel':  {it: 'Annulla', en: 'Cancel', fr: 'Annuler', de: 'Abbrechen', es: 'Cancelar'},
  'cal.event.deleteConfirm': {it: 'Eliminare questo appuntamento?', en: 'Delete this appointment?', fr: 'Supprimer ce rendez-vous ?', de: 'Diesen Termin loschen?', es: 'Eliminar esta cita?'},
  'cal.event.linkedTo': {it: 'Collegato a', en: 'Linked to', fr: 'Lie a', de: 'Verknupft mit', es: 'Vinculado a'},
  'cal.event.saved':   {it: 'Appuntamento salvato', en: 'Appointment saved', fr: 'Rendez-vous enregistre', de: 'Termin gespeichert', es: 'Cita guardada'},
  'cal.event.err.title': {it: 'Titolo obbligatorio', en: 'Title required', fr: 'Titre obligatoire', de: 'Titel erforderlich', es: 'Titulo obligatorio'},
  'cal.event.err.range': {it: 'La fine precede l\'inizio', en: 'End is before start', fr: 'La fin precede le debut', de: 'Ende liegt vor Beginn', es: 'El fin precede al inicio'},
```

- [ ] **Step 4: Create `event_modal.js`**

```javascript
// app/static/js/event_modal.js — Fase B.1: modal evento condiviso (create/edit/delete)
// Unica fonte di verità per la scrittura eventi. Espone window.openEventModal.
(function () {
  var MODAL_ID = 'event-modal';
  var _ctx = null; // { id, onSaved }

  function _T(key) { return (window.mfT ? mfT(key) : key); }

  function _ensureModal() {
    if (document.getElementById(MODAL_ID)) return;
    var html =
      '<div class="modal-overlay" id="' + MODAL_ID + '">' +
      '  <div class="modal" style="max-width:520px;">' +
      '    <div class="modal-header">' +
      '      <span class="modal-title" id="evm-title" data-i18n="cal.event.new">Nuovo appuntamento</span>' +
      '      <button class="btn btn-ghost btn-icon" type="button" onclick="closeModal(\'' + MODAL_ID + '\')">&times;</button>' +
      '    </div>' +
      '    <div class="modal-body">' +
      '      <input type="hidden" id="evm-id">' +
      '      <input type="hidden" id="evm-acquisition-id">' +
      '      <input type="hidden" id="evm-client-id">' +
      '      <input type="hidden" id="evm-project-id">' +
      '      <div id="evm-linked" class="text-muted" style="font-size:12px;margin-bottom:8px;display:none;"></div>' +
      '      <div class="form-group">' +
      '        <label class="form-label" data-i18n="cal.event.title">Titolo</label>' +
      '        <input class="form-input" id="evm-field-title" type="text" required>' +
      '      </div>' +
      '      <div class="form-group">' +
      '        <label style="display:flex;align-items:center;gap:6px;font-size:13px;">' +
      '          <input type="checkbox" id="evm-allday"> <span data-i18n="cal.event.allday">Tutto il giorno</span>' +
      '        </label>' +
      '      </div>' +
      '      <div class="form-row">' +
      '        <div class="form-group" style="flex:1;">' +
      '          <label class="form-label" data-i18n="cal.event.start">Inizio</label>' +
      '          <input class="form-input" id="evm-start" type="datetime-local">' +
      '        </div>' +
      '        <div class="form-group" style="flex:1;">' +
      '          <label class="form-label" data-i18n="cal.event.end">Fine</label>' +
      '          <input class="form-input" id="evm-end" type="datetime-local">' +
      '        </div>' +
      '      </div>' +
      '      <div class="form-row">' +
      '        <div class="form-group" style="flex:1;">' +
      '          <label class="form-label" data-i18n="cal.event.location">Luogo</label>' +
      '          <input class="form-input" id="evm-location" type="text">' +
      '        </div>' +
      '        <div class="form-group" style="flex:1;">' +
      '          <label class="form-label" data-i18n="cal.event.status">Stato</label>' +
      '          <select class="form-select" id="evm-status">' +
      '            <option value="confirmed" data-i18n="cal.event.status.confirmed">Confermato</option>' +
      '            <option value="tentative" data-i18n="cal.event.status.tentative">Provvisorio</option>' +
      '            <option value="cancelled" data-i18n="cal.event.status.cancelled">Annullato</option>' +
      '          </select>' +
      '        </div>' +
      '      </div>' +
      '      <div class="form-group">' +
      '        <label class="form-label" data-i18n="cal.event.link">Link riunione</label>' +
      '        <input class="form-input" id="evm-url" type="url">' +
      '      </div>' +
      '    </div>' +
      '    <div class="modal-footer" style="display:flex;justify-content:space-between;gap:8px;">' +
      '      <button class="btn btn-ghost btn-sm" type="button" id="evm-delete" style="color:#ef4444;" data-i18n="cal.event.delete">Elimina</button>' +
      '      <div style="display:flex;gap:8px;">' +
      '        <button class="btn btn-secondary btn-sm" type="button" onclick="closeModal(\'' + MODAL_ID + '\')" data-i18n="cal.event.cancel">Annulla</button>' +
      '        <button class="btn btn-primary btn-sm" type="button" id="evm-save" data-i18n="cal.event.save">Salva</button>' +
      '      </div>' +
      '    </div>' +
      '  </div>' +
      '</div>';
    var wrap = document.createElement('div');
    wrap.innerHTML = html;
    document.body.appendChild(wrap.firstElementChild);
    document.getElementById('evm-save').addEventListener('click', _onSave);
    document.getElementById('evm-delete').addEventListener('click', _onDelete);
    document.getElementById('evm-allday').addEventListener('change', _syncAllDay);
  }

  function _syncAllDay() {
    var isAll = document.getElementById('evm-allday').checked;
    ['evm-start', 'evm-end'].forEach(function (idf) {
      document.getElementById(idf).type = isAll ? 'date' : 'datetime-local';
    });
  }

  function _toLocalInput(iso, dateOnly) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    var pad = function (n) { return String(n).padStart(2, '0'); };
    var s = d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
    return dateOnly ? s : s + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }

  function openEventModal(opts) {
    opts = opts || {};
    _ensureModal();
    _ctx = { id: null, onSaved: opts.onSaved || null };
    var ev = opts.event || null;
    var pf = opts.prefill || {};
    var isEdit = !!(ev && ev.id);
    _ctx.id = isEdit ? ev.id : null;

    document.getElementById('evm-title').setAttribute('data-i18n', isEdit ? 'cal.event.edit' : 'cal.event.new');
    document.getElementById('evm-id').value = isEdit ? ev.id : '';
    var allday = isEdit ? !!ev.all_day : false;
    document.getElementById('evm-allday').checked = allday;
    _syncAllDay();
    document.getElementById('evm-field-title').value = isEdit ? (ev.title || '') : '';
    document.getElementById('evm-location').value = isEdit ? (ev.location || '') : '';
    document.getElementById('evm-url').value = isEdit ? (ev.meeting_url || '') : '';
    document.getElementById('evm-status').value = isEdit ? (ev.status || 'confirmed') : 'confirmed';

    var startIso = isEdit ? ev.start : (pf.start || null);
    var endIso = isEdit ? ev.end : (pf.end || null);
    var startVal = _toLocalInput(startIso, allday) || _toLocalInput(new Date().toISOString(), allday);
    document.getElementById('evm-start').value = startVal;
    document.getElementById('evm-end').value = _toLocalInput(endIso, allday) || startVal;

    var aid = isEdit ? ev.acquisition_id : pf.acquisition_id;
    var cid = isEdit ? ev.client_id : pf.client_id;
    var pid = isEdit ? ev.project_id : pf.project_id;
    document.getElementById('evm-acquisition-id').value = aid || '';
    document.getElementById('evm-client-id').value = cid || '';
    document.getElementById('evm-project-id').value = pid || '';
    var linked = document.getElementById('evm-linked');
    if (aid || cid || pid) {
      var ref = aid ? ('#' + aid) : (cid ? ('#' + cid) : ('#' + pid));
      linked.textContent = _T('cal.event.linkedTo') + ' ' + ref;
      linked.style.display = 'block';
    } else {
      linked.style.display = 'none';
    }

    document.getElementById('evm-delete').style.display = isEdit ? 'inline-block' : 'none';

    if (window.applyI18n) applyI18n(document.getElementById(MODAL_ID));
    openModal(MODAL_ID);
  }

  function _onSave() {
    var title = document.getElementById('evm-field-title').value.trim();
    if (!title) { if (window.toast) toast(_T('cal.event.err.title'), 'error'); return; }
    var allday = document.getElementById('evm-allday').checked;
    var start = document.getElementById('evm-start').value;
    var end = document.getElementById('evm-end').value;
    if (!start) { if (window.toast) toast(_T('cal.event.err.title'), 'error'); return; }
    if (!end) end = start;
    if (!allday && end < start) { if (window.toast) toast(_T('cal.event.err.range'), 'error'); return; }

    var fd = new FormData();
    fd.append('title', title);
    fd.append('start_at', start);
    fd.append('end_at', end);
    fd.append('all_day', allday ? '1' : '0');
    fd.append('location', document.getElementById('evm-location').value.trim());
    fd.append('meeting_url', document.getElementById('evm-url').value.trim());
    fd.append('status', document.getElementById('evm-status').value);
    var aid = document.getElementById('evm-acquisition-id').value;
    var cid = document.getElementById('evm-client-id').value;
    var pid = document.getElementById('evm-project-id').value;
    if (aid) fd.append('acquisition_id', aid);
    if (cid) fd.append('client_id', cid);
    if (pid) fd.append('project_id', pid);

    var id = _ctx.id;
    var url = '/calendar/api/events' + (id ? '/' + id : '');
    fetch(url, { method: id ? 'PUT' : 'POST', body: fd }).then(function (r) {
      if (!r.ok) { if (window.toast) toast(_T('common.error'), 'error'); return; }
      if (window.toast) toast(_T('cal.event.saved'), 'success');
      closeModal(MODAL_ID);
      if (_ctx.onSaved) _ctx.onSaved();
    });
  }

  function _onDelete() {
    var id = _ctx.id;
    if (!id) return;
    if (!confirm(_T('cal.event.deleteConfirm'))) return;
    fetch('/calendar/api/events/' + id, { method: 'DELETE' }).then(function (r) {
      if (!r.ok) { if (window.toast) toast(_T('common.error'), 'error'); return; }
      closeModal(MODAL_ID);
      if (_ctx.onSaved) _ctx.onSaved();
    });
  }

  window.openEventModal = openEventModal;
})();
```

- [ ] **Step 5: Run i18n test + JS syntax check**

Run: `.venv/Scripts/python.exe -m pytest tests/test_calendar_editing.py::test_i18n_has_event_modal_keys -v`
Expected: PASS.
Run: `node --check app/static/js/event_modal.js`
Expected: nessun output (sintassi OK).

- [ ] **Step 6: Commit**

```bash
git add app/static/js/event_modal.js app/static/js/i18n.js tests/test_calendar_editing.py
git commit -F <msgfile>
# "feat(calendar): modal evento condiviso event_modal.js + i18n"
```

---

### Task 2: `calendar_page.js` — vista settimana + apertura modal su click/select/resize

**Files:**
- Modify: `app/static/js/calendar_page.js` (riscrittura completa)
- Modify: `app/templates/pages/calendar.html` (include `event_modal.js` nello `{% block scripts %}`)
- Test: `tests/test_calendar_editing.py` (parte pagina)

**Interfaces:**
- Consumes: `window.openEventModal` (Task 1); API `/calendar/api/events` (GET/PUT).
- Produces: pagina `/calendar` che include `event_modal.js`; nessuna funzione globale nuova richiesta da altri task.

- [ ] **Step 1: Write the failing test**

```python
# aggiungi a tests/test_calendar_editing.py
from tests.test_calendar_api import client  # noqa: F401


def test_calendar_page_includes_event_modal(client):
    c, _ = client
    html = c.get("/calendar").text
    assert "event_modal.js" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_calendar_editing.py::test_calendar_page_includes_event_modal -v`
Expected: FAIL (`event_modal.js` non incluso).

- [ ] **Step 3: Include `event_modal.js` in `calendar.html`**

In `app/templates/pages/calendar.html`, dentro `{% block scripts %}`, PRIMA di `calendar_page.js`:

```html
<script src="/static/js/event_modal.js?v={{ app_version }}"></script>
```

- [ ] **Step 4: Rewrite `calendar_page.js`**

Sostituisci l'intero contenuto di `app/static/js/calendar_page.js` con:

```javascript
// app/static/js/calendar_page.js — Fase B.1: vista settimana + editing via modal condiviso
let _cal = null;

function calScope() {
  const s = document.getElementById('cal-scope');
  return s ? s.value : 'team';
}

async function calFetchEvents(info, success, failure) {
  try {
    const url = '/calendar/api/events?start=' + encodeURIComponent(info.startStr) +
                '&end=' + encodeURIComponent(info.endStr) + '&scope=' + calScope();
    const r = await fetch(url);
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    const evs = (data.events || []).map(e => ({
      id: e.id, title: e.title, start: e.start, end: e.end, allDay: e.all_day,
      extendedProps: {
        source: e.source, description: e.description, location: e.location,
        meeting_url: e.meeting_url, status: e.status,
        acquisition_id: e.acquisition_id, client_id: e.client_id, project_id: e.project_id
      }
    }));
    (data.markers || []).forEach(m => evs.push({
      title: '• ' + m.title, start: m.date, allDay: true, display: 'background',
      classNames: ['cal-marker'], editable: false, extendedProps: { marker: m.kind }
    }));
    success(evs);
  } catch (e) { failure(e); }
}

// Rimappa un evento FullCalendar → oggetto compatibile con openEventModal.
function _fcEventToObj(fc) {
  const p = fc.extendedProps || {};
  return {
    id: fc.id, title: fc.title, all_day: fc.allDay,
    start: fc.start ? fc.start.toISOString() : null,
    end: fc.end ? fc.end.toISOString() : null,
    location: p.location || '', meeting_url: p.meeting_url || '',
    status: p.status || 'confirmed', description: p.description || '',
    acquisition_id: p.acquisition_id || null, client_id: p.client_id || null,
    project_id: p.project_id || null
  };
}

function calNewEvent(prefill) {
  window.openEventModal({ prefill: prefill || {}, onSaved: () => _cal && _cal.refetchEvents() });
}

document.addEventListener('DOMContentLoaded', function () {
  const root = document.getElementById('calendar-root');
  if (!root || typeof FullCalendar === 'undefined') return;
  const lang = (window.MF_CURRENT_LANG || localStorage.getItem('mf_lang') || 'it');
  _cal = new FullCalendar.Calendar(root, {
    initialView: 'timeGridWeek',
    locale: lang,
    headerToolbar: { left: 'prev,next today', center: 'title', right: 'dayGridMonth,timeGridWeek,timeGridDay,listWeek' },
    editable: true,
    selectable: true,
    nowIndicator: true,
    allDaySlot: true,
    slotMinTime: '07:00:00',
    slotMaxTime: '22:00:00',
    slotDuration: '00:30:00',
    expandRows: true,
    eventTimeFormat: { hour: '2-digit', minute: '2-digit', hour12: false },
    events: calFetchEvents,
    eventClick: function (info) {
      if (info.event.extendedProps.marker) return;
      info.jsEvent.preventDefault();
      window.openEventModal({ event: _fcEventToObj(info.event), onSaved: () => _cal.refetchEvents() });
    },
    select: function (info) {
      window.openEventModal({
        prefill: { start: info.startStr, end: info.endStr },
        onSaved: () => _cal.refetchEvents()
      });
      _cal.unselect();
    },
    dateClick: function (info) {
      window.openEventModal({
        prefill: { start: info.dateStr + (info.allDay ? '' : 'T09:00'), end: info.dateStr + (info.allDay ? '' : 'T10:00') },
        onSaved: () => _cal.refetchEvents()
      });
    },
    eventDrop: function (info) {
      if (info.event.extendedProps.marker) { info.revert(); return; }
      const fd = new FormData();
      fd.append('start_at', info.event.start.toISOString());
      if (info.event.end) fd.append('end_at', info.event.end.toISOString());
      fetch('/calendar/api/events/' + info.event.id, { method: 'PUT', body: fd })
        .then(r => { if (!r.ok) { info.revert(); if (window.toast) toast(mfT('common.error'), 'error'); } });
    },
    eventResize: function (info) {
      if (info.event.extendedProps.marker) { info.revert(); return; }
      const fd = new FormData();
      fd.append('start_at', info.event.start.toISOString());
      if (info.event.end) fd.append('end_at', info.event.end.toISOString());
      fetch('/calendar/api/events/' + info.event.id, { method: 'PUT', body: fd })
        .then(r => { if (!r.ok) { info.revert(); if (window.toast) toast(mfT('common.error'), 'error'); } });
    },
  });
  _cal.render();
  const sc = document.getElementById('cal-scope');
  if (sc) sc.addEventListener('change', () => _cal.refetchEvents());
});
```

Nota: il bottone toolbar "Nuovo appuntamento" in `calendar.html` chiama già `calNewEvent()` (invariato, ora apre il modal).

- [ ] **Step 5: Run test + JS syntax check + grep guard**

Run: `.venv/Scripts/python.exe -m pytest tests/test_calendar_editing.py::test_calendar_page_includes_event_modal -v`
Expected: PASS.
Run: `node --check app/static/js/calendar_page.js`
Expected: nessun errore.
Run: `grep -n "openEventModal\|_fcEventToObj" app/static/js/calendar_page.js`
Expected: referenziate; `openEventModal` proviene da `event_modal.js` (non ridefinita qui).

- [ ] **Step 6: Commit**

```bash
git add app/static/js/calendar_page.js app/templates/pages/calendar.html tests/test_calendar_editing.py
git commit -F <msgfile>
# "feat(calendar): vista settimana + editing eventi via modal (click/select/resize)"
```

---

### Task 3: Tab Appuntamenti acquisizioni — righe leggibili + edit/elimina + modal

**Files:**
- Modify: `app/templates/pages/acquisitions.html` (funzioni `acqDetLoadCalendarEvents`/`acqNewAppointment` ~riga 818-855; include `event_modal.js` nel `{% block scripts %}` ~riga 467; eventuale CSS badge)
- Modify: `app/static/js/i18n.js` (chiave `acq.appt.allDayLabel` per "tutto il giorno" nella riga lista)
- Test: `tests/test_calendar_editing.py` (parte acquisizioni)

**Interfaces:**
- Consumes: `window.openEventModal` (Task 1); `GET /calendar/api/events?acquisition_id=`; helper `api`/`escapeHtml`/`mfT`/`applyI18n`.
- Produces: tab Appuntamenti con righe leggibili + ✎/🗑; `acqDetLoadCalendarEvents(aid)` invariato come nome (ricarica lista), `acqNewAppointment()` apre il modal.

- [ ] **Step 1: Write the failing test**

```python
# aggiungi a tests/test_calendar_editing.py
def test_acquisitions_includes_event_modal(client):
    c, _ = client
    html = c.get("/acquisitions").text
    assert "event_modal.js" in html
    assert 'id="det-tab-calendar"' in html  # tab ancora presente
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_calendar_editing.py::test_acquisitions_includes_event_modal -v`
Expected: FAIL (`event_modal.js` non incluso).

- [ ] **Step 3: Add i18n key**

In `app/static/js/i18n.js`, vicino a `acq.detail.noAppointments`:

```javascript
  'acq.appt.allDayLabel': {it: 'Tutto il giorno', en: 'All day', fr: 'Toute la journee', de: 'Ganztags', es: 'Todo el dia'},
```

- [ ] **Step 4: Include `event_modal.js` in `acquisitions.html`**

In `app/templates/pages/acquisitions.html`, all'inizio di `{% block scripts %}` (~riga 467, prima di `<script>`):

```html
<script src="/static/js/event_modal.js?v={{ app_version }}"></script>
```

- [ ] **Step 5: Replace the two functions**

In `app/templates/pages/acquisitions.html`, sostituisci `acqDetLoadCalendarEvents` e `acqNewAppointment` (blocco introdotto in α.172.240) con:

```javascript
function _apptStatusBadge(status) {
  var map = {
    confirmed: { c: '#4ade80', k: 'cal.event.status.confirmed' },
    tentative: { c: '#fbbf24', k: 'cal.event.status.tentative' },
    cancelled: { c: '#ef4444', k: 'cal.event.status.cancelled' }
  };
  var m = map[status] || map.confirmed;
  return '<span style="font-size:10px;padding:1px 6px;border-radius:8px;border:1px solid ' + m.c +
         ';color:' + m.c + ';margin-left:6px;">' + escapeHtml(mfT(m.k)) + '</span>';
}

function _apptWhen(ev) {
  if (!ev.start) return '';
  var s = new Date(ev.start);
  if (ev.all_day) return s.toLocaleDateString() + ' · ' + mfT('acq.appt.allDayLabel');
  var out = s.toLocaleDateString() + ' ' + s.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  if (ev.end) {
    var e = new Date(ev.end);
    out += '–' + e.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  return out;
}

async function acqDetLoadCalendarEvents(aid) {
  try {
    const r = await api('GET', '/calendar/api/events?acquisition_id=' + aid);
    const list = document.getElementById('det-calendar-list');
    const items = (r && r.events) || [];
    if (!items.length) {
      list.innerHTML = '<div class="text-muted" style="font-size:12px;padding:8px 0;" data-i18n="acq.detail.noAppointments">' + mfT('acq.detail.noAppointments') + '</div>';
      return;
    }
    list.innerHTML = '';
    items.forEach(ev => {
      const el = document.createElement('div');
      el.className = 'acq-activity-item';
      el.style.display = 'flex';
      el.style.justifyContent = 'space-between';
      el.style.alignItems = 'flex-start';
      el.style.gap = '8px';
      const safeUrl = (ev.meeting_url && /^https?:\/\//i.test(ev.meeting_url)) ? ev.meeting_url : null;
      const left =
        '<div>' +
        '<div><strong>' + escapeHtml(ev.title || '') + '</strong>' + _apptStatusBadge(ev.status) + '</div>' +
        '<div style="color:var(--text3);font-size:11px;margin-top:2px;">' + escapeHtml(_apptWhen(ev)) + '</div>' +
        (ev.location ? '<div style="color:var(--text3);font-size:11px;">' + escapeHtml(ev.location) + '</div>' : '') +
        (safeUrl ? '<div style="font-size:11px;"><a href="' + escapeHtml(safeUrl) + '" target="_blank" rel="noopener">' + escapeHtml(safeUrl) + '</a></div>' : '') +
        '</div>';
      const right =
        '<div style="display:flex;gap:4px;flex-shrink:0;">' +
        '<button class="btn btn-ghost btn-icon btn-sm" type="button" title="' + escapeHtml(mfT('cal.event.edit')) + '" data-appt-edit="' + ev.id + '">✎</button>' +
        '<button class="btn btn-ghost btn-icon btn-sm" type="button" style="color:#ef4444;" title="' + escapeHtml(mfT('cal.event.delete')) + '" data-appt-del="' + ev.id + '">🗑</button>' +
        '</div>';
      el.innerHTML = left + right;
      el.querySelector('[data-appt-edit]').addEventListener('click', function () {
        window.openEventModal({ event: ev, prefill: { acquisition_id: aid }, onSaved: () => acqDetLoadCalendarEvents(aid) });
      });
      el.querySelector('[data-appt-del]').addEventListener('click', function () {
        if (!confirm(mfT('cal.event.deleteConfirm'))) return;
        fetch('/calendar/api/events/' + ev.id, { method: 'DELETE' }).then(function (resp) {
          if (resp.ok) acqDetLoadCalendarEvents(aid);
          else if (window.toast) toast(mfT('common.error'), 'error');
        });
      });
      list.appendChild(el);
    });
  } catch (e) {}
}

function acqNewAppointment() {
  if (!_acqCurrentId) return;
  window.openEventModal({ prefill: { acquisition_id: _acqCurrentId }, onSaved: () => acqDetLoadCalendarEvents(_acqCurrentId) });
}
```

(Nota: `data-appt-edit`/`data-appt-del` + `addEventListener` invece di `onclick` con JSON — rispetta la trappola "no JSON.stringify in onclick". `escapeHtml`/`mfT`/`api`/`openEventModal` NON ridefinite.)

- [ ] **Step 6: Run test + grep guard**

Run: `.venv/Scripts/python.exe -m pytest tests/test_calendar_editing.py -v`
Expected: tutti PASS (i18n + calendar page + acquisitions).
Run: `.venv/Scripts/python.exe -m pytest tests/test_acquisitions_calendar_tab.py -v`
Expected: PASS (regressione tab invariata).
Run: `grep -n "openEventModal\|acqDetLoadCalendarEvents\|acqNewAppointment" app/templates/pages/acquisitions.html`
Expected: definite/referenziate; `openEventModal` da event_modal.js.

- [ ] **Step 7: Commit**

```bash
git add app/templates/pages/acquisitions.html app/static/js/i18n.js tests/test_calendar_editing.py
git commit -F <msgfile>
# "feat(calendar): tab Appuntamenti leggibile + edit/elimina via modal condiviso"
```

---

### Task 4: Chiusura fase — bump versione + smoke + suite

**Files:**
- Modify: `app/main.py` (versione `.240` → `.241`), `CHANGELOG.md`, `docs/STATO.md`

**Interfaces:**
- Consumes: tutto quanto sopra.
- Produces: versione `3.5.0-alpha.172.241`.

- [ ] **Step 1: Bump version**

In `app/main.py`: `version="3.5.0-alpha.172.240"` → `"3.5.0-alpha.172.241"`.

- [ ] **Step 2: CHANGELOG**

In `CHANGELOG.md`, nuova voce in cima:

```markdown
## v3.5.0-alpha.172.241 — Fase B.1 Calendario: editing eventi + leggibilità (6 lug 2026)

- **Modal evento condiviso** (`event_modal.js`): crea/modifica/elimina appuntamenti (titolo, inizio/fine, tutto-il-giorno, luogo, link, stato, collegamenti). Unica fonte di verità per la scrittura eventi, usato sia in `/calendar` sia nel tab Appuntamenti acquisizioni.
- **Calendario vista settimana** default (griglia oraria 07-22, indicatore ora, formato 24h): risolve accavallamenti e orari illeggibili. Click/selezione → nuovo evento; click su evento → modifica; drag/resize → aggiorna orari.
- **Tab Appuntamenti acquisizioni** leggibile: riga con titolo, fascia oraria, luogo, badge stato, link (solo http(s)), pulsanti modifica/elimina.
- i18n 5 lingue. Nessuna modifica backend.
```

- [ ] **Step 3: STATO**

In `docs/STATO.md`: versione corrente → `.241`; aggiungi sezione `### α.172.241 ✅ (Fase B.1 — 6 lug)` con i punti sopra; **Prossimo step** → Fase C sync Google (invariato).

- [ ] **Step 4: Full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: tutti verdi (1050 + nuovi). Se un test preesistente rompe, correggilo minimamente e annota.

- [ ] **Step 5: Smoke browser (Playwright)**

Avvia server (`start.bat` o `.venv/Scripts/python.exe run.py`), poi verifica manualmente/Playwright:
- `/calendar` in vista settimana: seleziona un intervallo → modal → salva evento con orari → riappare in griglia con orario leggibile; ri-click → modifica titolo → salva; drag → orario aggiornato; elimina.
- `/acquisitions` → trattativa → tab Appuntamenti → "Nuovo appuntamento" → modal → salva; riga leggibile con ✎/🗑; edit e delete funzionano.
- Console browser: 0 errori.

- [ ] **Step 6: Commit**

```bash
git add app/main.py CHANGELOG.md docs/STATO.md
git commit -F <msgfile>
# "chore(calendar): Fase B.1 v3.5.0-alpha.172.241 (editing + leggibilità)"
```

---

## Self-Review

**1. Spec coverage:**
- Modal condiviso create/edit/delete (spec §Architettura.1) → Task 1 ✓
- Vista settimana + eventClick/select/resize + rimozione prompt (spec §2) → Task 2 ✓
- Tab acquisizioni righe leggibili + ✎/🗑 + nuovo via modal (spec §3) → Task 3 ✓
- i18n 5 lingue (spec §4) → Task 1 + Task 3 ✓
- Anti-XSS meeting_url (spec §Vincoli) → Task 3 (regex http(s)) ✓
- Nessuna modifica backend (spec §Vincoli) → confermato, nessun task tocca `calendar.py` ✓
- Testing pytest smoke + node --check + smoke browser (spec §Testing) → Task 1/2/3/4 ✓

**2. Placeholder scan:** nessun TBD/TODO; ogni step di codice mostra il codice.

**3. Type consistency:** `openEventModal({event, prefill, onSaved})`, `_fcEventToObj`, `acqDetLoadCalendarEvents(aid)`, `acqNewAppointment()`, chiavi i18n `cal.event.*` coerenti tra Task 1/2/3. Campi evento serializzati (`start`/`end`/`all_day`/`status`/`meeting_url`/`acquisition_id`) coerenti col backend α.172.240 e con `_fcEventToObj`.

## Note

- Il modal è iniettato una sola volta (`_ensureModal` guardato da `getElementById`), quindi caricare `event_modal.js` su entrambe le pagine non crea duplicati.
- `datetime-local`/`date` inviano stringhe ISO naive → `_parse_dt` backend (`datetime.fromisoformat`) le accetta (incluso il formato solo-data per all_day).
- Timezone: coerente con Fase B (naive/locale). Normalizzazione tz fuori scope.
