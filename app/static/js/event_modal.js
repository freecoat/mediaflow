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

  // Il pannello di conferma eliminazione non deve sopravvivere alla riapertura
  // del modale su un altro evento (riapparirebbe già "armato").
  function _resetExternalDeletePanel() {
    var old = document.getElementById('evm-external-delete-confirm');
    if (old) old.remove();
  }

  function openEventModal(opts) {
    opts = opts || {};
    _ensureModal();
    _resetExternalDeletePanel();
    _ctx = { id: null, external: opts.external || null, etag: null,
             onSaved: opts.onSaved || null };
    if (_ctx.external) { _openExternal(_ctx.external); return; }
    _toggleClaqoOnlyFields(true);  // ripristina i campi Claqo-only dopo un evento Google
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

  // ── Modalità esterna: evento Google reale, nessuna copia locale ──────────
  // I campi che Google non mappa su Claqo (stato, link riunione, collegamenti a
  // trattativa/progetto) sono nascosti invece che mostrati vuoti e ignorati.
  function _openExternal(ext) {
    fetch('/calendar/api/google-events/' + encodeURIComponent(ext.calendar_id) + '/' +
          encodeURIComponent(ext.event_id))
      .then(function (r) {
        if (!r.ok) { if (window.toast) toast(_T('cal.google.notEditable'), 'error'); return null; }
        return r.json();
      })
      .then(function (ev) {
        if (!ev) return;
        _ctx.etag = ev.etag || null;
        document.getElementById('evm-title').setAttribute('data-i18n', 'cal.event.edit');
        document.getElementById('evm-id').value = '';
        document.getElementById('evm-allday').checked = !!ev.all_day;
        _syncAllDay();
        document.getElementById('evm-field-title').value = ev.title || '';
        document.getElementById('evm-location').value = '';
        var startVal = _toLocalInput(ev.start, ev.all_day);
        document.getElementById('evm-start').value = startVal;
        document.getElementById('evm-end').value = _toLocalInput(ev.end, ev.all_day) || startVal;
        _toggleClaqoOnlyFields(false);
        var linked = document.getElementById('evm-linked');
        linked.textContent = _T('cal.google.source');
        linked.style.display = 'block';
        document.getElementById('evm-delete').style.display = 'inline-block';
        if (window.applyI18n) applyI18n(document.getElementById(MODAL_ID));
        openModal(MODAL_ID);
      });
  }

  // Mostra/nasconde i campi che esistono solo nel modello Claqo.
  function _toggleClaqoOnlyFields(show) {
    ['evm-status', 'evm-url'].forEach(function (idf) {
      var el = document.getElementById(idf);
      var grp = el && el.closest('.form-group');
      if (grp) grp.style.display = show ? '' : 'none';
    });
  }

  function _onSaveExternal() {
    var title = document.getElementById('evm-field-title').value.trim();
    if (!title) { if (window.toast) toast(_T('cal.event.err.title'), 'error'); return; }
    var allday = document.getElementById('evm-allday').checked;
    var start = document.getElementById('evm-start').value;
    var end = document.getElementById('evm-end').value || start;
    if (!allday && end < start) { if (window.toast) toast(_T('cal.event.err.range'), 'error'); return; }
    var fd = new FormData();
    fd.append('title', title);
    fd.append('start_at', start);
    fd.append('end_at', end);
    fd.append('all_day', allday ? '1' : '0');
    if (_ctx.etag) fd.append('etag', _ctx.etag);
    fetch(_externalUrl(), { method: 'PUT', body: fd }).then(function (r) {
      if (r.status === 409) {
        // L'evento e' cambiato su Google dopo che l'abbiamo letto: non sovrascriviamo.
        if (window.toast) toast(_T('cal.google.conflict'), 'error');
        closeModal(MODAL_ID);
        if (_ctx.onSaved) _ctx.onSaved();
        return;
      }
      if (!r.ok) { if (window.toast) toast(_T('common.error'), 'error'); return; }
      if (window.toast) toast(_T('cal.event.saved'), 'success');
      closeModal(MODAL_ID);
      if (_ctx.onSaved) _ctx.onSaved();
    });
  }

  function _externalUrl() {
    return '/calendar/api/google-events/' + encodeURIComponent(_ctx.external.calendar_id) +
           '/' + encodeURIComponent(_ctx.external.event_id);
  }

  // Conferma a due passi: su Google la cancellazione e' definitiva, non c'e'
  // soft-delete da cui recuperare. Un confirm() nativo e' troppo poco.
  function _onDeleteExternalStep1() {
    var existing = document.getElementById('evm-external-delete-confirm');
    if (existing) { existing.style.display = 'block'; return; }
    var panel = document.createElement('div');
    panel.id = 'evm-external-delete-confirm';
    panel.style.cssText = 'margin-top:8px;padding:8px;border:1px solid #ef4444;' +
                          'border-radius:6px;font-size:12px;flex-basis:100%;';
    panel.innerHTML =
      '<p style="margin:0 0 8px;" data-i18n="cal.google.deleteWarning">' +
      'Eliminazione definitiva da Google Calendar, non recuperabile.</p>' +
      '<button class="btn btn-danger btn-sm" type="button" id="evm-external-delete-confirm-btn" ' +
      'data-i18n="cal.google.deleteConfirmBtn">Elimina definitivamente da Google</button>';
    document.getElementById('evm-delete').insertAdjacentElement('afterend', panel);
    if (window.applyI18n) applyI18n(panel);
    document.getElementById('evm-external-delete-confirm-btn')
      .addEventListener('click', _onDeleteExternalStep2);
  }

  function _onDeleteExternalStep2() {
    var fd = new FormData();
    if (_ctx.etag) fd.append('etag', _ctx.etag);
    fetch(_externalUrl(), { method: 'DELETE', body: fd }).then(function (r) {
      if (!r.ok) {
        if (window.toast) toast(_T(r.status === 409 ? 'cal.google.conflict' : 'common.error'), 'error');
        return;
      }
      closeModal(MODAL_ID);
      if (_ctx.onSaved) _ctx.onSaved();
    });
  }

  function _onSave() {
    if (_ctx.external) { _onSaveExternal(); return; }
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
    if (_ctx.external) { _onDeleteExternalStep1(); return; }
    var id = _ctx.id;
    if (!id) return;
    if (!confirm(_T('cal.event.deleteConfirm'))) return;  // locale = soft-delete, recuperabile
    fetch('/calendar/api/events/' + id, { method: 'DELETE' }).then(function (r) {
      if (!r.ok) { if (window.toast) toast(_T('common.error'), 'error'); return; }
      closeModal(MODAL_ID);
      if (_ctx.onSaved) _ctx.onSaved();
    });
  }

  window.openEventModal = openEventModal;
})();
