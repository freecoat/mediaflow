/* Media Library (Fase A) — browser unificato read-only asset digitali+fisici.
 * Vanilla JS, pattern helper globali: api(method,url), escapeHtml(), mfT(),
 * applyI18n(). Nessuna azione mutante: i bulk sono disabilitati.
 * v3.5.0-alpha.172.244 (feat/media-library). */

let _mediaOffset = 0;
const _mediaLimit = 50;
let _mediaSel = new Set();          // chiavi "nature:id"
let _mediaRowIndex = {};            // "nature:id" -> row (per dettaglio/selezione)
let _mediaDebounce = null;

const _MEDIA_FILTER_FIELDS = [
  'nature', 'project', 'client', 'department', 'asset_type', 'physical_kind',
  'delivery_status', 'linked_to_delivery', 'tech_resolution', 'tech_codec',
];
const _MEDIA_CHECK_FIELDS = ['internal_archive', 'delivered_external'];

function _mediaKey(r) { return r.nature + ':' + r.id; }

function mfMediaCollectFilters() {
  const f = {};
  _MEDIA_FILTER_FIELDS.forEach(k => {
    // project/client -> project_id/client_id ecc.
    const el = document.getElementById('media-f-' + k);
    if (!el || !el.value) return;
    const key = (k === 'project' || k === 'client' || k === 'department') ? k + '_id' : k;
    f[key] = el.value;
  });
  _MEDIA_CHECK_FIELDS.forEach(k => {
    const el = document.getElementById('media-f-' + k);
    if (el && el.checked) f[k] = '1';
  });
  const q = document.getElementById('media-q');
  if (q && q.value.trim()) f.q = q.value.trim();
  const prop = document.getElementById('media-f-proposals');
  if (prop && prop.checked) f.proposed_state = 'pending_review';
  return f;
}

async function mfMediaInit() {
  try {
    const opt = await api('GET', '/media/api/filters');
    _mediaFillSelect('media-f-project', (opt.projects || []).map(p => ({ v: p.id, t: (p.code ? p.code + ' — ' : '') + (p.title || '') })));
    _mediaFillSelect('media-f-client', (opt.clients || []).map(c => ({ v: c.id, t: c.name })));
    _mediaFillSelect('media-f-department', (opt.departments || []).map(d => ({ v: d.id, t: d.name })));
    _mediaFillSelect('media-f-asset_type', (opt.asset_types || []).map(x => ({ v: x, t: x })));
    _mediaFillSelect('media-f-physical_kind', (opt.physical_kinds || []).map(x => ({ v: x, t: x.toUpperCase() })));
    _mediaFillSelect('media-f-delivery_status', (opt.delivery_statuses || []).map(x => ({ v: x, t: x })));
    const tech = opt.tech || {};
    _mediaFillSelect('media-f-tech_resolution', (tech.resolution || []).map(x => ({ v: x, t: x })));
    _mediaFillSelect('media-f-tech_codec', (tech.codec || []).map(x => ({ v: x, t: x })));
  } catch (e) { console.error('media filters', e); }
  mfMediaLoad(true);
}

function _mediaFillSelect(id, items) {
  const el = document.getElementById(id);
  if (!el) return;
  const placeholder = el.querySelector('option') ? el.querySelector('option').outerHTML : '<option value=""></option>';
  el.innerHTML = placeholder + items.map(it =>
    `<option value="${escapeHtml(String(it.v))}">${escapeHtml(String(it.t))}</option>`).join('');
}

function mfMediaDebouncedLoad() {
  clearTimeout(_mediaDebounce);
  _mediaDebounce = setTimeout(() => mfMediaLoad(true), 300);
}

