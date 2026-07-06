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
    // Overlay Google read-only (best-effort, non blocca il calendario)
    const showG = document.getElementById('cal-show-google');
    if (showG && showG.checked) {
      try {
        const gr = await fetch('/calendar/api/google-overlay?start=' +
          encodeURIComponent(info.startStr) + '&end=' + encodeURIComponent(info.endStr));
        if (gr.ok) {
          const gd = await gr.json();
          (gd.events || []).forEach(g => evs.push({
            title: g.title, start: g.start, end: g.end, allDay: g.all_day,
            editable: false, classNames: ['cal-google'], extendedProps: { google: true }
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
    acquisition_id: p.acquisition_id || null, client_id: p.client_id || null,
    project_id: p.project_id || null
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
  if (info.event.extendedProps.marker) { info.revert(); return; }
  const fd = new FormData();
  fd.append('start_at', info.event.start.toISOString());
  if (info.event.end) fd.append('end_at', info.event.end.toISOString());
  fetch('/calendar/api/events/' + info.event.id, { method: 'PUT', body: fd })
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
      if (info.event.extendedProps.marker || info.event.extendedProps.google) return;
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
  const shg = document.getElementById('cal-show-google');
  if (shg) shg.addEventListener('change', () => _cal.refetchEvents());
});
