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
    // Overlay Google: sempre fetchato, filtrato per calendario visibile (sidebar).
    {
      try {
        const gr = await fetch('/calendar/api/google-overlay?start=' +
          encodeURIComponent(info.startStr) + '&end=' + encodeURIComponent(info.endStr));
        if (gr.ok) {
          const gd = await gr.json();
          (gd.events || []).filter(g => !hidden.has(g.calendar_id)).forEach(g => evs.push({
            id: 'g:' + g.calendar_id + ':' + g.id,
            title: g.title, start: g.start, end: g.end, allDay: g.all_day,
            editable: !g.read_only,
            classNames: g.read_only ? ['cal-google', 'cal-google-ro'] : ['cal-google'],
            backgroundColor: g.color || undefined,
            borderColor: g.color || undefined,
            extendedProps: {
              google: true, read_only: g.read_only,
              google_calendar_id: g.calendar_id, google_event_id: g.id,
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

// Evento Google esistente → oggetto per openEventModal (modalità google).
function _fcGoogleToObj(fc) {
  const p = fc.extendedProps || {};
  return {
    id: fc.id, title: fc.title, all_day: fc.allDay,
    start: fc.start ? fc.start.toISOString() : null,
    end: fc.end ? fc.end.toISOString() : null,
    location: p.location || '', status: p.status || 'confirmed',
    description: p.description || '', attendees: p.attendees || [],
    google_calendar_id: p.google_calendar_id, google_event_id: p.google_event_id
  };
}

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
  fd.append('all_day', info.event.allDay ? '1' : '0');
  let url = '/calendar/api/events/' + info.event.id;
  if (p.google) {
    if (p.read_only) { info.revert(); return; }
    fd.append('calendar_id', p.google_calendar_id);
    fd.append('event_id', p.google_event_id);
    url = '/calendar/api/google-event';
  }
  fetch(url, { method: 'PUT', body: fd })
    .then(r => { if (!r.ok) { info.revert(); if (window.toast) toast(mfT('common.error'), 'error'); } });
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
      info.jsEvent.preventDefault();
      if (p.google) {
        if (p.read_only) { if (window.toast) toast(mfT('cal.google.readonly'), 'error'); return; }
        window.openEventModal({ event: _fcGoogleToObj(info.event), onSaved: () => _cal.refetchEvents() });
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
