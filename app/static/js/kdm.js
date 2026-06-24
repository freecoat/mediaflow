// KDM/DKDM page — vanilla JS
// Usa helper globali: api(method, url, body), toast(msg, type), openModal(id),
// closeModal(id), escapeHtml(s) da global.js
// applyI18n(root?) da i18n.js (opzionale, legge window.MF_I18N)

function kdmInit() {
  kdmInitFilters();
  kdmSwitchTab('requests');
}

// ── Filtri richieste (MFFilterBar) ────────────────────────────────────────────

var _kdmFilters = {q: null, status: null, type: null};

function kdmInitFilters() {
  var host = document.getElementById('kdm-filters');
  if (!host || !window.MFFilterBar || host._mfFilterBar) return;
  MFFilterBar({
    host: host,
    filters: [
      {kind: 'text', id: 'q', label: mfT('kdm.filter.search'),
       placeholder: mfT('kdm.filter.search_ph')},
      {kind: 'select', id: 'status', label: mfT('kdm.col.status'), searchable: false,
       options: [{value: '', label: mfT('kdm.filter.all')}].concat(
         KDM_STATUS_ORDER.map(function(s) {
           return {value: s, label: (KDM_STATUS_LABEL[s] || {}).lbl || s};
         }))},
      {kind: 'select', id: 'type', label: mfT('kdm.col.type'), searchable: false,
       options: [
         {value: '', label: mfT('kdm.filter.all')},
         {value: 'kdm', label: 'KDM'},
         {value: 'dkdm', label: 'DKDM'},
       ]},
    ],
    onChange: function(vals) {
      _kdmFilters = vals;
      kdmRenderRequests();
    },
  });
}

function kdmFilteredRequests() {
  var q = (_kdmFilters.q || '').toLowerCase();
  return _kdmRequests.filter(function(r) {
    if (_kdmFilters.status && r.status !== _kdmFilters.status) return false;
    if (_kdmFilters.type && r.request_type !== _kdmFilters.type) return false;
    if (q) {
      var hay = ((r.requested_title || '') + ' ' + (r.requested_cpl_uuid || '')).toLowerCase();
      if (hay.indexOf(q) === -1) return false;
    }
    return true;
  });
}

function kdmSwitchTab(name) {
  document.querySelectorAll('.kdm-tab').forEach(function(el) {
    el.style.display = 'none';
  });
  document.querySelectorAll('.tab-btn[data-tab]').forEach(function(b) {
    var isActive = b.dataset.tab === name;
    b.classList.toggle('active', isActive);
    b.style.borderBottomColor = isActive ? 'var(--indigo2)' : 'transparent';
    b.style.color = isActive ? 'var(--text)' : 'var(--text3)';
    b.style.fontWeight = isActive ? '600' : '500';
  });
  var pane = document.getElementById('kdm-tab-' + name);
  if (pane) pane.style.display = '';
  if (name === 'requests') kdmLoadRequests();
  else if (name === 'facilities') kdmLoadFacilities();
  else if (name === 'cpl') kdmLoadCpl();
}

// ── Status ordering ──────────────────────────────────────────────────────────

var KDM_STATUS_ORDER = ['received', 'matched', 'keys_pending', 'generated',
  'delivered', 'confirmed', 'rejected', 'expired'];

var KDM_STATUS_LABEL = {
  received:     {lbl: 'Ricevuta',     color: '#fbbf24', bg: 'rgba(251,191,36,.18)'},
  matched:      {lbl: 'Abbinata',     color: '#60a5fa', bg: 'rgba(96,165,250,.18)'},
  keys_pending: {lbl: 'Chiavi...',    color: '#fb923c', bg: 'rgba(251,146,60,.18)'},
  generated:    {lbl: 'Generata',     color: '#a78bfa', bg: 'rgba(167,139,250,.18)'},
  delivered:    {lbl: 'Consegnata',   color: '#22c55e', bg: 'rgba(34,197,94,.18)'},
  confirmed:    {lbl: 'Confermata',   color: '#4ade80', bg: 'rgba(74,222,128,.18)'},
  rejected:     {lbl: 'Rifiutata',    color: '#ef4444', bg: 'rgba(239,68,68,.18)'},
  expired:      {lbl: 'Scaduta',      color: '#9aa0b8', bg: 'rgba(154,160,184,.15)'},
};

