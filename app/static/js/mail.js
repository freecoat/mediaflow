// app/static/js/mail.js — Client email Sotto-fase 1: webmail /mail
let _mailLabel = 'INBOX';
let _mailNextPage = null;
let _mailConnected = false;

async function mfMailInit() {
  const st = await (await fetch('/mail/api/status')).json().catch(function () { return {connected: false}; });
  _mailConnected = !!st.connected;
  if (!_mailConnected) {
    const box = document.getElementById('mail-reading');
    if (box) box.innerHTML = '<div class="mail-cta"><p>' + mfT('mail.notConnected') +
      '</p><a class="btn btn-primary" href="/auth/oauth/google/start?scopes=email">' +
      mfT('mail.connect') + '</a></div>';
    return;
  }
  mfMailLoadLabels();
  mfMailLoadThreads(true);
}

async function mfMailLoadLabels() {
  try {
    const d = await (await fetch('/mail/api/labels')).json();
    const box = document.getElementById('mail-labels');
    if (!box) return;
    const sys = [['INBOX', mfT('mail.inbox')], ['SENT', mfT('mail.sent')], ['DRAFT', mfT('mail.drafts')]];
    const user = (d.labels || []).filter(function (l) { return l.type === 'user'; });
    box.innerHTML = sys.map(function (p) {
      return '<a href="#" class="mail-label" data-label="' + p[0] + '">' + escapeHtml(p[1]) + '</a>';
    }).join('') + user.map(function (l) {
      return '<a href="#" class="mail-label" data-label="' + escapeHtml(l.id) + '">' + escapeHtml(l.name) + '</a>';
    }).join('');
  } catch (e) { /* best-effort */ }
}

function _mailFromName(from) {
  // "Anna Rossi <anna@a24.com>" -> "Anna Rossi"; "anna@a24.com" -> "anna@a24.com"
  if (!from) return '';
  const m = from.match(/^\s*"?([^"<]*?)"?\s*<[^>]+>\s*$/);
  const name = m && m[1].trim();
  return name || from.replace(/[<>]/g, '').trim();
}

function _mailShortDate(d) {
  // Date RFC2822 dagli header. Oggi -> ora, altrimenti giorno/mese.
  if (!d) return '';
  const dt = new Date(d);
  if (isNaN(dt.getTime())) return '';
  const now = new Date();
  const sameDay = dt.getDate() === now.getDate() && dt.getMonth() === now.getMonth()
    && dt.getFullYear() === now.getFullYear();
  const lang = (window.mfCurrentLang ? mfCurrentLang() : 'it');
  return sameDay ? dt.toLocaleTimeString(lang, {hour: '2-digit', minute: '2-digit'})
                 : dt.toLocaleDateString(lang, {day: '2-digit', month: 'short'});
}

async function mfMailLoadThreads(reset) {
  if (reset) { _mailNextPage = null; }
  const box = document.getElementById('mail-thread-list');
  if (!box) return;
  const q = (document.getElementById('mail-search') || {}).value || '';
  const params = new URLSearchParams({label: _mailLabel});
  if (q) params.set('q', q);
  if (_mailNextPage) params.set('page_token', _mailNextPage);
  try {
    const d = await (await fetch('/mail/api/threads?' + params.toString())).json();
    const rows = (d.threads || []).map(function (t) {
      // Oggetto e anteprima sono cose diverse: l'oggetto viene dagli header,
      // lo snippet è il corpo. Mai usare il secondo al posto del primo.
      const count = (t.message_count || 0) > 1 ? ' (' + t.message_count + ')' : '';
      const ell = 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
      return '<div class="mail-thread-row" data-thread="' + escapeHtml(t.id) + '" ' +
        'style="display:flex;flex-direction:column;gap:2px;padding:8px;border-radius:6px;cursor:pointer;">' +
        '<div style="display:flex;justify-content:space-between;gap:8px;font-size:.85em;">' +
        '<span style="' + ell + '">' + escapeHtml(_mailFromName(t.from)) + '</span>' +
        '<span class="muted" style="flex:none;">' + escapeHtml(_mailShortDate(t.date)) + '</span></div>' +
        '<div style="font-weight:600;' + ell + '">' +
        escapeHtml(t.subject || mfT('mail.nosubject')) + count + '</div>' +
        '<div class="muted" style="font-size:.85em;' + ell + '">' + escapeHtml(t.snippet || '') + '</div>' +
        '</div>';
    }).join('');
    box.innerHTML = (reset ? '' : box.innerHTML) + (rows || '<div class="muted">' + mfT('mail.empty') + '</div>');
    _mailNextPage = d.next_page_token || null;
  } catch (e) { box.innerHTML = '<div class="muted">' + mfT('mail.empty') + '</div>'; }
}

