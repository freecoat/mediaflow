// app/static/js/calendar_page.js — Fase B.1: vista settimana + editing via modal condiviso
let _cal = null;

function calScope() {
  const s = document.getElementById('cal-scope');
  return s ? s.value : 'team';
}

// ── Visibilità calendari (localStorage: array di id NASCOSTI; 'claqo' = eventi locali) ──
function _calHidden() {
  try { return new Set(JSON.parse(localStorage.getItem('mf_cal_hidden') || '[]')); }
  catch (e) { return new Set(); }
}
function _calSetHidden(id, hidden) {
  const s = _calHidden();
  if (hidden) s.add(id); else s.delete(id);
  try { localStorage.setItem('mf_cal_hidden', JSON.stringify([...s])); } catch (e) { /* quota */ }
}

async function calLoadCalendars() {
  const box = document.getElementById('cal-list');
  if (!box) return;
  const hidden = _calHidden();
  const accent = getComputedStyle(document.documentElement).getPropertyValue('--accent') || '#6272f5';
  let rows = '<label class="cal-item"><input type="checkbox" data-cal-id="claqo"' +
    (hidden.has('claqo') ? '' : ' checked') + '>' +
    '<span class="cal-dot" style="background:' + accent.trim() + '"></span>' +
    '<span class="cal-item-name">' + mfT('cal.claqoCalendar') + '</span></label>';
  try {
    const d = await (await fetch('/calendar/api/google-calendars')).json();
    const cals = d.calendars || [];
    cals.forEach(function (c) {
      const color = c.color || '#888';
      rows += '<label class="cal-item"><input type="checkbox" data-cal-id="' + escapeHtml(c.id) + '"' +
        (hidden.has(c.id) ? '' : ' checked') + '>' +
        '<span class="cal-dot" style="background:' + escapeHtml(color) + '"></span>' +
        '<span class="cal-item-name">' + escapeHtml(c.summary) + '</span></label>';
    });
    if (!cals.length) rows += '<div class="cal-empty">' + mfT('cal.noCalendars') + '</div>';
  } catch (e) { /* best-effort */ }
  box.innerHTML = rows;
}

async function calFetchEvents(info, success, failure) {
  try {
    const url = '/calendar/api/events?start=' + encodeURIComponent(info.startStr) +
                '&end=' + encodeURIComponent(info.endStr) + '&scope=' + calScope();
    const r = await fetch(url);
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    const hidden = _calHidden();
    // Eventi locali (calendario "Claqo") — nascondibili dalla sidebar.
    const evs = hidden.has('claqo') ? [] : (data.events || []).map(e => ({
      id: e.id, title: e.title, start: e.start, end: e.end, allDay: e.all_day,
      classNames: e.external_event_id ? ['cal-synced'] : [],
      extendedProps: {
        source: e.source, description: e.description, location: e.location,
        meeting_url: e.meeting_url, status: e.status, sync_state: e.sync_state,
        acquisition_id: e.acquisition_id, client_id: e.client_id, project_id: e.project_id
      }
    }));
    (data.markers || []).forEach(m => evs.push({
      title: '• ' + m.title, start: m.date, allDay: true, display: 'background',
      classNames: ['cal-marker'], editable: false, extendedProps: { marker: m.kind }
    }));
    // Overlay Google (best-effort, non blocca il calendario). Editabile solo dove
    // il server lo concede: accessRole owner/writer + opt-in scope + non ricorrente.
    // Sempre fetchato: la visibilita' si sceglie per-calendario dalla sidebar
    // "I miei calendari", non piu' con un interruttore unico mostra/nascondi.
    {
      try {
        const gr = await fetch('/calendar/api/google-overlay?start=' +
          encodeURIComponent(info.startStr) + '&end=' + encodeURIComponent(info.endStr));
        if (gr.ok) {
          const gd = await gr.json();
          if (gd.error && window.toast) toast(mfT('cal.google.overlayError'), 'error');
          (gd.events || []).filter(g => !hidden.has(g.calendar_id)).forEach(g => evs.push({
            // id composito: gli id locali sono interi puri, nessuna collisione.
            id: 'g:' + g.calendar_id + ':' + g.id,
            title: g.title, start: g.start, end: g.end, allDay: g.all_day,
            // `editable` deciso dal server (accessRole + opt-in + non ricorrente):
            // non ricavarlo dal solo read_only, perde la regola dello scope.
            editable: !!g.editable,
            classNames: g.editable ? ['cal-google', 'cal-google-editable']
                                   : ['cal-google', 'cal-google-ro'],
            backgroundColor: g.color || undefined,
            borderColor: g.color || undefined,
            extendedProps: {
              google: true, editable: !!g.editable, read_only: !g.editable,
              calendar_id: g.calendar_id, event_id: g.id,
              // etag = versione dell'evento su Google: viaggia nel PUT come
              // If-Match. Va riaggiornato dopo ogni scrittura.
              etag: g.etag || null,
              description: g.description, location: g.location,
              status: g.status, attendees: g.attendees, calendar: g.calendar
            }
          }));
        }
      } catch (e) { /* overlay best-effort */ }
    }
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
    attendees: p.attendees || [],
    acquisition_id: p.acquisition_id || null, client_id: p.client_id || null,
    project_id: p.project_id || null
  };
}

