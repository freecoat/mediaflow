// KDM/DKDM page — vanilla JS
// Usa helper globali: api(method, url, body), toast(msg, type), openModal(id),
// closeModal(id), escapeHtml(s) da global.js
// applyI18n(root?) da i18n.js (opzionale, legge window.MF_I18N)

function kdmInit() {
  kdmSwitchTab('requests');
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
  if (!_kdmRequests.length) {
    body.innerHTML = '<tr><td colspan="7" class="text-muted" style="text-align:center;padding:24px;" data-i18n="kdm.empty.requests">Nessuna richiesta KDM.</td></tr>';
    if (window.applyI18n) applyI18n();
    return;
  }
  var html = _kdmRequests.map(function(r) {
    var matchCell = r.dcp_cpl_id
      ? '<span style="color:#22c55e;">✓ ' + escapeHtml(String(r.matched_confidence || '')) + '%</span>'
      : '<span style="color:#fbbf24;">⚠</span>';
    var win = escapeHtml((r.valid_from || '') + (r.valid_to ? ' → ' + r.valid_to : ''));
    return '<tr>' +
      '<td>' + kdmRenderStatus(r.status) + '</td>' +
      '<td class="text-sm">' + escapeHtml((r.request_type || '').toUpperCase()) + '</td>' +
      '<td>' + escapeHtml(r.requested_title || r.requested_cpl_uuid || '—') + '</td>' +
      '<td class="text-sm text-muted">' + win + '</td>' +
      '<td>' + matchCell + '</td>' +
      '<td>' +
        '<button class="btn btn-ghost btn-sm" onclick="kdmRematch(' + r.id + ')" data-i18n="kdm.action.match">Match</button> ' +
        '<button class="btn btn-ghost btn-sm" onclick="kdmOpenTransition(' + r.id + ')" data-i18n="kdm.action.transition">Stato→</button>' +
      '</td>' +
      '<td class="text-right">' +
        '<button class="btn btn-ghost btn-sm" onclick="kdmDeleteRequest(' + r.id + ')" style="color:#ef4444;" title="Elimina" data-i18n="kdm.action.delete">✕</button>' +
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

async function kdmDoTransition() {
  var sel = document.getElementById('kdm-transition-status');
  if (!sel || !_kdmTransitionTargetId) return;
  var toStatus = sel.value;
  if (!toStatus) { toast('Seleziona uno stato', 'warning'); return; }
  try {
    await api('POST', '/kdm/api/requests/' + _kdmTransitionTargetId + '/transition',
      new URLSearchParams({to_status: toStatus}));
    closeModal('kdm-modal-transition');
    toast('Stato aggiornato', 'success');
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
      '<button class="btn btn-ghost btn-sm" onclick="kdmCopyLink(' + escapeHtml(JSON.stringify(l.url)) + ')">Copia</button>' +
      '<button class="btn btn-ghost btn-sm" style="color:#ef4444;" onclick="kdmRevokeLink(' + l.id + ')">Revoca</button>' +
    '</div>';
  }).join('');
}

function kdmCopyLink(url) {
  try {
    navigator.clipboard.writeText(url).then(function() {
      toast('Link copiato', 'success');
    });
  } catch (e) {
    toast('URL: ' + url, 'info');
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
      '<td class="text-right">' +
        '<button class="btn btn-ghost btn-sm" style="color:#ef4444;" onclick="kdmDeleteCpl(' + c.id + ')" data-i18n="kdm.action.delete">Elimina</button>' +
      '</td>' +
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

async function kdmDeleteCpl(id) {
  if (!confirm('Eliminare questa CPL? Le richieste KDM abbinate verranno de-linkate.')) return;
  // CPL soft-delete non implementato in questo router — placeholder
  toast('Funzione non disponibile in questa versione', 'warning');
}
