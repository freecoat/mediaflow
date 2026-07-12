// app/static/js/mail.js — Client email /mail (Sotto-fase 1 + 2a azioni/organizzazione)
let _mailLabel = 'INBOX';
let _mailNextPage = null;
let _mailConnected = false;
let _mailAccount = null;            // email account (per reply-all)
let _mailSel = new Set();          // thread id selezionati (multi-select)
let _mailLabels = [];              // cache etichette (per dropdown "Sposta in")
let _mailAtts = [];                // File[] allegati compose (accumulanti, no replace)
let _mailSignature = '';           // firma HTML utente (auto-inserita nel compose)
let _mailPrefs = {mark_read_on_open: true, autosave: true, auto_refresh_sec: 120,
                  compose_new_window: false, default_font: 'Arial, sans-serif'};
let _mailDraftId = null;           // id bozza corrente (autosave)
let _mailAutosaveTimer = null;
let _mailRefreshTimer = null;
let _mailStandalone = false;       // true nella finestra pop-out /mail/compose

// Icone SVG inline (16px, stroke=currentColor). Gmail-like, sostituiscono le emoji.
const _MAIL_ICONS = {
  archive: '<svg class="mail-ico" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="4" rx="1"/><path d="M5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8"/><path d="M10 12h4"/></svg>',
  trash: '<svg class="mail-ico" viewBox="0 0 24 24"><path d="M4 7h16"/><path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/><path d="M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13"/></svg>',
  star: '<svg class="mail-ico" viewBox="0 0 24 24"><polygon points="12 2 15 9 22 9.3 16.6 14 18.5 21 12 17 5.5 21 7.4 14 2 9.3 9 9"/></svg>',
};
function mfMailIcon(name) { return _MAIL_ICONS[name] || ''; }

async function mfMailInit() {
  const st = await (await fetch('/mail/api/status')).json().catch(function () { return {connected: false}; });
  _mailConnected = !!st.connected;
  _mailAccount = st.account_email || null;
  if (!_mailConnected) {
    const box = document.getElementById('mail-reading');
    if (box) box.innerHTML = '<div class="mail-cta"><p>' + mfT('mail.notConnected') +
      '</p><a class="btn btn-primary" href="/auth/oauth/google/start?scopes=email">' +
      mfT('mail.connect') + '</a></div>';
    return;
  }
  await mfMailLoadPrefs();
  mfMailLoadLabels();
  mfMailLoadThreads(true);
  mfMailLoadContacts();
  mfMailLoadSignature();
  mfMailStartAutoRefresh();
  window.addEventListener('focus', mfMailOnFocus);
}

async function mfMailLoadSignature() {
  try {
    const d = await (await fetch('/mail/api/signature')).json();
    _mailSignature = d.signature || '';
  } catch (e) { _mailSignature = ''; }
}

async function mfMailLoadPrefs() {
  try {
    const d = await (await fetch('/mail/api/prefs')).json();
    if (d.prefs) _mailPrefs = d.prefs;
  } catch (e) { /* best-effort: default */ }
}

// ── Auto-sync: polling periodico + refresh su focus finestra ────────────
function mfMailStartAutoRefresh() {
  if (_mailRefreshTimer) { clearInterval(_mailRefreshTimer); _mailRefreshTimer = null; }
  const sec = parseInt(_mailPrefs.auto_refresh_sec, 10) || 0;
  if (sec > 0) {
    _mailRefreshTimer = setInterval(function () {
      // non disturbare mentre si scrive un'email
      const composing = document.getElementById('mail-compose');
      if (composing && composing.classList.contains('open')) return;
      mfMailLoadThreads(true);
      mfMailLoadLabels();
    }, sec * 1000);
  }
}

function mfMailOnFocus() {
  const composing = document.getElementById('mail-compose');
  if (composing && composing.classList.contains('open')) return;
  mfMailLoadThreads(true);
  mfMailLoadLabels();
}

async function mfMailLoadContacts() {
  try {
    const d = await (await fetch('/mail/api/contacts')).json();
    const dl = document.getElementById('mail-contacts');
    if (!dl) return;
    dl.innerHTML = (d.contacts || []).map(function (c) {
      const label = c.name ? (c.name + ' <' + c.email + '>') : c.email;
      return '<option value="' + escapeHtml(c.email) + '">' + escapeHtml(label) + '</option>';
    }).join('');
  } catch (e) { /* best-effort: autocomplete assente */ }
}