// NB: gli eventi Google NON passano da un converter dell'overlay. Il modale li
// apre con `external:` e rifa' una GET: i dati dell'overlay possono essere vecchi
// di minuti, e salvare partendo da quelli rimanderebbe a Google valori stale.

function calNewEvent(prefill) {
  window.openEventModal({ prefill: prefill || {}, onSaved: () => _cal && _cal.refetchEvents() });
}

async function calSyncNow() {
  try {
    const r = await fetch('/calendar/api/sync', { method: 'POST' });
    const d = await r.json();
    if (r.ok && window.toast) {
      toast(mfT('cal.sync.done') + ': ' + (d.pushed || 0) + '↑ ' + (d.deleted || 0) + '✕' +
            (d.failed ? ' · ' + d.failed + ' ' + mfT('cal.sync.error') : ''), d.failed ? 'error' : 'success');
    } else if (!r.ok && window.toast) {
      toast(mfT('cal.sync.error'), 'error');
    }
  } catch (e) {
    if (window.toast) toast(mfT('cal.sync.error'), 'error');
  }
  if (_cal) _cal.refetchEvents();
}

function _calPutTimes(info) {
  const p = info.event.extendedProps;
  if (p.marker) { info.revert(); return; }
  const fd = new FormData();
  fd.append('start_at', info.event.start.toISOString());
  if (info.event.end) fd.append('end_at', info.event.end.toISOString());
  // If-Match: se l'evento e' cambiato su Google dopo il fetch dell'overlay, Google
  // risponde 412 -> 409 e non sovrascriviamo. Senza etag sarebbe last-write-wins.
  if (p.google && p.etag) fd.append('etag', p.etag);
  // Drag&drop instradato sulla sorgente: evento Google → API Google, locale → API locale.
  const url = p.google
    ? '/calendar/api/google-events/' + encodeURIComponent(p.calendar_id) + '/' +
      encodeURIComponent(p.event_id)
    : '/calendar/api/events/' + info.event.id;
  fetch(url, { method: 'PUT', body: fd }).then(async r => {
    if (r.ok) {
      // La PATCH ha prodotto una nuova versione: senza riallineare l'etag il drag
      // successivo dello stesso evento manderebbe quello vecchio -> 409 falso.
      if (p.google) {
        const d = await r.json().catch(() => null);
        if (d && d.event && d.event.etag) info.event.setExtendedProp('etag', d.event.etag);
      }
      return;
    }
    info.revert();
    if (window.toast) {
      // 409 = l'evento e' cambiato su Google nel frattempo (If-Match), non un errore generico.
      toast(mfT(r.status === 409 ? 'cal.google.conflict' : 'common.error'), 'error');
    }
    // Sul conflitto l'overlay in pagina e' per definizione stale: ricaricalo, cosi'
    // l'utente vede la versione vera e riparte da etag freschi.
    if (r.status === 409 && _cal) _cal.refetchEvents();
  });
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
      const p = info.event.extendedProps;
      if (p.marker) return;
      // Read-only: dirlo, invece di non fare nulla in silenzio.
      if (p.google && !p.editable) {
        if (window.toast) toast(mfT('cal.google.readonly'), 'error');
        return;
      }
      info.jsEvent.preventDefault();
      if (p.google) {
        // `external` (non `event`): il modale rifà una GET e mostra dati freschi.
        // Passare l'oggetto dell'overlay mostrerebbe partecipanti/descrizione stale.
        window.openEventModal({
          external: { calendar_id: p.calendar_id, event_id: p.event_id },
          onSaved: () => _cal.refetchEvents()
        });
        return;
      }
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
        prefill: {
          start: info.dateStr + (info.allDay ? '' : 'T09:00'),
          end: info.dateStr + (info.allDay ? '' : 'T10:00')
        },
        onSaved: () => _cal.refetchEvents()
      });
    },
    eventDrop: _calPutTimes,
    eventResize: _calPutTimes,
  });
  _cal.render();
  const sc = document.getElementById('cal-scope');
  if (sc) sc.addEventListener('change', () => _cal.refetchEvents());
  const list = document.getElementById('cal-list');
  if (list) list.addEventListener('change', function (ev) {
    const cb = ev.target.closest('[data-cal-id]');
    if (!cb) return;
    _calSetHidden(cb.getAttribute('data-cal-id'), !cb.checked);
    _cal.refetchEvents();
  });
  calLoadCalendars();
});