async function mfMediaLoad(reset) {
  if (reset) { _mediaOffset = 0; document.getElementById('media-tbody').innerHTML = ''; }
  const f = mfMediaCollectFilters();
  const params = new URLSearchParams(f);
  params.set('offset', _mediaOffset);
  params.set('limit', _mediaLimit);
  let out;
  try {
    out = await api('GET', '/media/api/assets?' + params.toString());
  } catch (e) { console.error('media load', e); toast(mfT('media.loadError'), 'error'); return; }

  const rows = out.rows || [];
  rows.forEach(r => { _mediaRowIndex[_mediaKey(r)] = r; });
  _mediaRenderRows(rows, reset);

  document.getElementById('media-count').textContent =
    (out.total != null ? out.total : rows.length) + ' ' + mfT('media.items');
  const more = document.getElementById('media-loadmore');
  if (out.next_offset != null) { _mediaOffset = out.next_offset; more.style.display = ''; }
  else { more.style.display = 'none'; }

  const tbody = document.getElementById('media-tbody');
  document.getElementById('media-empty').style.display = tbody.children.length ? 'none' : '';
  mfMediaSyncBar();
}

function _mediaFmtSize(bytes) {
  if (!bytes) return '—';
  const u = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  let i = 0, n = bytes;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return n.toFixed(n >= 10 || i === 0 ? 0 : 1) + ' ' + u[i];
}

function _mediaStatusBadge(r) {
  if (r.linked_to_delivery && r.delivery_status) {
    return `<span class="badge">${escapeHtml(r.delivery_status)}</span>`;
  }
  if (r.proposed_state && r.proposed_state !== 'confirmed') {
    return `<span class="badge" style="opacity:.7;">${escapeHtml(r.proposed_state)}</span>`;
  }
  return '<span class="text-muted">—</span>';
}

function _mediaRenderRows(rows, reset) {
  const tbody = document.getElementById('media-tbody');
  if (reset) tbody.innerHTML = '';
  const html = rows.map(r => {
    const key = _mediaKey(r);
    const proj = r.project ? (r.project.code || r.project.title || '') : '';
    const cli = r.client ? r.client.name : '';
    const projCli = [proj, cli].filter(Boolean).map(escapeHtml).join(' · ') || '<span class="text-muted">—</span>';
    const type = r.nature === 'digital'
      ? (r.asset_type || '') : (r.physical_kind ? r.physical_kind.toUpperCase() : '');
    const natLabel = mfT(r.nature === 'digital' ? 'media.digital' : 'media.physical');
    const natIcon = r.nature === 'digital' ? '🎞️' : '📦';
    const storage = r.storage && r.storage.path ? escapeHtml(r.storage.path) : '<span class="text-muted">—</span>';
    const cks = r.checksum ? escapeHtml(String(r.checksum).slice(0, 10)) : '<span class="text-muted">—</span>';
    const checked = _mediaSel.has(key) ? 'checked' : '';
    return `<tr data-key="${escapeHtml(key)}" style="cursor:pointer;">
      <td><input type="checkbox" ${checked} onclick="event.stopPropagation();mfMediaToggleRow('${escapeHtml(key)}',this.checked)"></td>
      <td onclick="mfMediaOpenDetail('${escapeHtml(key)}')">${escapeHtml(r.name || '')}</td>
      <td onclick="mfMediaOpenDetail('${escapeHtml(key)}')">${natIcon} ${escapeHtml(natLabel)}</td>
      <td onclick="mfMediaOpenDetail('${escapeHtml(key)}')">${escapeHtml(type)}</td>
      <td onclick="mfMediaOpenDetail('${escapeHtml(key)}')">${projCli}</td>
      <td onclick="mfMediaOpenDetail('${escapeHtml(key)}')">${_mediaStatusBadge(r)}</td>
      <td onclick="mfMediaOpenDetail('${escapeHtml(key)}')" style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${storage}</td>
      <td onclick="mfMediaOpenDetail('${escapeHtml(key)}')"><code style="font-size:11px;">${cks}</code></td>
      <td class="text-right" onclick="mfMediaOpenDetail('${escapeHtml(key)}')">${_mediaFmtSize(r.size_bytes)}</td>
    </tr>`;
  }).join('');
  tbody.insertAdjacentHTML('beforeend', html);
}

function mfMediaToggleRow(key, on) {
  if (on) _mediaSel.add(key); else _mediaSel.delete(key);
  mfMediaSyncBar();
}

