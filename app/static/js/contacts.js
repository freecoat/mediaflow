// app/static/js/contacts.js — Client email F3: Rubrica Contatti
let _mfContactsFilterState = {};

async function mfContactsLoad() {
  const box = document.getElementById('contacts-list');
  if (!box) return;
  const params = new URLSearchParams();
  Object.keys(_mfContactsFilterState).forEach(function (k) {
    const v = _mfContactsFilterState[k];
    if (v) params.set(k, v);
  });
  try {
    const d = await (await fetch('/contacts/api/list?' + params.toString())).json();
    const items = d.items || [];
    if (!items.length) {
      box.innerHTML = '<div class="muted" style="padding:20px;">' + mfT('contact.empty') + '</div>';
      return;
    }
    box.innerHTML = '<table class="table"><thead><tr>' +
      '<th>' + mfT('contact.name') + '</th><th>' + mfT('contact.companyText') + '</th>' +
      '<th>' + mfT('contact.email') + '</th><th>' + mfT('contact.phone') + '</th>' +
      '<th>' + mfT('contact.links') + '</th></tr></thead><tbody>' +
      items.map(function (it) {
        const company = it.company_text || '';
        const orphan = !it.client_id && it.links.acquisitions === 0 && it.links.projects === 0
          ? ' <span class="badge">' + mfT('contact.orphan') + '</span>' : '';
        return '<tr class="clickable" data-contact-open="' + it.id + '">' +
          '<td>' + escapeHtml(it.name) + orphan + '</td>' +
          '<td>' + escapeHtml(company) + '</td>' +
          '<td>' + escapeHtml(it.email || '') + '</td>' +
          '<td>' + escapeHtml(it.phone || '') + '</td>' +
          '<td>' + it.links.acquisitions + ' 🎯 · ' + it.links.projects + ' 🎬</td></tr>';
      }).join('') + '</tbody></table>';
  } catch (e) { box.innerHTML = '<div class="muted">' + mfT('contact.error') + '</div>'; }
}

function mfContactsInitFilterBar() {
  const host = document.getElementById('contacts-filterbar');
  if (!host || typeof MFFilterBar !== 'function') return;
  MFFilterBar({
    host: host,
    filters: [
      {id: 'search', kind: 'text', label: mfT('contact.search'), minWidth: '220px'},
      {id: 'triage', kind: 'select', label: mfT('contact.triage'), options: [
        {value: '', label: mfT('contact.all')}, {value: '1', label: mfT('contact.orphansOnly')}]},
    ],
    onChange: function (vals) { _mfContactsFilterState = vals; mfContactsLoad(); },
  });
}