async function mfMailLoadLabels() {
  try {
    const d = await (await fetch('/mail/api/labels?counts=1')).json();
    _mailLabels = d.labels || [];
    const box = document.getElementById('mail-labels');
    if (!box) return;
    const cnt = {};
    _mailLabels.forEach(function (l) { cnt[l.id] = l.threads_unread || 0; });
    const sys = [['INBOX', mfT('mail.inbox')], ['STARRED', mfT('mail.star')],
                 ['SENT', mfT('mail.sent')], ['DRAFT', mfT('mail.drafts')], ['TRASH', mfT('mail.trash')]];
    const user = _mailLabels.filter(function (l) { return l.type === 'user'; });
    function badge(id) { return cnt[id] ? ' <span class="mail-label-count">' + cnt[id] + '</span>' : ''; }
    box.innerHTML = sys.map(function (p) {
      return '<a href="#" class="mail-label" data-label="' + p[0] + '">' + escapeHtml(p[1]) + badge(p[0]) + '</a>';
    }).join('') + user.map(function (l) {
      return '<a href="#" class="mail-label" data-label="' + escapeHtml(l.id) + '">' + escapeHtml(l.name) + badge(l.id) + '</a>';
    }).join('');
  } catch (e) { /* best-effort */ }
}

async function mfMailLoadThreads(reset) {
  if (reset) { _mailNextPage = null; _mailSel.clear(); mfMailSyncActionbar(); }
  const box = document.getElementById('mail-thread-list');
  if (!box) return;
  const q = (document.getElementById('mail-search') || {}).value || '';
  const params = new URLSearchParams({label: _mailLabel});
  if (q) params.set('q', q);
  if (_mailNextPage) params.set('page_token', _mailNextPage);
  try {
    const d = await (await fetch('/mail/api/threads?' + params.toString())).json();
    const rows = (d.threads || []).map(function (t) {
      const id = escapeHtml(t.id);
      const subj = t.subject || mfT('mail.noSubject');
      const from = t.from || '';
      let date = '';
      if (t.date) { const dd = new Date(t.date); if (!isNaN(dd.getTime())) date = dd.toLocaleDateString(); }
      const unread = t.unread ? ' mail-unread' : '';
      const sel = _mailSel.has(t.id) ? ' checked' : '';
      const starOn = t.starred ? ' mail-star-on' : '';
      const count = (t.msg_count && t.msg_count > 1) ? ' <span class="mail-row-count">' + t.msg_count + '</span>' : '';
      return '<div class="mail-thread-row' + unread + '" data-thread="' + id + '">' +
        '<input type="checkbox" class="mail-sel" data-sel="' + id + '"' + sel + '>' +
        '<button class="mail-star' + starOn + '" data-mail-star="' + id + '" title="' + escapeHtml(mfT('mail.star')) + '">' + mfMailIcon('star') + '</button>' +
        '<div class="mail-row-main">' +
        '<div class="mail-row-top"><span class="mail-row-from">' + escapeHtml(from) + '</span>' +
        '<span class="mail-row-date">' + escapeHtml(date) + '</span></div>' +
        '<div class="mail-row-subj">' + escapeHtml(subj) + count + '</div>' +
        '<div class="mail-row-snip">' + escapeHtml(t.snippet || '') + '</div></div>' +
        '<div class="mail-row-quick">' +
        '<button class="mail-q" data-mail-quick="archive" data-thread="' + id + '" title="' + escapeHtml(mfT('mail.archive')) + '">' + mfMailIcon('archive') + '</button>' +
        '<button class="mail-q" data-mail-quick="trash" data-thread="' + id + '" title="' + escapeHtml(mfT('mail.trash')) + '">' + mfMailIcon('trash') + '</button>' +
        '</div></div>';
    }).join('');
    box.innerHTML = (reset ? '' : box.innerHTML) + (rows || (reset ? '<div class="muted">' + mfT('mail.empty') + '</div>' : ''));
    _mailNextPage = d.next_page_token || null;
    const more = document.getElementById('mail-loadmore');
    if (more) more.style.display = _mailNextPage ? 'block' : 'none';
  } catch (e) { box.innerHTML = '<div class="muted">' + mfT('mail.empty') + '</div>'; }
}