function mfMediaToggleAll(on) {
  document.querySelectorAll('#media-tbody tr').forEach(tr => {
    const key = tr.getAttribute('data-key');
    const cb = tr.querySelector('input[type=checkbox]');
    if (cb) cb.checked = on;
    if (on) _mediaSel.add(key); else _mediaSel.delete(key);
  });
  mfMediaSyncBar();
}

function mfMediaSyncBar() {
  const n = _mediaSel.size;
  const bar = document.getElementById('media-actionbar');
  bar.style.display = n ? '' : 'none';
  if (n) document.getElementById('media-sel-count').textContent =
    mfT('media.selected').replace('{n}', n);
}

function mfMediaResetFilters() {
  document.querySelectorAll('.media-filters select').forEach(s => { s.value = ''; });
  document.querySelectorAll('.media-filters input[type=checkbox]').forEach(c => { c.checked = false; });
  const q = document.getElementById('media-q'); if (q) q.value = '';
  mfMediaLoad(true);
}

async function mfMediaOpenDetail(key) {
  const r = _mediaRowIndex[key];
  if (!r) return;
  let d;
  try { d = await api('GET', `/media/api/asset/${r.nature}/${r.id}`); }
  catch (e) { toast(mfT('media.loadError'), 'error'); return; }
  const panel = document.getElementById('media-detail');
  const body = document.getElementById('media-detail-body');
  const rows = [];
  const kv = (label, val) => rows.push(
    `<div style="margin-bottom:6px;"><span class="text-muted text-sm">${escapeHtml(label)}</span><br>${val}</div>`);
  kv(mfT('media.colName'), `<strong>${escapeHtml(d.name || '')}</strong>`);
  kv(mfT('media.nature'), escapeHtml(mfT(d.nature === 'digital' ? 'media.digital' : 'media.physical')));
  if (d.project) kv(mfT('media.fltProject'), escapeHtml((d.project.code || '') + ' ' + (d.project.title || '')));
  if (d.client) kv(mfT('media.fltClient'), escapeHtml(d.client.name));
  if (d.department) kv(mfT('media.fltDepartment'), escapeHtml(d.department.name));
  kv(mfT('media.linkedDelivery'), d.linked_to_delivery
    ? escapeHtml(d.delivery_status || 'yes') : '—');
  if (d.storage && d.storage.path) kv(mfT('media.storage'), `<code style="font-size:11px;word-break:break-all;">${escapeHtml(d.storage.path)}</code>`);
  if (d.checksum) kv(mfT('media.checksum'), `<code style="font-size:11px;word-break:break-all;">${escapeHtml(d.checksum)}</code>`);
  kv(mfT('media.size'), _mediaFmtSize(d.size_bytes));
  if (d.tech && (d.tech.resolution || d.tech.codec)) {
    kv(mfT('media.tech'), escapeHtml([d.tech.resolution, d.tech.codec, d.tech.frame_rate].filter(Boolean).join(' · ')));
  }
  if (Array.isArray(d.deliverables) && d.deliverables.length) {
    const dl = d.deliverables.map(x =>
      `<li style="${x.superseded ? 'text-decoration:line-through;opacity:.6;' : ''}">${escapeHtml(x.job || '')} — <em>${escapeHtml(x.status || '')}</em>${x.superseded ? ' <span class="badge">' + escapeHtml(mfT('media.superseded')) + '</span>' : ''}</li>`).join('');
    kv(mfT('media.deliverables'), `<ul style="margin:4px 0 0 16px;">${dl}</ul>`);
  }
  body.innerHTML = rows.join('');
  panel.style.display = '';
}

function mfMediaCloseDetail() {
  document.getElementById('media-detail').style.display = 'none';
}

/* ── Azioni bulk (Fase B) ───────────────────────────────────────── */

let _mediaAssocMode = 'associate';   // 'associate' | 'unlink'
let _mediaAssocDebounce = null;

function _mediaSelItems() {
  return Array.from(_mediaSel).map(k => {
    const i = k.indexOf(':');
    return { nature: k.slice(0, i), id: parseInt(k.slice(i + 1), 10) };
  });
}