async function mfContactOpenDetail(id) {
  const body = document.getElementById('cd-body');
  const title = document.getElementById('cd-name');
  if (!body) return;
  try {
    const d = await (await fetch('/contacts/api/' + encodeURIComponent(id))).json();
    if (title) title.textContent = d.name;
    const acqRows = (d.acquisitions || []).map(function (a) {
      return '<li>' + escapeHtml(a.title) + (a.role ? ' — ' + escapeHtml(a.role) : '') +
        ' <button class="btn btn-sm" data-contact-unlink="' + id + '" data-target-type="acquisition" data-target-id="' + a.id + '">✕</button></li>';
    }).join('') || '<li class="muted">' + mfT('contact.none') + '</li>';
    const projRows = (d.projects || []).map(function (p) {
      return '<li>' + escapeHtml(p.code) + ' — ' + escapeHtml(p.title) +
        (p.role ? ' — ' + escapeHtml(p.role) : '') +
        ' <button class="btn btn-sm" data-contact-unlink="' + id + '" data-target-type="project" data-target-id="' + p.id + '">✕</button></li>';
    }).join('') || '<li class="muted">' + mfT('contact.none') + '</li>';
    const emailRows = (d.email_links || []).map(function (e) {
      return '<li>' + escapeHtml(e.subject || e.thread_id) + '</li>';
    }).join('') || '<li class="muted">' + mfT('contact.none') + '</li>';
    // "+ Associa" per sezione (create-link). Il picker apre modal-contact-link-picker.
    const assocBtn = function (type) {
      return ' <button class="btn btn-sm" data-contact-link-open="' + id +
        '" data-target-type="' + type + '">' + mfT('contact.linkBtn') + '</button>';
    };
    const clientBlock = d.client
      ? escapeHtml(d.client.name) +
        ' <button class="btn btn-sm" data-contact-unlink="' + id + '" data-target-type="client" data-target-id="' + d.client.id + '">✕</button>'
      : escapeHtml(d.company_text || '—');
    body.innerHTML =
      '<div class="form-group"><label class="form-label">' + mfT('contact.email') + '</label>' +
      '<div>' + escapeHtml(d.email || '—') + '</div></div>' +
      '<div class="form-group"><label class="form-label">' + mfT('contact.phone') + '</label>' +
      '<div>' + escapeHtml(d.phone || '—') + '</div></div>' +
      '<div class="form-group"><label class="form-label">' + mfT('contact.client') + assocBtn('client') + '</label>' +
      '<div>' + clientBlock + '</div></div>' +
      '<div class="form-group"><label class="form-label">' + mfT('contact.acquisitions') + assocBtn('acquisition') + '</label><ul>' + acqRows + '</ul></div>' +
      '<div class="form-group"><label class="form-label">' + mfT('contact.projects') + assocBtn('project') + '</label><ul>' + projRows + '</ul></div>' +
      '<div class="form-group"><label class="form-label">' + mfT('contact.emailLinks') + '</label><ul>' + emailRows + '</ul></div>';
    openModal('modal-contact-detail');
  } catch (e) { if (window.toast) toast(mfT('contact.error'), 'error'); }
}

// ── Picker "+ Associa": cliente / trattativa / progetto ──────────
const _MF_PICK_LABEL = {
  client: 'contact.pickClient', acquisition: 'contact.pickAcquisition', project: 'contact.pickProject',
};
let _mfLinkPicker = {cid: null, type: null};

function mfContactOpenLinkPicker(cid, targetType) {
  _mfLinkPicker = {cid: cid, type: targetType};
  const titleEl = document.getElementById('clp-title');
  const searchEl = document.getElementById('clp-search');
  const roleEl = document.getElementById('clp-role');
  if (titleEl) titleEl.textContent = mfT(_MF_PICK_LABEL[targetType] || 'contact.linkBtn');
  if (searchEl) searchEl.value = '';
  if (roleEl) roleEl.value = '';
  openModal('modal-contact-link-picker');
  mfContactLinkPickerLoad('');
}

async function mfContactLinkPickerLoad(q) {
  const box = document.getElementById('clp-results');
  if (!box) return;
  const type = _mfLinkPicker.type;
  q = (q || '').trim().toLowerCase();
  box.innerHTML = '<div class="muted">…</div>';
  try {
    let rows = [];
    if (type === 'client') {
      const arr = await (await fetch('/clients/api')).json();
      rows = (arr || [])
        .filter(function (c) { return !q || (c.name || '').toLowerCase().indexOf(q) >= 0; })
        .map(function (c) { return {id: c.id, label: c.name || ('#' + c.id)}; });
    } else if (type === 'project') {
      const arr = await (await fetch('/projects/api')).json();
      rows = (arr || [])
        .filter(function (p) { return !q || ((p.code || '') + ' ' + (p.title || '')).toLowerCase().indexOf(q) >= 0; })
        .map(function (p) { return {id: p.id, label: (p.code || '') + ' — ' + (p.title || '')}; });
    } else {  // acquisition — endpoint ritorna {items:[...]}
      const d = await (await fetch('/acquisitions/api/list')).json();
      rows = (d.items || [])
        .filter(function (a) { return !q || ((a.title || '') + ' ' + (a.client_name || '')).toLowerCase().indexOf(q) >= 0; })
        .map(function (a) { return {id: a.id, label: (a.title || '') + (a.client_name ? ' · ' + a.client_name : '')}; });
    }
    if (!rows.length) { box.innerHTML = '<div class="muted">' + mfT('contact.none') + '</div>'; return; }
    box.innerHTML = rows.map(function (r) {
      return '<div style="display:flex;justify-content:space-between;align-items:center;padding:4px 0;border-bottom:1px solid var(--border);">' +
        '<span>' + escapeHtml(r.label) + '</span>' +
        '<button class="btn btn-sm btn-primary" data-link-pick-id="' + escapeHtml(String(r.id)) + '">' + mfT('contact.linkBtn') + '</button></div>';
    }).join('');
  } catch (e) { box.innerHTML = '<div class="muted">' + mfT('contact.error') + '</div>'; }
}