function mfMailSyncActionbar() {
  const bar = document.getElementById('mail-actionbar');
  if (!bar) return;
  bar.style.display = _mailSel.size ? 'flex' : 'none';
  const c = document.getElementById('mail-sel-count');
  if (c) c.textContent = mfT('mail.selected').replace('{n}', _mailSel.size);
  const dd = document.getElementById('mail-move-select');
  if (dd && dd.options.length <= 1) {
    dd.innerHTML = '<option value="">' + escapeHtml(mfT('mail.moveTo')) + '</option>' +
      _mailLabels.filter(function (l) { return l.type === 'user'; }).map(function (l) {
        return '<option value="' + escapeHtml(l.id) + '">' + escapeHtml(l.name) + '</option>';
      }).join('');
  }
}

async function mfMailAction(action, labelId, ids) {
  const list = ids || [..._mailSel];
  if (!list.length) return;
  const fd = new FormData();
  fd.append('thread_ids', list.join(','));
  fd.append('action', action);
  if (labelId) fd.append('label_id', labelId);
  try {
    const r = await (await fetch('/mail/api/threads/action', {method: 'POST', body: fd})).json();
    if (r.failed && window.toast) toast(mfT('mail.actionPartial'), 'error');
    else if (window.toast) toast(mfT('mail.actionOk'), 'success');
  } catch (e) { if (window.toast) toast(mfT('email.error'), 'error'); }
  if (!ids) _mailSel.clear();
  mfMailLoadLabels();
  mfMailLoadThreads(true);
}