function kdmRenderStatus(st) {
  var m = KDM_STATUS_LABEL[st] || {lbl: escapeHtml(st), color: 'var(--text3)', bg: 'var(--bg2)'};
  return '<span style="display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;color:' +
    m.color + ';background:' + m.bg + ';">' + m.lbl + '</span>';
}

function kdmRenderType(t) {
  var isDkdm = (t || '').toLowerCase() === 'dkdm';
  var color = isDkdm ? '#c084fc' : '#60a5fa';
  var bg = isDkdm ? 'rgba(192,132,252,.18)' : 'rgba(96,165,250,.18)';
  return '<span style="display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:700;color:' +
    color + ';background:' + bg + ';">' + escapeHtml((t || 'kdm').toUpperCase()) + '</span>';
}

// ── Tab: Richieste ───────────────────────────────────────────────────────────

var _kdmRequests = [];

async function kdmLoadRequests() {
  var body = document.getElementById('kdm-requests-body');
  if (!body) return;
  body.innerHTML = '<tr><td colspan="7" class="text-muted" style="text-align:center;padding:24px;">Caricamento...</td></tr>';
  try {
    _kdmRequests = await api('GET', '/kdm/api/requests');
  } catch (e) {
    body.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#ef4444;padding:24px;">Errore: ' + escapeHtml(e.message || '') + '</td></tr>';
    return;
  }
  _kdmRequests.sort(function(a, b) {
    return KDM_STATUS_ORDER.indexOf(a.status) - KDM_STATUS_ORDER.indexOf(b.status);
  });
  kdmRenderRequests();
}

function kdmRenderRequests() {
  var body = document.getElementById('kdm-requests-body');
  if (!body) return;
  var rows = kdmFilteredRequests();
  if (!rows.length) {
    var emptyKey = _kdmRequests.length ? 'kdm.empty.filtered' : 'kdm.empty.requests';
    var emptyTxt = _kdmRequests.length ? 'Nessun risultato per i filtri.' : 'Nessuna richiesta KDM.';
    body.innerHTML = '<tr><td colspan="7" class="text-muted" style="text-align:center;padding:24px;" data-i18n="' + emptyKey + '">' + emptyTxt + '</td></tr>';
    if (window.applyI18n) applyI18n();
    return;
  }
  var html = rows.map(function(r) {
    var matchCell = r.dcp_cpl_id
      ? '<span style="color:#22c55e;">✓ ' + escapeHtml(String(r.matched_confidence || '')) + '%</span>'
      : '<span style="color:#fbbf24;">⚠</span>';
    var win = escapeHtml((r.valid_from || '') + (r.valid_to ? ' → ' + r.valid_to : ''));
    var title = escapeHtml(r.requested_title || r.requested_cpl_uuid || '—');
    return '<tr style="cursor:pointer;" onclick="kdmOpenDetail(' + r.id + ')">' +
      '<td>' + kdmRenderStatus(r.status) + '</td>' +
      '<td>' + kdmRenderType(r.request_type) + '</td>' +
      '<td><span style="color:var(--indigo2);font-weight:500;">' + title + '</span></td>' +
      '<td class="text-sm text-muted">' + win + '</td>' +
      '<td>' + matchCell + '</td>' +
      '<td>' +
        '<button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();kdmOpenDetail(' + r.id + ')" data-i18n="kdm.action.open">Apri</button>' +
      '</td>' +
      '<td class="text-right">' +
        '<button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();kdmDeleteRequest(' + r.id + ')" style="color:#ef4444;" title="' + mfT('kdm.action.delete') + '" data-i18n="kdm.action.delete" data-i18n-attr="title">✕</button>' +
      '</td>' +
    '</tr>';
  }).join('');
  body.innerHTML = html;  // eslint-disable-line
  if (window.applyI18n) applyI18n();
}

async function kdmRematch(id) {
  try {
    var res = await api('POST', '/kdm/api/requests/' + id + '/match');
    var n = (res.candidates || []).length;
    toast('Candidati trovati: ' + n, n > 0 ? 'success' : 'info');
    await kdmLoadRequests();
  } catch (e) {
    toast('Errore match: ' + (e.message || ''), 'error');
  }
}