async function mfContactLink(cid, targetType, targetId, role) {
  const fd = new FormData();
  fd.append('target_type', targetType);
  fd.append('target_id', targetId);
  if (role) fd.append('role', role);
  try {
    const r = await fetch('/contacts/api/' + encodeURIComponent(cid) + '/link', {method: 'POST', body: fd});
    const b = await r.json();
    if (r.ok) {
      if (window.toast) toast(b.already_linked ? mfT('contact.alreadyLinked') : mfT('contact.linked'), 'success');
      closeModal('modal-contact-link-picker');
      mfContactOpenDetail(cid);  // refresh sezioni del dettaglio
      mfContactsLoad();          // refresh conteggi link nella lista
    } else if (window.toast) toast(mfT('contact.error'), 'error');
  } catch (e) { if (window.toast) toast(mfT('contact.error'), 'error'); }
}

async function mfContactSaveNew() {
  const fd = new FormData();
  const map = {name: 'cn-name', company_text: 'cn-company', email: 'cn-email',
               phone: 'cn-phone', role: 'cn-role'};
  Object.keys(map).forEach(function (k) {
    const el = document.getElementById(map[k]);
    if (el && el.value.trim()) fd.append(k, el.value.trim());
  });
  if (!fd.get('name')) { if (window.toast) toast(mfT('contact.nameRequired'), 'error'); return; }
  try {
    const r = await fetch('/contacts/api/create', {method: 'POST', body: fd});
    const b = await r.json();
    if (!r.ok) { if (window.toast) toast(mfT('contact.error'), 'error'); return; }
    if (b.existing_id) { if (window.toast) toast(mfT('contact.dedupFound'), 'success'); }
    else if (window.toast) toast(mfT('contact.created'), 'success');
    closeModal('modal-contact-new');
    mfContactsLoad();
  } catch (e) { if (window.toast) toast(mfT('contact.error'), 'error'); }
}

async function mfContactUnlink(cid, targetType, targetId) {
  const fd = new FormData();
  fd.append('target_type', targetType);
  fd.append('target_id', targetId);
  try {
    const r = await fetch('/contacts/api/' + encodeURIComponent(cid) + '/link', {method: 'DELETE', body: fd});
    if (r.ok) { mfContactOpenDetail(cid); mfContactsLoad(); }
  } catch (e) { if (window.toast) toast(mfT('contact.error'), 'error'); }
}