async function _mediaOpenAssocModal(mode) {
  if (!_mediaSel.size) { toast(mfT('media.selectFirst'), 'error'); return; }
  _mediaAssocMode = mode;
  document.getElementById('media-assoc-title').textContent =
    mfT(mode === 'unlink' ? 'media.unlinkTitle' : 'media.assocTitle');
  document.getElementById('media-assoc-reason-row').style.display = mode === 'unlink' ? 'none' : '';
  document.getElementById('assoc-reason').value = '';
  document.getElementById('assoc-search').value = '';
  document.getElementById('assoc-project').innerHTML = '<option value=""></option>';
  document.getElementById('assoc-deliverable').innerHTML = '<option value=""></option>';
  try {
    const opt = await api('GET', '/media/api/filters');
    _mediaFillSelect('assoc-project',
      (opt.projects || []).map(p => ({ v: p.id, t: (p.code ? p.code + ' — ' : '') + (p.title || '') })));
  } catch (e) { console.error('assoc filters', e); }
  openModal('media-assoc-modal');
  mfMediaAssocLoadDeliv();
}

function mfMediaOpenAssociate() { _mediaOpenAssocModal('associate'); }
function mfMediaUnlinkPrompt() { _mediaOpenAssocModal('unlink'); }

function mfMediaAssocDebounced() {
  clearTimeout(_mediaAssocDebounce);
  _mediaAssocDebounce = setTimeout(mfMediaAssocLoadDeliv, 300);
}

async function mfMediaAssocLoadDeliv() {
  const pid = document.getElementById('assoc-project').value;
  const q = document.getElementById('assoc-search').value.trim();
  const params = new URLSearchParams();
  if (pid) params.set('project_id', pid);
  if (q) params.set('q', q);
  let list = [];
  try { list = await api('GET', '/media/api/deliverables?' + params.toString()); }
  catch (e) { console.error('assoc deliv', e); }
  const sel = document.getElementById('assoc-deliverable');
  sel.innerHTML = '<option value=""></option>' + list.map(d =>
    `<option value="${d.id}">${escapeHtml((d.project ? d.project.code + ' · ' : '') + d.name + ' [' + d.status + ']')}</option>`).join('');
}

async function mfMediaConfirmAssociate() {
  const did = document.getElementById('assoc-deliverable').value;
  if (!did) { toast(mfT('media.pickDeliverable'), 'error'); return; }
  const fd = new FormData();
  fd.append('deliverable_id', did);
  fd.append('items', JSON.stringify(_mediaSelItems()));
  const url = _mediaAssocMode === 'unlink' ? '/media/api/unlink' : '/media/api/associate';
  if (_mediaAssocMode !== 'unlink') {
    const reason = document.getElementById('assoc-reason').value.trim();
    if (reason) fd.append('reason', reason);
  }
  try {
    const out = await api('POST', url, fd);
    if (_mediaAssocMode === 'unlink') {
      toast(mfT('media.unlinkDone').replace('{n}', out.removed), 'success');
    } else {
      toast(mfT('media.assocDone').replace('{n}', out.linked).replace('{s}', out.superseded), 'success');
    }
    closeModal('media-assoc-modal');
    _mediaSel.clear();
    mfMediaLoad(true);
  } catch (e) { console.error(e); toast(mfT('media.actionError'), 'error'); }
}

async function mfMediaArchive(on) {
  if (!_mediaSel.size) { toast(mfT('media.selectFirst'), 'error'); return; }
  const fd = new FormData();
  fd.append('items', JSON.stringify(_mediaSelItems()));
  fd.append('internal_archive', on ? '1' : '0');
  try {
    const out = await api('POST', '/media/api/flags', fd);
    toast(mfT('media.flagsDone').replace('{n}', out.updated), 'success');
    _mediaSel.clear();
    mfMediaLoad(true);
  } catch (e) { console.error(e); toast(mfT('media.actionError'), 'error'); }
}

function mfMediaExport() {
  const suffix = _mediaSel.size
    ? '?items=' + encodeURIComponent(JSON.stringify(_mediaSelItems()))
    : '?' + new URLSearchParams(mfMediaCollectFilters()).toString();
  window.location = '/media/api/export' + suffix;
}