async function kdmDeleteRequest(id) {
  var req = _kdmRequests.find(function(r) { return r.id === id; });
  var title = req ? (req.requested_title || req.requested_cpl_uuid || 'richiesta ' + id) : 'richiesta ' + id;
  if (!confirm('Eliminare "' + title + '"? Azione irreversibile.')) return;
  try {
    await api('DELETE', '/kdm/api/requests/' + id);
    toast('Richiesta eliminata', 'success');
    await kdmLoadRequests();
  } catch (e) {
    toast('Errore: ' + (e.message || ''), 'error');
  }
}

var _kdmTransitionTargetId = null;
function kdmOpenTransition(id) {
  _kdmTransitionTargetId = id;
  openModal('kdm-modal-transition');
}

// ── Dettaglio richiesta (editabile + azioni leggibili) ────────────────────────

var _kdmDetail = null;

// ISO → valore per <input type="datetime-local"> (YYYY-MM-DDTHH:MM, local-ish)
function _kdmIsoToLocal(iso) {
  if (!iso) return '';
  return String(iso).slice(0, 16);
}

async function kdmOpenDetail(id) {
  try {
    _kdmDetail = await api('GET', '/kdm/api/requests/' + id);
  } catch (e) {
    toast('Errore: ' + (e.message || ''), 'error');
    return;
  }
  var d = _kdmDetail;
  document.getElementById('kdm-detail-id').value = d.id;
  document.getElementById('kdm-detail-type-badge').innerHTML = kdmRenderType(d.request_type);  // eslint-disable-line
  document.getElementById('kdm-detail-status-badge').innerHTML = kdmRenderStatus(d.status);  // eslint-disable-line

  var form = document.getElementById('kdm-detail-form');
  function setF(name, val) { var el = form.elements[name]; if (el) el.value = (val == null ? '' : val); }
  setF('requested_title', d.requested_title);
  setF('delivery_method', d.delivery_method || 'email');
  setF('requested_cpl_uuid', d.requested_cpl_uuid);
  setF('valid_from', _kdmIsoToLocal(d.valid_from));
  setF('valid_to', _kdmIsoToLocal(d.valid_to));
  setF('cinema_contact_name', d.cinema_contact_name);
  setF('cinema_contact_email', d.cinema_contact_email);
  setF('production_contact_name', d.production_contact_name);
  setF('production_contact_email', d.production_contact_email);
  setF('lab_contact_email', d.lab_contact_email);
  setF('notes', d.notes);

  // Info read-only
  var meta = [];
  if (d.dcp_cpl_id) {
    meta.push('🎬 CPL: ' + escapeHtml(d.dcp_cpl_title || ('#' + d.dcp_cpl_id)) +
      (d.matched_confidence != null ? ' (' + escapeHtml(String(d.matched_confidence)) + '% · ' + escapeHtml(d.match_source || '') + ')' : ''));
  } else {
    meta.push('⚠ ' + mfT('kdm.detail.no_cpl'));
  }
  if (d.target_facility_name) meta.push('🏛 ' + escapeHtml(d.target_facility_name));
  if (d.has_client_cert) meta.push('🔐 ' + mfT('kdm.detail.has_cert'));
  if (d.source_link_id) meta.push('🔗 ' + mfT('kdm.detail.from_link'));
  if (d.job_deliverable_produced_id) meta.push('📦 ' + mfT('kdm.detail.deliverable_done'));
  document.getElementById('kdm-detail-meta').innerHTML = meta.join(' &nbsp;·&nbsp; ');  // eslint-disable-line

  // Timeline
  var tl = (d.events || []).map(function(e) {
    var p = e.payload || {};
    var when = escapeHtml(_kdmIsoToLocal(e.created_at).replace('T', ' '));
    var what = (p.from && p.to)
      ? (((KDM_STATUS_LABEL[p.from] || {}).lbl || p.from) + ' → ' + ((KDM_STATUS_LABEL[p.to] || {}).lbl || p.to))
      : escapeHtml(e.event_type || '');
    return '<div style="padding:2px 0;">• ' + when + ' — ' + escapeHtml(what) + '</div>';
  }).join('');
  document.getElementById('kdm-detail-timeline').innerHTML = tl || ('<span data-i18n="kdm.detail.no_events">' + mfT('kdm.detail.no_events') + '</span>');  // eslint-disable-line

  // Abilita/disabilita azioni in base allo stato
  var canEmit = ['received', 'matched', 'keys_pending'].indexOf(d.status) !== -1;
  var canConfirm = ['generated', 'delivered'].indexOf(d.status) !== -1;
  var canMatch = !d.dcp_cpl_id && ['received', 'matched'].indexOf(d.status) !== -1;
  _kdmToggleBtn('kdm-detail-btn-emit', canEmit);
  _kdmToggleBtn('kdm-detail-btn-confirm', canConfirm);
  _kdmToggleBtn('kdm-detail-btn-match', canMatch);

  openModal('kdm-modal-detail');
  if (window.applyI18n) applyI18n();
}