function mfContactsInit() {
  mfContactsInitFilterBar();
  mfContactsLoad();
  const newBtn = document.getElementById('contacts-btn-new');
  if (newBtn) newBtn.addEventListener('click', function () { openModal('modal-contact-new'); });
  const saveBtn = document.getElementById('contacts-btn-save-new');
  if (saveBtn) saveBtn.addEventListener('click', mfContactSaveNew);
  const clpSearch = document.getElementById('clp-search');
  if (clpSearch) clpSearch.addEventListener('input', function () { mfContactLinkPickerLoad(this.value); });
  if (window._mfContactsClickBound) return;
  window._mfContactsClickBound = true;
  document.addEventListener('click', function (ev) {
    const t = ev.target;
    const open = t.closest && t.closest('[data-contact-open]');
    if (open) { mfContactOpenDetail(open.getAttribute('data-contact-open')); return; }
    const linkOpen = t.closest && t.closest('[data-contact-link-open]');
    if (linkOpen) {
      mfContactOpenLinkPicker(linkOpen.getAttribute('data-contact-link-open'),
                              linkOpen.getAttribute('data-target-type'));
      return;
    }
    const pick = t.closest && t.closest('[data-link-pick-id]');
    if (pick) {
      const roleEl = document.getElementById('clp-role');
      mfContactLink(_mfLinkPicker.cid, _mfLinkPicker.type,
                    pick.getAttribute('data-link-pick-id'),
                    roleEl ? roleEl.value.trim() : '');
      return;
    }
    const unlink = t.closest && t.closest('[data-contact-unlink]');
    if (unlink) {
      mfContactUnlink(unlink.getAttribute('data-contact-unlink'),
                      unlink.getAttribute('data-target-type'),
                      unlink.getAttribute('data-target-id'));
      return;
    }
  });
}

// ── Estrazione contatti da thread (usato da /mail e email_links.js) ──
async function mfContactExtractOpen(threadId, hostId) {
  const host = document.getElementById(hostId);
  if (!host) return;
  host.innerHTML = '<div class="muted">' + mfT('contact.extracting') + '</div>';
  try {
    const fd = new FormData();
    fd.append('thread_id', threadId);
    const r = await fetch('/contacts/api/extract', {method: 'POST', body: fd});
    const d = await r.json();
    const cands = d.candidates || [];
    if (!cands.length) { host.innerHTML = '<div class="muted">' + mfT('contact.none') + '</div>'; return; }
    host.innerHTML = cands.map(function (c, i) {
      return '<div class="contact-cand" style="border:1px solid var(--border);border-radius:6px;padding:8px;margin-bottom:6px;">' +
        '<b>' + escapeHtml(c.name || '') + '</b> <span class="muted">' + escapeHtml(c.email || '') + '</span>' +
        (c.role ? '<div class="muted">' + escapeHtml(c.role) + '</div>' : '') +
        (c.company_text ? '<div class="muted">' + escapeHtml(c.company_text) + '</div>' : '') +
        (c.phone ? '<div class="muted">' + escapeHtml(c.phone) + '</div>' : '') +
        '<button class="btn btn-sm" data-contact-cand-save="' + i + '" data-cand-host="' + escapeHtml(hostId) + '">' +
        mfT('contact.saveCandidate') + '</button></div>';
    }).join('');
    host._mfCandidates = cands;
  } catch (e) { host.innerHTML = '<div class="muted">' + mfT('contact.error') + '</div>'; }
}

async function mfContactSaveCandidate(hostId, idx) {
  const host = document.getElementById(hostId);
  const cand = host && host._mfCandidates && host._mfCandidates[idx];
  if (!cand) return;
  const fd = new FormData();
  fd.append('name', cand.name || '');
  if (cand.email) fd.append('email', cand.email);
  if (cand.phone) fd.append('phone', cand.phone);
  if (cand.role) fd.append('role', cand.role);
  if (cand.company_text) fd.append('company_text', cand.company_text);
  try {
    const r = await fetch('/contacts/api/create', {method: 'POST', body: fd});
    if (r.ok) { if (window.toast) toast(mfT('contact.created'), 'success'); }
    else if (window.toast) toast(mfT('contact.error'), 'error');
  } catch (e) { if (window.toast) toast(mfT('contact.error'), 'error'); }
}

if (!window._mfContactCandClickBound) {
  window._mfContactCandClickBound = true;
  document.addEventListener('click', function (ev) {
    const t = ev.target;
    const save = t.closest && t.closest('[data-contact-cand-save]');
    if (save) {
      mfContactSaveCandidate(save.getAttribute('data-cand-host'),
                            parseInt(save.getAttribute('data-contact-cand-save'), 10));
    }
  });
}

window.mfContactsInit = mfContactsInit;
window.mfContactOpenDetail = mfContactOpenDetail;
window.mfContactExtractOpen = mfContactExtractOpen;