// Foglio di stile iniettato nel frame: l'HTML delle email non porta quasi mai
// un font-size di base, e senza questo il corpo cade sui default UA (Times 16px
// su fondo bianco, <pre> monospace 13px) — illeggibile accanto al resto della UI.
const _MAIL_BODY_CSS =
  'html,body{margin:0;padding:12px;background:#fff;color:#202124;' +
  'font:15px/1.6 -apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,Helvetica,Arial,sans-serif;' +
  'overflow-wrap:break-word;word-break:break-word;}' +
  'img{max-width:100%;height:auto;}' +
  'table{max-width:100%;}' +
  'pre{white-space:pre-wrap;overflow-wrap:break-word;margin:0;' +
  'font:14px/1.6 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;}' +
  'a{color:#1a73e8;}' +
  'blockquote{margin:0 0 0 6px;padding-left:10px;border-left:2px solid #dadce0;color:#5f6368;}';

// Altezza del frame = altezza reale del contenuto. Serve leggere il documento
// interno, e per farlo il frame deve condividere l'origine del parent
// (sandbox="allow-same-origin"). Resta SENZA allow-scripts: nessun JS gira
// dentro, quindi l'HTML dell'email non diventa eseguibile.
function mfMailFitFrame(fr) {
  try {
    const d = fr.contentDocument;
    if (!d || !d.body) return;
    const h = Math.max(d.body.scrollHeight, d.documentElement.scrollHeight);
    fr.style.height = Math.min(Math.max(h + 4, 48), 20000) + 'px';
  } catch (e) {
    fr.style.height = '420px';  // origine opaca (sandbox stretto): fallback fisso
  }
}

// Le immagini finiscono di caricare dopo l'onload e allungano il documento:
// una seconda misura le recupera senza scomodare un observer nel frame.
function mfMailFitFrameLater(fr) {
  mfMailFitFrame(fr);
  setTimeout(function () { mfMailFitFrame(fr); }, 400);
}

function _mailRenderBody(html) {
  // corpo email in iframe sandboxed (no script). Immagini remote bloccate: si
  // neutralizza src http(s) sostituendolo con data-blocked-src finché l'utente non clicca "Mostra immagini".
  const blocked = (html || '').replace(/(<img\b[^>]*?)\ssrc=/gi, '$1 data-blocked-src=');
  const doc = '<!doctype html><html><head><meta charset="utf-8">' +
    '<base target="_blank"><style>' + _MAIL_BODY_CSS + '</style></head><body>' +
    blocked + '</body></html>';
  // & prima di ": in un attributo srcdoc "&amp;" si decodifica in "&", quindi
  // senza questo passaggio le entità del corpo email verrebbero mangiate.
  const attr = doc.replace(/&/g, '&amp;').replace(/"/g, '&quot;');
  return '<iframe class="mail-body-frame" sandbox="allow-same-origin" ' +
    'onload="mfMailFitFrameLater(this)" srcdoc="' + attr + '"></iframe>';
}

async function mfMailOpenThread(threadId) {
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
        '<button class="btn btn-sm" data-mail-forward="' + escapeHtml(m.id) + '">' + mfT('mail.forward') + '</button>' +
        '<button class="btn btn-sm" data-mail-assign="' + escapeHtml(threadId) + '">' + mfT('email.assign') + '</button> ' +
        '<button class="btn btn-sm" data-mail-extract-contact="' + escapeHtml(threadId) + '">' + mfT('email.extractContact') + '</button>' +
        '</div><div class="mail-contact-cands" id="mail-cands-' + escapeHtml(threadId) + '"></div></div>';
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
  ov.classList.remove('hidden');
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
    if (r.ok) { if (window.toast) toast(mfT('mail.sentOk'), 'success'); ov.classList.add('hidden'); mfMailLoadThreads(true); }
    else { if (window.toast) toast(mfT('mail.sendError'), 'error'); }
  } catch (e) { if (window.toast) toast(mfT('mail.sendError'), 'error'); }
}

document.addEventListener('click', function (ev) {
  const t = ev.target;
  const lab = t.closest && t.closest('[data-label]');
  if (lab) { ev.preventDefault(); _mailLabel = lab.getAttribute('data-label'); mfMailLoadThreads(true); return; }
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
  const extc = t.closest && t.closest('[data-mail-extract-contact]');
  if (extc && window.mfContactExtractOpen) {
    const tid = extc.getAttribute('data-mail-extract-contact');
    mfContactExtractOpen(tid, 'mail-cands-' + tid);
    return;
  }
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