function _mailRenderBody(html) {
  // corpo email in iframe sandboxed (no script). Immagini remote bloccate: si
  // neutralizza src http(s) sostituendolo con data-blocked-src finché l'utente non clicca "Mostra immagini".
  const blocked = (html || '').replace(/(<img\b[^>]*?)\ssrc=/gi, '$1 data-blocked-src=');
  const doc = '<!doctype html><html><head><meta charset="utf-8">' +
    '<base target="_blank"></head><body>' + blocked + '</body></html>';
  return '<iframe class="mail-body-frame" sandbox="allow-popups allow-popups-to-escape-sandbox" srcdoc="' +
    doc.replace(/"/g, '&quot;') + '"></iframe>';
}

async function mfMailOpenThread(threadId) {
  mailMobileView('read');
  const box = document.getElementById('mail-reading');
  if (!box) return;
  try {
    const t = await (await fetch('/mail/api/thread/' + encodeURIComponent(threadId))).json();
    box.innerHTML = (t.messages || []).map(function (m) {
      const atts = (m.attachments || []).map(function (a) {
        return '<a class="mail-att" href="/mail/api/attachment/' + encodeURIComponent(m.id) + '/' +
          encodeURIComponent(a.id) + '?filename=' + encodeURIComponent(a.filename) +
          '&mime=' + encodeURIComponent(a.mime_type) + '">📎 ' + escapeHtml(a.filename) + '</a>';
      }).join(' ');
      const bodyHtml = m.body_html || ('<pre>' + escapeHtml(m.body_text || '') + '</pre>');
      return '<div class="mail-msg"><div class="mail-msg-head"><b>' + escapeHtml(m.from) +
        '</b><span class="muted"> · ' + escapeHtml(m.date) + '</span><div>' + escapeHtml(m.subject) +
        '</div></div>' + _mailRenderBody(bodyHtml) +
        ' <button class="btn btn-sm" data-mail-show-images>' + mfT('mail.showImages') + '</button>' +
        '<div class="mail-atts">' + atts + '</div>' +
        '<div class="mail-msg-actions">' +
        '<button class="btn btn-sm" data-mail-reply="' + escapeHtml(m.id) + '" data-thread="' + escapeHtml(threadId) + '">' + mfT('mail.reply') + '</button> ' +
        '<button class="btn btn-sm" data-mail-replyall="' + escapeHtml(m.id) + '" data-thread="' + escapeHtml(threadId) + '">' + mfT('mail.replyAll') + '</button> ' +
        '<button class="btn btn-sm" data-mail-forward="' + escapeHtml(m.id) + '">' + mfT('mail.forward') + '</button>' +
        '<button class="btn btn-sm" data-mail-assign="' + escapeHtml(threadId) + '">' + mfT('email.assign') + '</button>' +
        '</div></div>';
    }).join('') || '<div class="muted">' + mfT('mail.empty') + '</div>';
    // memorizza l'ultimo thread per reply/forward
    box._lastThread = t;
    if (_mailPrefs.mark_read_on_open) mfMailMarkReadLocal(threadId);
  } catch (e) { box.innerHTML = '<div class="muted">' + mfT('mail.sendError') + '</div>'; }
}

// Segna letto senza ricaricare tutta la lista: aggiorna solo la riga + backend.
function mfMailMarkReadLocal(threadId) {
  const row = document.querySelector('.mail-thread-row[data-thread="' + (window.CSS && CSS.escape ? CSS.escape(threadId) : threadId) + '"]');
  if (row && !row.classList.contains('mail-unread')) return;  // già letto
  if (row) row.classList.remove('mail-unread');
  const fd = new FormData();
  fd.append('thread_ids', threadId);
  fd.append('action', 'read');
  fetch('/mail/api/threads/action', {method: 'POST', body: fd}).catch(function () {});
}

function mfMailCompose(prefill) {
  prefill = prefill || {};
  // Finestra separata (pref) — solo dalla finestra principale, non da un pop-out.
  if (_mailPrefs.compose_new_window && !_mailStandalone) {
    const qs = new URLSearchParams();
    ['to', 'cc', 'subject', 'thread_id', 'in_reply_to'].forEach(function (k) {
      if (prefill[k]) qs.set(k, prefill[k]);
    });
    mfMailOpenPopout(qs.toString());
    return;
  }
  const ov = document.getElementById('mail-compose');
  if (!ov) return;
  ov.querySelector('[name=to]').value = prefill.to || '';
  ov.querySelector('[name=cc]').value = prefill.cc || '';
  ov.querySelector('[name=bcc]').value = '';
  ov.querySelector('[name=subject]').value = prefill.subject || '';
  ov.querySelector('[name=thread_id]').value = prefill.thread_id || '';
  ov.querySelector('[name=in_reply_to]').value = prefill.in_reply_to || '';
  ov.querySelector('[name=draft_id]').value = '';
  _mailDraftId = null;
  mfMailDraftStatus('');
  const titleEl = document.getElementById('mail-compose-title');
  if (titleEl) titleEl.textContent = mfT(prefill.thread_id ? 'mail.reply' : 'mail.newMessage');
  // corpo: prefill.bodyHtml (già HTML) oppure prefill.body (testo → nl2br) + firma in coda
  const ed = document.getElementById('mail-body-editor');
  let html = prefill.bodyHtml || (prefill.body ? escapeHtml(prefill.body).replace(/\n/g, '<br>') : '');
  if (_mailSignature) html += '<br><br>' + _mailSignature;
  if (ed) { ed.innerHTML = html; ed.style.fontFamily = _mailPrefs.default_font || 'Arial, sans-serif'; }
  _mailAtts = [];
  mfMailRenderAtts();
  if (window.openModal) openModal('mail-compose'); else ov.classList.add('open');
}

function mfMailOpenPopout(query) {
  const url = '/mail/compose' + (query ? ('?' + query) : '');
  window.open(url, 'mfCompose_' + Date.now(), 'width=820,height=680');
}

function mfMailCloseCompose() {
  if (_mailAutosaveTimer) { clearTimeout(_mailAutosaveTimer); _mailAutosaveTimer = null; }
  if (_mailStandalone) { window.close(); return; }
  if (window.closeModal) closeModal('mail-compose'); else {
    const ov = document.getElementById('mail-compose'); if (ov) ov.classList.remove('open');
  }
}

function mfMailDraftStatus(txt) {
  const el = document.getElementById('mail-draft-status');
  if (el) el.textContent = txt || '';
}

async function mfMailSend() {
  const ov = document.getElementById('mail-compose');
  if (!ov) return;
  if (!confirm(mfT('mail.sendConfirm'))) return;
  const fd = new FormData();
  ['to', 'cc', 'bcc', 'subject', 'thread_id', 'in_reply_to', 'references'].forEach(function (n) {
    const el = ov.querySelector('[name=' + n + ']');
    if (el && el.value) fd.append(n, el.value);
  });
  const ed = document.getElementById('mail-body-editor');
  const font = _mailPrefs.default_font || 'Arial, sans-serif';
  fd.append('body', ed ? '<div style="font-family:' + font + '">' + ed.innerHTML + '</div>' : '');
  _mailAtts.forEach(function (f) { fd.append('attachments', f); });
  try {
    const r = await (await fetch('/mail/api/send', {method: 'POST', body: fd})).json();
    if (r.ok) {
      if (window.toast) toast(mfT('mail.sentOk'), 'success');
      _mailAtts = []; _mailDraftId = null;
      mfMailCloseCompose();
      if (!_mailStandalone) mfMailLoadThreads(true);
    } else { if (window.toast) toast(mfT('mail.sendError'), 'error'); }
  } catch (e) { if (window.toast) toast(mfT('mail.sendError'), 'error'); }
}

// ── Autosave bozze (debounced) ─────────────────────────────────────────
function mfMailScheduleAutosave() {
  if (!_mailPrefs.autosave) return;
  if (_mailAutosaveTimer) clearTimeout(_mailAutosaveTimer);
  _mailAutosaveTimer = setTimeout(mfMailAutosave, 2500);
}

function _mailComposeFormData() {
  const ov = document.getElementById('mail-compose');
  const fd = new FormData();
  ['to', 'cc', 'bcc', 'subject', 'thread_id', 'in_reply_to', 'references'].forEach(function (n) {
    const el = ov.querySelector('[name=' + n + ']');
    if (el && el.value) fd.append(n, el.value);
  });
  const ed = document.getElementById('mail-body-editor');
  fd.append('body', ed ? ed.innerHTML : '');
  _mailAtts.forEach(function (f) { fd.append('attachments', f); });
  return fd;
}

async function mfMailAutosave() {
  const ov = document.getElementById('mail-compose');
  if (!ov) return;
  const ed = document.getElementById('mail-body-editor');
  const to = (ov.querySelector('[name=to]') || {}).value || '';
  const subj = (ov.querySelector('[name=subject]') || {}).value || '';
  if (!to && !subj && (!ed || !ed.textContent.trim())) return;  // niente da salvare
  try {
    const url = _mailDraftId ? ('/mail/api/draft/' + encodeURIComponent(_mailDraftId)) : '/mail/api/draft';
    const method = _mailDraftId ? 'PUT' : 'POST';
    const r = await (await fetch(url, {method: method, body: _mailComposeFormData()})).json();
    if (r.ok) { if (r.id) _mailDraftId = r.id; mfMailDraftStatus(mfT('mail.draftSaved')); }
  } catch (e) { /* best-effort */ }
}

async function mfMailSaveDraftNow() {
  if (_mailAutosaveTimer) { clearTimeout(_mailAutosaveTimer); _mailAutosaveTimer = null; }
  await mfMailAutosave();
  if (window.toast) toast(mfT('mail.draftSaved'), 'success');
}

function mfMailRenderAtts() {
  const tray = document.getElementById('mail-att-tray');
  if (!tray) return;
  tray.innerHTML = _mailAtts.map(function (f, i) {
    return '<span class="mail-att-chip">📎 ' + escapeHtml(f.name) +
      ' <button type="button" data-mail-att-rm="' + i + '" title="' + escapeHtml(mfT('mail.remove')) + '">✕</button></span>';
  }).join('');
}

function mfMailAddFiles(files) {
  for (const f of files || []) { if (f) _mailAtts.push(f); }
  mfMailRenderAtts();
}

async function mfMailSend() {
  const ov = document.getElementById('mail-compose');
  if (!ov) return;
  if (!confirm(mfT('mail.sendConfirm'))) return;
  const fd = new FormData();
  ['to', 'cc', 'bcc', 'subject', 'thread_id', 'in_reply_to', 'references'].forEach(function (n) {
    const el = ov.querySelector('[name=' + n + ']');
    if (el && el.value) fd.append(n, el.value);
  });
  const ed = document.getElementById('mail-body-editor');
  fd.append('body', ed ? ed.innerHTML : '');
  _mailAtts.forEach(function (f) { fd.append('attachments', f); });
  try {
    const r = await (await fetch('/mail/api/send', {method: 'POST', body: fd})).json();
    if (r.ok) { if (window.toast) toast(mfT('mail.sentOk'), 'success'); if (window.closeModal) closeModal('mail-compose'); else ov.classList.remove('open'); _mailAtts = []; mfMailLoadThreads(true); }
    else { if (window.toast) toast(mfT('mail.sendError'), 'error'); }
  } catch (e) { if (window.toast) toast(mfT('mail.sendError'), 'error'); }
}

// ── Editor ricco: toolbar (execCommand) ────────────────────────────────
function mfMailExec(cmd, value) {
  const ed = document.getElementById('mail-body-editor');
  if (ed) ed.focus();
  try { document.execCommand(cmd, false, value || null); } catch (e) { /* best-effort */ }
}

document.addEventListener('mousedown', function (ev) {
  // mantiene la selezione nell'editor mentre si clicca la toolbar
  if (ev.target.closest && ev.target.closest('#mail-toolbar') &&
      !ev.target.closest('input, select')) {
    ev.preventDefault();
  }
});

document.addEventListener('click', function (ev) {
  const cmdEl = ev.target.closest && ev.target.closest('[data-mail-cmd]');
  if (cmdEl && cmdEl.tagName !== 'SELECT') {   // i <select> si gestiscono da 'change'
    const raw = cmdEl.getAttribute('data-mail-cmd');
    if (raw.indexOf(':') > -1) { const p = raw.split(':'); mfMailExec(p[0], p[1]); }
    else mfMailExec(raw);
    return;
  }
  const linkEl = ev.target.closest && ev.target.closest('[data-mail-link]');
  if (linkEl) {
    const url = prompt(mfT('mail.linkPrompt'), 'https://');
    if (url) mfMailExec('createLink', url);
    return;
  }
  const attBtn = ev.target.closest && ev.target.closest('[data-mail-attach]');
  if (attBtn) { const fi = document.getElementById('mail-file-input'); if (fi) fi.click(); return; }
  const rm = ev.target.closest && ev.target.closest('[data-mail-att-rm]');
  if (rm) { _mailAtts.splice(parseInt(rm.getAttribute('data-mail-att-rm'), 10), 1); mfMailRenderAtts(); return; }
  const sig = ev.target.closest && ev.target.closest('[data-mail-signature]');
  if (sig) { mfMailOpenSignature(); return; }
  const mx = ev.target.closest && ev.target.closest('[data-mail-maximize]');
  if (mx) { const m = document.querySelector('.mail-compose-modal'); if (m) m.classList.toggle('mail-compose-max'); return; }
  const po = ev.target.closest && ev.target.closest('[data-mail-popout]');
  if (po) {
    const ov = document.getElementById('mail-compose');
    const qs = new URLSearchParams();
    ['to', 'cc', 'subject', 'thread_id', 'in_reply_to'].forEach(function (k) {
      const el = ov.querySelector('[name=' + k + ']'); if (el && el.value) qs.set(k, el.value);
    });
    mfMailCloseCompose();
    mfMailOpenPopout(qs.toString());
    return;
  }
});

// Autosave: qualsiasi input dentro il compose (ri)avvia il timer debounced.
document.addEventListener('input', function (ev) {
  if (ev.target.closest && ev.target.closest('#mail-compose')) mfMailScheduleAutosave();
});

// ── Impostazioni email ─────────────────────────────────────────────────
function mfMailOpenSettings() {
  const set = function (id, val) { const el = document.getElementById(id); if (el) el.checked = !!val; };
  set('mail-set-markread', _mailPrefs.mark_read_on_open);
  set('mail-set-autosave', _mailPrefs.autosave);
  set('mail-set-newwin', _mailPrefs.compose_new_window);
  const ref = document.getElementById('mail-set-refresh'); if (ref) ref.value = String(_mailPrefs.auto_refresh_sec);
  const fnt = document.getElementById('mail-set-font'); if (fnt) fnt.value = _mailPrefs.default_font || 'Arial, sans-serif';
  if (window.openModal) openModal('mail-settings-modal');
}

async function mfMailSaveSettings() {
  const fd = new FormData();
  fd.append('mark_read_on_open', document.getElementById('mail-set-markread').checked ? '1' : '0');
  fd.append('autosave', document.getElementById('mail-set-autosave').checked ? '1' : '0');
  fd.append('compose_new_window', document.getElementById('mail-set-newwin').checked ? '1' : '0');
  fd.append('auto_refresh_sec', document.getElementById('mail-set-refresh').value);
  fd.append('default_font', document.getElementById('mail-set-font').value);
  try {
    const r = await (await fetch('/mail/api/prefs', {method: 'POST', body: fd})).json();
    if (r.ok && r.prefs) {
      _mailPrefs = r.prefs;
      mfMailStartAutoRefresh();
      if (window.toast) toast(mfT('mail.settingsSaved'), 'success');
      if (window.closeModal) closeModal('mail-settings-modal');
    }
  } catch (e) { if (window.toast) toast(mfT('email.error'), 'error'); }
}

// ── Init finestra pop-out /mail/compose ────────────────────────────────
async function mfMailComposeStandalone() {
  _mailStandalone = true;
  if (typeof applyI18n === 'function') applyI18n(document);
  await mfMailLoadPrefs();
  await mfMailLoadSignature();
  mfMailLoadContacts();
  const p = new URLSearchParams(location.search);
  mfMailCompose({
    to: p.get('to') || '', cc: p.get('cc') || '', subject: p.get('subject') || '',
    thread_id: p.get('thread_id') || '', in_reply_to: p.get('in_reply_to') || '',
  });
  const m = document.querySelector('.mail-compose-modal'); if (m) m.classList.add('mail-compose-max');
  const po = document.querySelector('[data-mail-popout]'); if (po) po.style.display = 'none';
}

document.addEventListener('change', function (ev) {
  const sel = ev.target.closest && ev.target.closest('[data-mail-cmd]');
  if (sel && (sel.tagName === 'SELECT')) { mfMailExec(sel.getAttribute('data-mail-cmd'), sel.value); return; }
  if (ev.target.matches && ev.target.matches('[data-mail-color]')) { mfMailExec('foreColor', ev.target.value); return; }
  if (ev.target.id === 'mail-file-input') { mfMailAddFiles(ev.target.files); ev.target.value = ''; return; }
});

// ── Drag & drop allegati sull'editor ───────────────────────────────────
document.addEventListener('dragover', function (ev) {
  const ed = ev.target.closest && ev.target.closest('#mail-body-editor');
  if (ed) { ev.preventDefault(); ed.classList.add('mail-drop-hover'); }
});
document.addEventListener('dragleave', function (ev) {
  const ed = ev.target.closest && ev.target.closest('#mail-body-editor');
  if (ed) ed.classList.remove('mail-drop-hover');
});
document.addEventListener('drop', function (ev) {
  const ed = ev.target.closest && ev.target.closest('#mail-body-editor');
  if (!ed) return;
  const files = ev.dataTransfer && ev.dataTransfer.files;
  if (files && files.length) { ev.preventDefault(); mfMailAddFiles(files); }
  ed.classList.remove('mail-drop-hover');
});

// ── Firma persistente ──────────────────────────────────────────────────
function mfMailOpenSignature() {
  const ed = document.getElementById('mail-signature-editor');
  if (ed) ed.innerHTML = _mailSignature || '';
  if (window.openModal) openModal('mail-signature-modal');
}

async function mfMailSaveSignature() {
  const ed = document.getElementById('mail-signature-editor');
  const html = ed ? ed.innerHTML : '';
  const fd = new FormData();
  fd.append('signature', html);
  try {
    const r = await (await fetch('/mail/api/signature', {method: 'POST', body: fd})).json();
    if (r.ok) { _mailSignature = html; if (window.toast) toast(mfT('mail.signatureSaved'), 'success'); if (window.closeModal) closeModal('mail-signature-modal'); }
    else if (window.toast) toast(mfT('email.error'), 'error');
  } catch (e) { if (window.toast) toast(mfT('email.error'), 'error'); }
}

document.addEventListener('change', function (ev) {
  const cb = ev.target.closest && ev.target.closest('[data-sel]');
  if (cb) {
    const id = cb.getAttribute('data-sel');
    if (cb.checked) _mailSel.add(id); else _mailSel.delete(id);
    mfMailSyncActionbar();
    return;
  }
  if (ev.target.id === 'mail-move-select' && ev.target.value) {
    mfMailAction('move', ev.target.value);
    ev.target.value = '';
  }
});

document.addEventListener('click', function (ev) {
  const t = ev.target;
  // Stella su singolo thread
  const starBtn = t.closest && t.closest('[data-mail-star]');
  if (starBtn) {
    ev.stopPropagation();
    const on = starBtn.classList.contains('mail-star-on');
    mfMailAction(on ? 'unstar' : 'star', null, [starBtn.getAttribute('data-mail-star')]);
    return;
  }
  // Azioni rapide riga (archivia/cestino su singolo)
  const quick = t.closest && t.closest('[data-mail-quick]');
  if (quick) {
    ev.stopPropagation();
    mfMailAction(quick.getAttribute('data-mail-quick'), null, [quick.getAttribute('data-thread')]);
    return;
  }
  // Barra azioni bulk
  const act = t.closest && t.closest('[data-mail-action]');
  if (act) { mfMailAction(act.getAttribute('data-mail-action')); return; }
  if (t.closest && t.closest('.mail-sel')) return;  // il checkbox si gestisce da 'change'
  const lab = t.closest && t.closest('[data-label]');
  if (lab) { ev.preventDefault(); _mailLabel = lab.getAttribute('data-label'); mailMobileView('list'); mfMailLoadThreads(true); return; }
  const row = t.closest && t.closest('[data-thread]');
  if (row && row.classList.contains('mail-thread-row')) { mfMailOpenThread(row.getAttribute('data-thread')); return; }
  const rep = t.closest && t.closest('[data-mail-reply]');
  if (rep) {
    const box = document.getElementById('mail-reading');
    const thr = box && box._lastThread;
    const m = thr && (thr.messages || []).find(function (x) { return x.id === rep.getAttribute('data-mail-reply'); });
    if (m) mfMailCompose({to: m.from, subject: 'Re: ' + (m.subject || ''), thread_id: rep.getAttribute('data-thread'), body: ''});
    return;
  }
  const repAll = t.closest && t.closest('[data-mail-replyall]');
  if (repAll) {
    const box = document.getElementById('mail-reading');
    const thr = box && box._lastThread;
    const m = thr && (thr.messages || []).find(function (x) { return x.id === repAll.getAttribute('data-mail-replyall'); });
    if (m) {
      // cc = tutti i destinatari (to+cc) tranne la mia email
      const others = ((m.to || '') + ',' + (m.cc || '')).split(',').map(function (s) { return s.trim(); })
        .filter(function (s) { return s && (!_mailAccount || s.toLowerCase().indexOf(_mailAccount.toLowerCase()) === -1); });
      mfMailCompose({to: m.from, cc: others.join(', '), subject: 'Re: ' + (m.subject || ''),
                     thread_id: repAll.getAttribute('data-thread'), body: ''});
    }
    return;
  }
  const fw = t.closest && t.closest('[data-mail-forward]');
  if (fw) {
    const box = document.getElementById('mail-reading');
    const thr = box && box._lastThread;
    const m = thr && (thr.messages || []).find(function (x) { return x.id === fw.getAttribute('data-mail-forward'); });
    if (m) mfMailCompose({subject: 'Fwd: ' + (m.subject || ''), body: '\n\n---\n' + (m.body_text || '')});
    return;
  }
  const imgBtn = t.closest && t.closest('[data-mail-show-images]');
  if (imgBtn) {
    const frame = imgBtn.parentElement.querySelector('.mail-body-frame');
    if (frame) frame.setAttribute('srcdoc', frame.getAttribute('srcdoc').replace(/data-blocked-src=/gi, 'src='));
    return;
  }
  const asg = t.closest && t.closest('[data-mail-assign]');
  if (asg) { mfMailAssign(asg.getAttribute('data-mail-assign')); return; }
});

async function mfMailAssign(threadId) {
  try {
    const d = await (await fetch('/acquisitions/api/list')).json();
    const raw = (d.acquisitions || d.items || d || []);
    const list = Array.isArray(raw) ? raw : (raw.acquisitions || []);
    if (!list.length) { if (window.toast) toast(mfT('email.empty'), 'error'); return; }
    const label = list.map(function (a, i) {
      return (i + 1) + '. ' + (a.prospect_name || a.title || ('#' + a.id));
    }).join('\n');
    const pick = prompt(mfT('email.assign') + '\n' + label);
    if (!pick) return;
    const acq = list[parseInt(pick, 10) - 1];
    if (!acq) return;
    const fd = new FormData();
    fd.append('thread_id', threadId);
    const r = await fetch('/acquisitions/api/' + acq.id + '/emails/link', {method: 'POST', body: fd});
    if (r.ok) { if (window.toast) toast(mfT('email.assignOk'), 'success'); }
    else { if (window.toast) toast(mfT('email.error'), 'error'); }
  } catch (err) { if (window.toast) toast(mfT('email.error'), 'error'); }
}

function mailMobileView(view) {
  const layout = document.querySelector('.mail-layout');
  if (!layout) return;
  layout.setAttribute('data-mail-view', view);
  const back = document.getElementById('mail-mb-back');
  const labelsBtn = document.getElementById('mail-mb-labels');
  if (back) back.style.display = (view === 'read') ? 'inline-flex' : 'none';
  if (labelsBtn) labelsBtn.style.display = (view === 'read') ? 'none' : 'inline-flex';
}