function _kdmToggleBtn(id, on) {
  var b = document.getElementById(id);
  if (!b) return;
  b.style.display = on ? '' : 'none';
}

async function kdmDetailSave() {
  var id = document.getElementById('kdm-detail-id').value;
  if (!id) return;
  var form = document.getElementById('kdm-detail-form');
  var fd = new FormData();
  ['requested_title', 'delivery_method', 'requested_cpl_uuid', 'valid_from',
   'valid_to', 'cinema_contact_name', 'cinema_contact_email',
   'production_contact_name', 'production_contact_email', 'lab_contact_email',
   'notes'].forEach(function(name) {
    var el = form.elements[name];
    if (!el) return;
    var v = el.value.trim();
    // Sentinel '0' per svuotare un campo già valorizzato (memo empty-multipart=None)
    if (v === '' && _kdmDetail && _kdmDetail[name]) v = '0';
    if (v !== '') fd.append(name, v);
  });
  try {
    await api('POST', '/kdm/api/requests/' + id, fd);
    toast(mfT('kdm.toast.saved'), 'success');
    closeModal('kdm-modal-detail');
    await kdmLoadRequests();
  } catch (e) {
    toast('Errore: ' + (e.message || ''), 'error');
  }
}

async function kdmDetailEmit() {
  var id = document.getElementById('kdm-detail-id').value;
  if (!id) return;
  if (!confirm(mfT('kdm.confirm.emit'))) return;
  try {
    await api('POST', '/kdm/api/requests/' + id + '/emit');
    toast(mfT('kdm.toast.emitted'), 'success');
    await kdmOpenDetail(parseInt(id, 10));
    await kdmLoadRequests();
  } catch (e) {
    toast('Errore: ' + (e.message || ''), 'error');
  }
}

async function kdmDetailConfirm() {
  var id = document.getElementById('kdm-detail-id').value;
  if (!id) return;
  if (!confirm(mfT('kdm.confirm.delivery'))) return;
  try {
    await api('POST', '/kdm/api/requests/' + id + '/confirm-delivery');
    toast(mfT('kdm.toast.confirmed'), 'success');
    await kdmOpenDetail(parseInt(id, 10));
    await kdmLoadRequests();
  } catch (e) {
    toast('Errore: ' + (e.message || ''), 'error');
  }
}

async function kdmDetailMatch() {
  var id = document.getElementById('kdm-detail-id').value;
  if (!id) return;
  await kdmRematch(parseInt(id, 10));
  await kdmOpenDetail(parseInt(id, 10));
}

function kdmDetailOpenFsm() {
  var id = document.getElementById('kdm-detail-id').value;
  if (!id) return;
  kdmOpenTransition(parseInt(id, 10));
}

async function kdmDoTransition() {
  var sel = document.getElementById('kdm-transition-status');
  if (!sel || !_kdmTransitionTargetId) return;
  var toStatus = sel.value;
  if (!toStatus) { toast('Seleziona uno stato', 'warning'); return; }
  try {
    var tid = _kdmTransitionTargetId;
    await api('POST', '/kdm/api/requests/' + tid + '/transition',
      new URLSearchParams({to_status: toStatus}));
    closeModal('kdm-modal-transition');
    toast('Stato aggiornato', 'success');
    var detailOpen = _kdmDetail && String(_kdmDetail.id) === String(tid) &&
      document.getElementById('kdm-modal-detail').classList.contains('open');
    if (detailOpen) await kdmOpenDetail(parseInt(tid, 10));
    await kdmLoadRequests();
  } catch (e) {
    toast('Errore: ' + (e.message || ''), 'error');
  }
}

