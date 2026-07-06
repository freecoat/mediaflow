// app/static/js/documents.js — Fase D: documenti Drive collegati (progetto/acquisition)
async function mfDocList(linkedType, linkedId) {
  const box = document.getElementById('doc-list-' + linkedType);
  if (!box) return;
  try {
    const r = await fetch('/documents/api/list?linked_type=' + encodeURIComponent(linkedType) +
      '&linked_id=' + encodeURIComponent(linkedId));
    const d = await r.json();
    const docs = d.documents || [];
    if (!docs.length) { box.innerHTML = '<div class="text-muted text-sm" data-i18n="doc.empty">' + mfT('doc.empty') + '</div>'; return; }
    box.innerHTML = docs.map(function (doc) {
      const icon = doc.icon_url ? '<img src="' + escapeHtml(doc.icon_url) + '" width="16" height="16" alt="">' : '📄';
      const owner = doc.owner_email ? '<span class="text-muted text-xs"> · ' + escapeHtml(doc.owner_email) + '</span>' : '';
      const safe = /^https?:\/\//i.test(doc.web_url || '') ? doc.web_url : '#';
      return '<div class="doc-row" style="display:flex;align-items:center;gap:6px;padding:6px 0;border-bottom:1px solid var(--border);">' + icon +
        ' <a href="' + escapeHtml(safe) + '" target="_blank" rel="noopener noreferrer" style="color:var(--indigo2);">' + escapeHtml(doc.name) + '</a>' +
        owner +
        '<span style="flex:1;"></span>' +
        ' <button class="btn btn-ghost btn-icon btn-sm" title="' + mfT('doc.remove') + '" data-doc-remove="' + doc.id +
        '" data-doc-type="' + escapeHtml(linkedType) + '" data-doc-linked="' + escapeHtml(String(linkedId)) + '">🗑</button></div>';
    }).join('');
  } catch (e) { box.innerHTML = '<div class="text-muted text-sm">' + mfT('doc.error') + '</div>'; }
}

async function mfDocAddByUrl(linkedType, linkedId) {
  const inp = document.getElementById('doc-url-' + linkedType);
  if (!inp || !inp.value.trim()) return;
  const fd = new FormData();
  fd.append('linked_type', linkedType);
  fd.append('linked_id', linkedId);
  fd.append('url', inp.value.trim());
  try {
    const r = await fetch('/documents/api/link', { method: 'POST', body: fd });
    if (r.ok) { inp.value = ''; if (window.toast) toast(mfT('doc.added'), 'success'); mfDocList(linkedType, linkedId); }
    else if (r.status === 400) { if (window.toast) toast(mfT('doc.invalidUrl'), 'error'); }
    else { if (window.toast) toast(mfT('doc.error'), 'error'); }
  } catch (e) { if (window.toast) toast(mfT('doc.error'), 'error'); }
}

async function mfDocRemove(docId, linkedType, linkedId) {
  try {
    const r = await fetch('/documents/api/link/' + docId, { method: 'DELETE' });
    if (r.ok) mfDocList(linkedType, linkedId);
  } catch (e) { if (window.toast) toast(mfT('doc.error'), 'error'); }
}

async function mfDocPicker(linkedType, linkedId) {
  try {
    const cfg = await (await fetch('/documents/api/picker-config')).json();
    if (!cfg.enabled) return;
    await new Promise(function (res) { gapi.load('picker', { callback: res }); });
    const view = new google.picker.DocsView(google.picker.ViewId.DOCS).setIncludeFolders(true);
    const picker = new google.picker.PickerBuilder()
      .setOAuthToken(cfg.oauth_token).setDeveloperKey(cfg.api_key).setAppId(cfg.app_id)
      .addView(view)
      .setCallback(function (data) {
        if (data.action !== google.picker.Action.PICKED) return;
        const f = data.docs[0];
        const fd = new FormData();
        fd.append('linked_type', linkedType); fd.append('linked_id', linkedId);
        fd.append('file_id', f.id); fd.append('name', f.name || '');
        fd.append('mime_type', f.mimeType || '');
        fd.append('web_url', f.url || ('https://drive.google.com/file/d/' + f.id + '/view'));
        fd.append('icon_url', (f.iconUrl || ''));
        fetch('/documents/api/link', { method: 'POST', body: fd }).then(function (r) {
          if (r.ok) { if (window.toast) toast(mfT('doc.added'), 'success'); mfDocList(linkedType, linkedId); }
        });
      }).build();
    picker.setVisible(true);
  } catch (e) { if (window.toast) toast(mfT('doc.error'), 'error'); }
}

// v3.5.0-alpha (Fase D) — handler delegato rimozione: bindato una sola volta
// su document (mfDocInit può essere chiamato più volte, es. ogni apertura
// pannello dettaglio trattativa in acquisitions.html).
let _mfDocClickBound = false;

async function mfDocInit(linkedType, linkedId) {
  if (!_mfDocClickBound) {
    _mfDocClickBound = true;
    document.addEventListener('click', function (ev) {
      const b = ev.target.closest && ev.target.closest('[data-doc-remove]');
      if (!b) return;
      mfDocRemove(b.getAttribute('data-doc-remove'), b.getAttribute('data-doc-type'),
                  b.getAttribute('data-doc-linked'));
    });
  }
  // mostra bottone Picker solo se abilitato + carica gapi CDN
  try {
    const cfg = await (await fetch('/documents/api/picker-config')).json();
    const btn = document.getElementById('doc-pick-' + linkedType);
    if (btn && cfg.enabled) {
      btn.style.display = '';
      if (!window.gapi) {
        const sc = document.createElement('script');
        sc.src = 'https://apis.google.com/js/api.js'; document.head.appendChild(sc);
      }
    }
  } catch (e) { /* picker best-effort */ }
  mfDocList(linkedType, linkedId);
}
