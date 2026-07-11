// app/static/js/mail.js — Client email /mail (Sotto-fase 1 + 2a azioni/organizzazione)
let _mailLabel = 'INBOX';
let _mailNextPage = null;
let _mailConnected = false;
let _mailAccount = null;            // email account (per reply-all)
let _mailSel = new Set();          // thread id selezionati (multi-select)
let _mailLabels = [];              // cache etichette (per dropdown "Sposta in")

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
  mfMailLoadLabels();
  mfMailLoadThreads(true);
  mfMailLoadContacts();
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
      const star = t.starred ? '★' : '☆';
      const starOn = t.starred ? ' mail-star-on' : '';
      const count = (t.msg_count && t.msg_count > 1) ? ' <span class="mail-row-count">' + t.msg_count + '</span>' : '';
      return '<div class="mail-thread-row' + unread + '" data-thread="' + id + '">' +
        '<input type="checkbox" class="mail-sel" data-sel="' + id + '"' + sel + '>' +
        '<button class="mail-star' + starOn + '" data-mail-star="' + id + '" title="' + escapeHtml(mfT('mail.star')) + '">' + star + '</button>' +
        '<div class="mail-row-main">' +
        '<div class="mail-row-top"><span class="mail-row-from">' + escapeHtml(from) + '</span>' +
        '<span class="mail-row-date">' + escapeHtml(date) + '</span></div>' +
        '<div class="mail-row-subj">' + escapeHtml(subj) + count + '</div>' +
        '<div class="mail-row-snip">' + escapeHtml(t.snippet || '') + '</div></div>' +
        '<div class="mail-row-quick">' +
        '<button class="mail-q" data-mail-quick="archive" data-thread="' + id + '" title="' + escapeHtml(mfT('mail.archive')) + '">🗄</button>' +
        '<button class="mail-q" data-mail-quick="trash" data-thread="' + id + '" title="' + escapeHtml(mfT('mail.trash')) + '">🗑</button>' +
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
  } catch (e) { box.innerHTML = '<div class="muted">' + mfT('mail.sendError') + '</div>'; }
}

function mfMailCompose(prefill) {
  prefill = prefill || {};
  const ov = document.getElementById('mail-compose');
  if (!ov) return;
  ov.querySelector('[name=to]').value = prefill.to || '';
  ov.querySelector('[name=cc]').value = prefill.cc || '';
  ov.querySelector('[name=subject]').value = prefill.subject || '';
  ov.querySelector('[name=body]').value = prefill.body || '';
  ov.querySelector('[name=thread_id]').value = prefill.thread_id || '';
  ov.querySelector('[name=in_reply_to]').value = prefill.in_reply_to || '';
  if (window.openModal) openModal('mail-compose'); else ov.classList.add('open');
}

async function mfMailSend() {
  const ov = document.getElementById('mail-compose');
  if (!ov) return;
  if (!confirm(mfT('mail.sendConfirm'))) return;
  const fd = new FormData();
  ['to', 'cc', 'bcc', 'subject', 'body', 'thread_id', 'in_reply_to', 'references'].forEach(function (n) {
    const el = ov.querySelector('[name=' + n + ']');
    if (el && el.value) fd.append(n, el.value);
  });
  const fileInp = ov.querySelector('[name=attachments]');
  if (fileInp && fileInp.files) { for (const f of fileInp.files) fd.append('attachments', f); }
  try {
    const r = await (await fetch('/mail/api/send', {method: 'POST', body: fd})).json();
    if (r.ok) { if (window.toast) toast(mfT('mail.sentOk'), 'success'); if (window.closeModal) closeModal('mail-compose'); else ov.classList.remove('open'); mfMailLoadThreads(true); }
    else { if (window.toast) toast(mfT('mail.sendError'), 'error'); }
  } catch (e) { if (window.toast) toast(mfT('mail.sendError'), 'error'); }
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