// ── Nuova richiesta modal ────────────────────────────────────────────────────

function kdmOpenNewRequest() {
  var form = document.getElementById('kdm-new-req-form');
  if (form) form.reset();
  openModal('kdm-modal-new-request');
}

async function kdmSaveNewRequest() {
  var form = document.getElementById('kdm-new-req-form');
  if (!form) return;
  var fd = new FormData(form);
  try {
    await api('POST', '/kdm/api/requests', fd);
    closeModal('kdm-modal-new-request');
    toast('Richiesta creata', 'success');
    await kdmLoadRequests();
  } catch (e) {
    toast('Errore: ' + (e.message || ''), 'error');
  }
}

// ── Genera link cliente ──────────────────────────────────────────────────────

async function kdmGenerateLink() {
  var titleInput = document.getElementById('kdm-link-prefill-title');
  var prefillTitle = titleInput ? titleInput.value.trim() : '';
  var fd = new FormData();
  if (prefillTitle) fd.append('prefill_title', prefillTitle);
  try {
    var res = await api('POST', '/kdm/api/links', fd);
    var url = res.url || '';
    if (url) {
      try {
        await navigator.clipboard.writeText(url);
        toast('Link copiato negli appunti: ' + url, 'success');
      } catch (ce) {
        // clipboard non disponibile (non-https / vecchio browser)
        toast('Link generato: ' + url, 'info');
      }
    } else {
      toast('Link generato', 'success');
    }
    if (window.kdmLoadLinks) kdmLoadLinks();
  } catch (e) {
    toast('Errore generazione link: ' + (e.message || ''), 'error');
  }
}

// ── Tab: Links panel (nella tab Richieste) ───────────────────────────────────

var _kdmLinks = [];

async function kdmLoadLinks() {
  var container = document.getElementById('kdm-links-list');
  if (!container) return;
  try {
    _kdmLinks = await api('GET', '/kdm/api/links');
  } catch (e) {
    _kdmLinks = [];
  }
  if (!_kdmLinks.length) {
    container.innerHTML = '<div class="text-muted text-sm" style="padding:8px 0;">Nessun link attivo.</div>';
    return;
  }
  container.innerHTML = _kdmLinks.map(function(l) {
    return '<div style="display:flex;align-items:center;gap:8px;padding:4px 0;border-bottom:1px solid var(--border);">' +
      '<span class="text-sm mono" style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + escapeHtml(l.url) + '</span>' +
      '<button class="btn btn-ghost btn-sm" onclick="kdmCopyLink(' + l.id + ')">Copia</button>' +
      '<button class="btn btn-ghost btn-sm" style="color:#ef4444;" onclick="kdmRevokeLink(' + l.id + ')">Revoca</button>' +
    '</div>';
  }).join('');
}

function kdmCopyLink(id) {
  var l = (_kdmLinks || []).find(function(x) { return x.id === id; });
  if (!l) return;
  try {
    navigator.clipboard.writeText(l.url).then(function() {
      toast('Link copiato', 'success');
    });
  } catch (e) {
    toast('URL: ' + l.url, 'info');
  }
}

async function kdmRevokeLink(id) {
  if (!confirm('Revocare questo link? Chi lo possiede non potrà più accedere.')) return;
  try {
    await api('POST', '/kdm/api/links/' + id + '/revoke');
    toast('Link revocato', 'success');
    await kdmLoadLinks();
  } catch (e) {
    toast('Errore: ' + (e.message || ''), 'error');
  }
}

// ── Tab: Cinema/Server ───────────────────────────────────────────────────────

var _kdmFacilities = [];

