// app/static/js/settings_account.js — Fase A account linking UI
// Consuma GET /auth/oauth/status, avvia /auth/oauth/{pid}/start,
// chiama POST /auth/oauth/{pid}/disconnect e /auth/oauth/{pid}/sync-toggle.
// Dipende da escapeHtml (global.js) e window.applyI18n / window.mfT (i18n.js).

async function loadAccountSettings() {
  const box = document.getElementById('account-cards');
  if (!box) return;
  let data;
  try {
    const r = await fetch('/auth/oauth/status');
    if (!r.ok) throw new Error('status ' + r.status);
    data = await r.json();
  } catch (e) {
    box.innerHTML = '<p class="text-sm" style="color:#ef4444;">' + escapeHtml(String(e)) + '</p>';
    return;
  }
  box.innerHTML = '';
  const providers = data.providers || {};
  for (const [pid, p] of Object.entries(providers)) {
    const card = document.createElement('div');
    card.className = 'card mb-3';
    card.style.cssText = 'border:1px solid var(--border); padding:14px; border-radius:var(--radius);';
    const connected = p.connected;
    const microsoftDisabled = (pid === 'microsoft') && !connected;
    let actions;
    if (microsoftDisabled) {
      actions = '<span class="badge" data-i18n="settings.account.comingSoon">Prossimamente</span>';
    } else if (connected) {
      actions =
        '<label style="display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer;margin-bottom:8px;">' +
        '<input type="checkbox" ' + (p.auto_sync_calendar ? 'checked' : '') +
        ' onchange="toggleAccountSync(\'' + escapeHtml(pid) + '\', this.checked)"> ' +
        '<span data-i18n="settings.account.autoSync">Sync calendario automatico</span></label>' +
        '<button class="btn btn-danger btn-sm" onclick="disconnectAccount(\'' + escapeHtml(pid) + '\')" ' +
        'data-i18n="settings.account.disconnect">Scollega</button>';
      // Opt-in email (Gmail): richiede scope gmail.readonly+compose in aggiunta.
      if (pid === 'google') {
        const hasMail = (p.scopes || '').indexOf('gmail.readonly') !== -1;
        actions += hasMail
          ? ' <span class="badge badge-active" style="font-size:11px;">Email ✓</span>'
          : ' <a class="btn btn-secondary btn-sm" href="/auth/oauth/google/start?scopes=email" ' +
            'data-i18n="mail.connect">Collega Gmail</a>';
        // Opt-in editing calendario: calendar.events in aggiunta. Riconosce anche
        // lo scope 'calendar' pieno (superset) che Google concede su alcuni account.
        const sc = p.scopes || '';
        const hasCalWrite = sc.indexOf('calendar.events') !== -1 ||
                            sc.split(/\s+/).some(s => s.endsWith('/auth/calendar'));
        actions += hasCalWrite
          ? ' <span class="badge badge-active" style="font-size:11px;" ' +
            'data-i18n="settings.account.calendarWriteActive">Editing calendario ✓</span>'
          : ' <a class="btn btn-secondary btn-sm" href="/auth/oauth/google/start?scopes=calendar_write" ' +
            'data-i18n="settings.account.calendarWrite">Attiva editing calendario</a>';
      }
    } else {
      const notCfgTitle = window.mfT ? mfT('settings.account.notConfigured') : 'client_id non configurato';
      const disabled = p.configured ? '' : 'disabled title="' + escapeHtml(notCfgTitle) + '"';
      actions = '<a class="btn btn-secondary btn-sm" ' + disabled +
        ' href="/auth/oauth/' + escapeHtml(pid) + '/start" ' +
        'data-i18n="settings.account.connect">Collega</a>';
    }
    const emailLine = connected
      ? '<p class="text-sm text-muted" style="margin:4px 0 10px;">' + escapeHtml(p.account_email || '') + '</p>'
      : '<p class="text-sm text-muted" style="margin:4px 0 10px;" data-i18n="settings.account.notLinked">Non collegato</p>';
    card.innerHTML =
      '<div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">' +
      '<strong style="font-size:14px;">' + escapeHtml(p.label || pid) + '</strong>' +
      (connected ? '<span class="badge badge-active" style="font-size:11px;" data-i18n="settings.account.connected">Connesso</span>' : '') +
      '</div>' +
      emailLine +
      '<div>' + actions + '</div>';
    box.appendChild(card);
  }
  if (Object.keys(providers).length === 0) {
    box.innerHTML = '<p class="text-sm text-muted" data-i18n="settings.account.noProviders">Nessun provider OAuth configurato.</p>';
  }
  if (window.applyI18n) window.applyI18n(box);
}

async function disconnectAccount(pid) {
  const msg = window.mfT ? mfT('settings.account.confirmDisconnect') : 'Scollegare questo account?';
  if (!confirm(msg)) return;
  try {
    const r = await fetch('/auth/oauth/' + pid + '/disconnect', {method: 'POST'});
    if (!r.ok) throw new Error('status ' + r.status);
    if (window.toast) toast(mfT ? mfT('settings.account.disconnected') : 'Account scollegato', 'success');
  } catch (e) {
    if (window.toast) toast('Errore: ' + String(e), 'error');
  }
  loadAccountSettings();
}

async function toggleAccountSync(pid, enabled) {
  try {
    const fd = new FormData();
    fd.append('enabled', enabled ? 'true' : 'false');
    const r = await fetch('/auth/oauth/' + pid + '/sync-toggle', {method: 'POST', body: fd});
    if (!r.ok) throw new Error('status ' + r.status);
    if (window.toast) toast(window.mfT ? mfT('settings.account.syncUpdated') : 'Preferenza sync aggiornata', 'success');
  } catch (e) {
    if (window.toast) toast('Errore: ' + String(e), 'error');
    loadAccountSettings(); // ripristina stato
  }
}
