// app/static/js/calendar_page.js — Fase B FullCalendar wiring
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
      extendedProps: { source: e.source, location: e.location, meeting_url: e.meeting_url,
                       acquisition_id: e.acquisition_id, client_id: e.client_id }
    }));
    (data.markers || []).forEach(m => evs.push({
      title: '• ' + m.title, start: m.date, allDay: true, display: 'background',
      classNames: ['cal-marker'], editable: false, extendedProps: { marker: m.kind }
    }));
    success(evs);
  } catch (e) { failure(e); }
}

async function calSaveEvent(fd, id) {
  const method = id ? 'PUT' : 'POST';
  const url = '/calendar/api/events' + (id ? '/' + id : '');
  const r = await fetch(url, { method, body: fd });
  if (!r.ok) { if (window.toast) toast('Errore salvataggio', 'error'); return null; }
  return r.json();
}

function calNewEvent(prefill) {
  prefill = prefill || {};
  const title = prompt(window.mfT ? mfT('cal.event.title') : 'Titolo');
  if (!title) return;
  const start = prefill.start || new Date().toISOString().slice(0, 16);
  const end = prefill.end || start;
  const fd = new FormData();
  fd.append('title', title);
  fd.append('start_at', start);
  fd.append('end_at', end);
  if (prefill.acquisition_id) fd.append('acquisition_id', prefill.acquisition_id);
  if (prefill.client_id) fd.append('client_id', prefill.client_id);
  calSaveEvent(fd, null).then(() => _cal && _cal.refetchEvents());
}

document.addEventListener('DOMContentLoaded', function () {
  const root = document.getElementById('calendar-root');
  if (!root || typeof FullCalendar === 'undefined') return;
  const lang = (window.MF_CURRENT_LANG || localStorage.getItem('mf_lang') || 'it');
  _cal = new FullCalendar.Calendar(root, {
    initialView: 'dayGridMonth',
    locale: lang,
    headerToolbar: { left: 'prev,next today', center: 'title', right: 'dayGridMonth,timeGridWeek,timeGridDay,listWeek' },
    editable: true,
    events: calFetchEvents,
    dateClick: function (info) { calNewEvent({ start: info.dateStr + 'T09:00', end: info.dateStr + 'T10:00' }); },
    eventDrop: function (info) {
      if (info.event.extendedProps.marker) { info.revert(); return; }
      const fd = new FormData();
      fd.append('start_at', info.event.start.toISOString());
      if (info.event.end) fd.append('end_at', info.event.end.toISOString());
      calSaveEvent(fd, info.event.id);
    },
  });
  _cal.render();
  const sc = document.getElementById('cal-scope');
  if (sc) sc.addEventListener('change', () => _cal.refetchEvents());
});
