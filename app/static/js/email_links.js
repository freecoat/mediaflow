// app/static/js/email_links.js — Client email F2: email agganciate alla trattativa
let _emClickBound = false;

function _emRenderBody(html) {
  // anteprima corpo in iframe sandboxed (no script), immagini remote bloccate.
  const blocked = (html || '').replace(/(<img\b[^>]*?)\ssrc=/gi, '$1 data-blocked-src=');
  const doc = '<!doctype html><html><head><meta charset="utf-8"><base target="_blank"></head><body>' +
    blocked + '</body></html>';
  return '<iframe class="mail-body-frame" sandbox="" srcdoc="' + doc.replace(/"/g, '&quot;') + '"></iframe>';
}

async function mfEmailList(aid) {
  const box = document.getElementById('em-list');
  if (!box) return;
  try {
    const d = await (await fetch('/acquisitions/api/' + encodeURIComponent(aid) + '/emails')).json();
    const emails = d.emails || [];
    if (!emails.length) { box.innerHTML = '<div class="muted" data-i18n="email.empty">' + mfT('email.empty') + '</div>'; return; }
    box.innerHTML = emails.map(function (e) {
      return '<div class="em-row" style="padding:6px 0;border-bottom:1px solid var(--border);">' +
        '<b>' + escapeHtml(e.subject || '') + '</b> <span class="muted">' + escapeHtml(e.from_addr || '') +
        ' · ' + escapeHtml(e.email_date || '') + '</span><div class="muted">' + escapeHtml(e.snippet || '') + '</div>' +
        '<div style="display:flex;gap:6px;margin-top:4px;">' +
        '<button class="btn btn-sm" data-em-preview="' + escapeHtml(e.thread_id) + '">' + mfT('email.expand') + '</button>' +
        '<button class="btn btn-sm" data-em-extract="' + escapeHtml(e.thread_id) + '">' + mfT('email.extract') + '</button>' +
        '<button class="btn btn-sm" data-em-remove="' + e.id + '" data-em-aid="' + escapeHtml(String(aid)) + '">🗑</button>' +
        '</div><div class="em-preview" id="em-prev-' + escapeHtml(e.thread_id) + '"></div></div>';
    }).join('');
  } catch (err) { box.innerHTML = '<div class="muted">' + mfT('email.error') + '</div>'; }
}

async function mfEmailSearch(aid) {
  const inp = document.getElementById('em-search');
  const box = document.getElementById('em-results');
  if (!inp || !box) return;
  const q = inp.value.trim();
  try {
    const d = await (await fetch('/mail/api/threads?q=' + encodeURIComponent(q))).json();
    const rows = (d.threads || []).map(function (t) {
      return '<div class="em-result" style="display:flex;gap:6px;align-items:center;padding:3px 0;">' +
        '<span style="flex:1;">' + escapeHtml(t.snippet || '(…)') + '</span>' +
        '<button class="btn btn-sm" data-em-pin="' + escapeHtml(t.id) + '" data-em-aid="' + escapeHtml(String(aid)) + '">' + mfT('email.pin') + '</button></div>';
    }).join('');
    box.innerHTML = rows || '<div class="muted">' + mfT('email.empty') + '</div>';
  } catch (err) { box.innerHTML = '<div class="muted">' + mfT('email.error') + '</div>'; }
}

async function mfEmailPin(aid, payload) {
  const fd = new FormData();
  Object.keys(payload || {}).forEach(function (k) { if (payload[k]) fd.append(k, payload[k]); });
  try {
    const r = await fetch('/acquisitions/api/' + encodeURIComponent(aid) + '/emails/link', {method: 'POST', body: fd});
    if (r.ok) { if (window.toast) toast(mfT('email.pinned'), 'success'); mfEmailList(aid); }
    else if (r.status === 400) { if (window.toast) toast(mfT('email.invalidUrl'), 'error'); }
    else { if (window.toast) toast(mfT('email.error'), 'error'); }
  } catch (err) { if (window.toast) toast(mfT('email.error'), 'error'); }
}

async function mfEmailPinUrl(aid) {
  const inp = document.getElementById('em-url');
  if (!inp || !inp.value.trim()) return;
  await mfEmailPin(aid, {url: inp.value.trim()});
  inp.value = '';
}

async function mfEmailPreview(threadId) {
  const box = document.getElementById('em-prev-' + threadId);
  if (!box) return;
  if (box.innerHTML) { box.innerHTML = ''; return; }  // toggle
  try {
    const t = await (await fetch('/mail/api/thread/' + encodeURIComponent(threadId))).json();
    const m = (t.messages || [])[0] || {};
    const html = m.body_html || ('<pre>' + escapeHtml(m.body_text || '') + '</pre>');
    box.innerHTML = _emRenderBody(html);
  } catch (err) { box.innerHTML = '<div class="muted">' + mfT('email.error') + '</div>'; }
}

async function mfEmailExtract(threadId) {
  // riusa il copilot (Fase 2): fetch corpo → inietta come il bottone 📥.
  try {
    const t = await (await fetch('/mail/api/thread/' + encodeURIComponent(threadId))).json();
    const body = (t.messages || []).map(function (m) { return m.body_text || ''; }).join('\n\n');
    const ta = document.getElementById('cp-input');
    if (ta && window.copilotSend) {
      ta.value = mfT('copilot.email.instruction') + '\n\n' + body;
      copilotSend();
    }
  } catch (err) { if (window.toast) toast(mfT('email.error'), 'error'); }
}

async function mfEmailRemove(id, aid) {
  try {
    const r = await fetch('/email-links/' + id, {method: 'DELETE'});
    if (r.ok) mfEmailList(aid);
  } catch (err) { if (window.toast) toast(mfT('email.error'), 'error'); }
}

function mfEmailInit(aid) {
  if (!_emClickBound) {
    _emClickBound = true;
    document.addEventListener('click', function (ev) {
      const t = ev.target;
      const pin = t.closest && t.closest('[data-em-pin]');
      if (pin) { mfEmailPin(pin.getAttribute('data-em-aid'), {thread_id: pin.getAttribute('data-em-pin')}); return; }
      const prev = t.closest && t.closest('[data-em-preview]');
      if (prev) { mfEmailPreview(prev.getAttribute('data-em-preview')); return; }
      const ext = t.closest && t.closest('[data-em-extract]');
      if (ext) { mfEmailExtract(ext.getAttribute('data-em-extract')); return; }
      const rem = t.closest && t.closest('[data-em-remove]');
      if (rem) { mfEmailRemove(rem.getAttribute('data-em-remove'), rem.getAttribute('data-em-aid')); return; }
    });
  }
  mfEmailList(aid);
}