async function kdmLoadFacilities() {
  var pane = document.getElementById('kdm-tab-facilities');
  if (!pane) return;
  pane.innerHTML = '<div class="text-muted" style="padding:24px;text-align:center;">Caricamento...</div>';
  try {
    _kdmFacilities = await api('GET', '/kdm/api/facilities');
  } catch (e) {
    pane.innerHTML = '<div style="color:#ef4444;padding:24px;text-align:center;">Errore: ' + escapeHtml(e.message || '') + '</div>';
    return;
  }
  if (!_kdmFacilities.length) {
    pane.innerHTML = '<div class="text-muted text-sm" style="padding:24px;text-align:center;" data-i18n="kdm.empty.facilities">Nessun cinema/server registrato.</div>';
    if (window.applyI18n) applyI18n();
    return;
  }
  var html = '<div style="display:flex;justify-content:flex-end;margin-bottom:10px;">' +
    '<button class="btn btn-secondary btn-sm" onclick="kdmOpenNewFacility()" data-i18n="kdm.btn.add_facility">+ Cinema</button>' +
  '</div>' +
  '<table class="table"><thead><tr>' +
    '<th data-i18n="kdm.col.fac_name">Nome</th>' +
    '<th data-i18n="kdm.col.fac_kind">Tipo</th>' +
    '<th data-i18n="kdm.col.fac_city">Città</th>' +
    '<th data-i18n="kdm.col.fac_screens">Sale</th>' +
    '<th></th>' +
  '</tr></thead><tbody>' +
  _kdmFacilities.map(function(f) {
    return '<tr>' +
      '<td><strong>' + escapeHtml(f.name) + '</strong></td>' +
      '<td class="text-sm text-muted">' + escapeHtml(f.kind || '—') + '</td>' +
      '<td class="text-sm">' + escapeHtml(f.city || '—') + '</td>' +
      '<td class="text-sm mono">' + (f.screen_count || '—') + '</td>' +
      '<td class="text-right">' +
        '<button class="btn btn-ghost btn-sm" onclick="kdmEditFacility(' + f.id + ')" data-i18n="kdm.action.edit">Modifica</button> ' +
        '<button class="btn btn-ghost btn-sm" style="color:#ef4444;" onclick="kdmDeleteFacility(' + f.id + ')" data-i18n="kdm.action.delete">Elimina</button>' +
      '</td>' +
    '</tr>';
  }).join('') +
  '</tbody></table>';
  pane.innerHTML = html;  // eslint-disable-line
  if (window.applyI18n) applyI18n();
}

function kdmOpenNewFacility() {
  document.getElementById('kdm-fac-id').value = '';
  document.getElementById('kdm-fac-name').value = '';
  document.getElementById('kdm-fac-kind').value = 'cinema';
  document.getElementById('kdm-fac-city').value = '';
  openModal('kdm-modal-facility');
}

function kdmEditFacility(id) {
  var f = _kdmFacilities.find(function(x) { return x.id === id; });
  if (!f) return;
  document.getElementById('kdm-fac-id').value = f.id;
  document.getElementById('kdm-fac-name').value = f.name || '';
  document.getElementById('kdm-fac-kind').value = f.kind || 'cinema';
  document.getElementById('kdm-fac-city').value = f.city || '';
  openModal('kdm-modal-facility');
}

async function kdmSaveFacility() {
  var id = document.getElementById('kdm-fac-id').value;
  var fd = new FormData();
  fd.append('name', document.getElementById('kdm-fac-name').value);
  fd.append('kind', document.getElementById('kdm-fac-kind').value);
  fd.append('city', document.getElementById('kdm-fac-city').value);
  try {
    var url = id ? '/kdm/api/facilities/' + id : '/kdm/api/facilities';
    var method = id ? 'PUT' : 'POST';
    await api(method, url, fd);
    closeModal('kdm-modal-facility');
    toast(id ? 'Cinema aggiornato' : 'Cinema aggiunto', 'success');
    await kdmLoadFacilities();
  } catch (e) {
    toast('Errore: ' + (e.message || ''), 'error');
  }
}

async function kdmDeleteFacility(id) {
  if (!confirm('Eliminare questo cinema/server?')) return;
  try {
    await api('DELETE', '/kdm/api/facilities/' + id);
    toast('Cinema eliminato', 'success');
    await kdmLoadFacilities();
  } catch (e) {
    toast('Errore: ' + (e.message || ''), 'error');
  }
}

// ── Tab: CPL DCP ─────────────────────────────────────────────────────────────

var _kdmCpls = [];

async function kdmLoadCpl() {
  var pane = document.getElementById('kdm-tab-cpl');
  if (!pane) return;
  pane.innerHTML = '<div class="text-muted" style="padding:24px;text-align:center;">Caricamento...</div>';
  try {
    _kdmCpls = await api('GET', '/kdm/api/cpl');
  } catch (e) {
    pane.innerHTML = '<div style="color:#ef4444;padding:24px;text-align:center;">Errore: ' + escapeHtml(e.message || '') + '</div>';
    return;
  }
  if (!_kdmCpls.length) {
    pane.innerHTML = '<div class="text-muted text-sm" style="padding:24px;text-align:center;" data-i18n="kdm.empty.cpl">Nessuna CPL registrata. Carica un file CPL XML oppure inserisci manualmente.</div>' +
      '<div style="display:flex;justify-content:center;gap:10px;margin-top:14px;">' +
        '<button class="btn btn-secondary btn-sm" onclick="kdmOpenCplManual()" data-i18n="kdm.btn.add_cpl_manual">+ CPL manuale</button>' +
        '<label class="btn btn-secondary btn-sm" style="cursor:pointer;">' +
          '<input type="file" accept=".xml" style="display:none;" onchange="kdmUploadCpl(event)">&#8593; Upload CPL XML</label>' +
      '</div>';
    if (window.applyI18n) applyI18n();
    return;
  }
  var html = '<div style="display:flex;justify-content:flex-end;gap:10px;margin-bottom:10px;">' +
    '<label class="btn btn-secondary btn-sm" style="cursor:pointer;">' +
      '<input type="file" accept=".xml" style="display:none;" onchange="kdmUploadCpl(event)" data-i18n="kdm.btn.upload_cpl">&#8593; Upload CPL XML</label>' +
    '<button class="btn btn-secondary btn-sm" onclick="kdmOpenCplManual()" data-i18n="kdm.btn.add_cpl_manual">+ CPL manuale</button>' +
  '</div>' +
  '<table class="table"><thead><tr>' +
    '<th data-i18n="kdm.col.cpl_uuid">CPL UUID</th>' +
    '<th data-i18n="kdm.col.cpl_title">Titolo</th>' +
    '<th data-i18n="kdm.col.cpl_content_kind">Tipo</th>' +
    '<th data-i18n="kdm.col.cpl_duration">Durata</th>' +
    '<th data-i18n="kdm.col.cpl_source">Fonte</th>' +
    '<th></th>' +
  '</tr></thead><tbody>' +
  _kdmCpls.map(function(c) {
    return '<tr>' +
      '<td class="mono text-sm" title="' + escapeHtml(c.cpl_uuid || '') + '">' + escapeHtml((c.cpl_uuid || '').slice(-12) || '—') + '</td>' +
      '<td>' + escapeHtml(c.content_title_text || '—') + '</td>' +
      '<td class="text-sm text-muted">' + escapeHtml(c.content_kind || '—') + '</td>' +
      '<td class="text-sm mono">' + escapeHtml(c.duration_frames ? String(c.duration_frames) + 'f' : '—') + '</td>' +
      '<td class="text-sm text-muted">' + escapeHtml(c.source || '—') + '</td>' +
      '<td></td>' +
    '</tr>';
  }).join('') +
  '</tbody></table>';
  pane.innerHTML = html;  // eslint-disable-line
  if (window.applyI18n) applyI18n();
}

function kdmOpenCplManual() {
  var form = document.getElementById('kdm-cpl-manual-form');
  if (form) form.reset();
  openModal('kdm-modal-cpl-manual');
}

async function kdmSaveCplManual() {
  var fd = new FormData(document.getElementById('kdm-cpl-manual-form'));
  try {
    await api('POST', '/kdm/api/cpl/manual', fd);
    closeModal('kdm-modal-cpl-manual');
    toast('CPL aggiunta', 'success');
    await kdmLoadCpl();
  } catch (e) {
    toast('Errore: ' + (e.message || ''), 'error');
  }
}

async function kdmUploadCpl(event) {
  var file = event.target.files[0];
  if (!file) return;
  var fd = new FormData();
  fd.append('file', file, file.name);
  try {
    var res = await api('POST', '/kdm/api/cpl/parse', fd);
    toast('CPL caricata: ' + escapeHtml(res.content_title_text || res.cpl_uuid || ''), 'success');
    await kdmLoadCpl();
  } catch (e) {
    toast('Errore parse CPL: ' + (e.message || ''), 'error');
  }
  event.target.value = '';
}

