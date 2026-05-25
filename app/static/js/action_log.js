/* Claqo — action_log.js (Bundle E v3.5.0-alpha.172.76)
   Permanent ring-buffer log per toast/api/error events.
   Open panel: Ctrl+Shift+L. Verbose mode: localStorage.mf_verbose=1.
   Storage: localStorage.mf_action_log (JSON array, max MF_LOG_MAX entries).
   No innerHTML — all DOM built via createElement (XSS-safe).
*/
(function () {
  'use strict';
  const STORE_KEY = 'mf_action_log';
  const VERBOSE_KEY = 'mf_verbose';
  const MF_LOG_MAX = 500;

  function _now() { return new Date().toISOString(); }
  function isVerbose() { return localStorage.getItem(VERBOSE_KEY) === '1'; }

  function _load() {
    try { return JSON.parse(localStorage.getItem(STORE_KEY) || '[]'); }
    catch (e) { return []; }
  }
  function _save(arr) {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(arr.slice(-MF_LOG_MAX))); }
    catch (e) {
      try { localStorage.setItem(STORE_KEY, JSON.stringify(arr.slice(-Math.floor(MF_LOG_MAX / 2)))); }
      catch (_) { /* quota full, give up */ }
    }
  }

  function mfLog(type, cat, msg, detail) {
    const entry = {
      ts: _now(),
      type: String(type || 'info'),
      cat: String(cat || 'info'),
      msg: msg == null ? '' : String(msg).slice(0, 2000),
      detail: detail == null ? null : (typeof detail === 'string'
        ? detail.slice(0, 4000)
        : (function () { try { return JSON.stringify(detail).slice(0, 4000); } catch (e) { return '[unserializable]'; } })()
      ),
      url: location.pathname + location.search,
    };
    const arr = _load(); arr.push(entry); _save(arr);
    if (window._mfLogPanel && window._mfLogPanel.classList.contains('mf-log-open')) {
      _renderRow(entry);
    }
    return entry;
  }
  window.mfLog = mfLog;
  window.mfLogVerboseIsOn = isVerbose;
  window.mfLogSetVerbose = function (on) {
    localStorage.setItem(VERBOSE_KEY, on ? '1' : '0');
  };
  window.mfLogClear = function () { _save([]); _refreshPanel(); };
  window.mfLogExport = function () {
    const data = JSON.stringify(_load(), null, 2);
    const blob = new Blob([data], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'claqo-action-log-' + _now().replace(/[:.]/g, '-') + '.json';
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  function _makeBtn(label, title) {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = label;
    if (title) b.title = title;
    b.style.cssText = 'font-size:11px;padding:3px 8px;cursor:pointer;background:transparent;color:inherit;border:1px solid rgba(255,255,255,0.2);border-radius:4px;';
    return b;
  }

  function _buildPanel() {
    if (window._mfLogPanel) return window._mfLogPanel;
    const panel = document.createElement('div');
    panel.id = 'mf-action-log-panel';
    panel.className = 'mf-log-panel';
    panel.style.cssText = (
      'position:fixed; right:16px; bottom:16px; width:min(640px, calc(100vw - 32px)); '
      + 'height:min(420px, 60vh); background:var(--bg2, #1f2436); color:var(--text1, #e8ecf5); '
      + 'border:1px solid rgba(255,255,255,0.1); border-radius:12px; '
      + 'box-shadow:0 12px 40px rgba(0,0,0,0.45); z-index:99998; '
      + 'display:none; flex-direction:column; font-family:system-ui, sans-serif;'
    );

    // Header
    const header = document.createElement('div');
    header.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:10px 14px;border-bottom:1px solid rgba(255,255,255,0.08);';
    const title = document.createElement('div');
    title.style.cssText = 'font-weight:600;font-size:13px;';
    title.appendChild(document.createTextNode('📋 Log azioni '));
    const hint = document.createElement('span');
    hint.style.cssText = 'font-weight:400;color:var(--text3,#888);font-size:11px;';
    hint.textContent = '(Ctrl+Shift+L)';
    title.appendChild(hint);
    header.appendChild(title);

    const actions = document.createElement('div');
    actions.style.cssText = 'display:flex;gap:6px;align-items:center;';
    const vbLabel = document.createElement('label');
    vbLabel.style.cssText = 'display:flex;align-items:center;gap:4px;font-size:11px;cursor:pointer;';
    const vb = document.createElement('input');
    vb.type = 'checkbox'; vb.id = 'mf-log-verbose';
    vbLabel.appendChild(vb);
    vbLabel.appendChild(document.createTextNode(' verbose'));
    actions.appendChild(vbLabel);
    const btnCopy = _makeBtn('Copia tutto'); actions.appendChild(btnCopy);
    const btnExport = _makeBtn('Esporta JSON'); actions.appendChild(btnExport);
    const btnClear = _makeBtn('Svuota'); actions.appendChild(btnClear);
    const btnClose = _makeBtn('✕'); btnClose.style.border = '0'; btnClose.style.fontSize = '13px';
    actions.appendChild(btnClose);
    header.appendChild(actions);
    panel.appendChild(header);

    // Body
    const body = document.createElement('div');
    body.id = 'mf-log-body';
    body.style.cssText = 'flex:1;overflow-y:auto;padding:6px 0;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;line-height:1.4;';
    panel.appendChild(body);

    // Footer
    const footer = document.createElement('div');
    footer.style.cssText = 'padding:6px 14px;border-top:1px solid rgba(255,255,255,0.08);font-size:10px;color:var(--text3,#888);';
    footer.textContent = 'Ring buffer ' + MF_LOG_MAX + ' eventi · click su riga per espandere detail';
    panel.appendChild(footer);

    document.body.appendChild(panel);
    window._mfLogPanel = panel;

    btnClose.onclick = () => togglePanel(false);
    btnClear.onclick = () => { if (confirm('Svuotare il log azioni?')) window.mfLogClear(); };
    btnExport.onclick = window.mfLogExport;
    btnCopy.onclick = () => {
      const txt = _load().map(_entryToText).join('\n');
      _copyToClipboard(txt, btnCopy);
    };
    vb.checked = isVerbose();
    vb.onchange = () => window.mfLogSetVerbose(vb.checked);
    return panel;
  }

  function _entryToText(e) {
    const detail = e.detail ? ' · ' + e.detail : '';
    return '[' + e.ts + '] ' + e.type.toUpperCase() + '/' + e.cat + ' @ ' + (e.url || '?')
      + ' :: ' + e.msg + detail;
  }

  function _copyToClipboard(txt, btn) {
    const done = (ok) => {
      if (!btn) return;
      const orig = btn.textContent;
      btn.textContent = ok ? '✓' : '✗';
      setTimeout(() => { btn.textContent = orig; }, 1200);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(txt).then(() => done(true)).catch(() => done(false));
    } else {
      try {
        const ta = document.createElement('textarea');
        ta.value = txt; ta.style.position = 'fixed'; ta.style.left = '-9999px';
        document.body.appendChild(ta); ta.select();
        document.execCommand('copy'); ta.remove(); done(true);
      } catch (e) { done(false); }
    }
  }

  const CAT_COLOR = {
    info: '#94a3b8', success: '#34d399', warning: '#fbbf24',
    error: '#f87171', debug: '#a78bfa',
  };

  function _renderRow(entry) {
    const body = window._mfLogPanel && window._mfLogPanel.querySelector('#mf-log-body');
    if (!body) return;
    const row = document.createElement('div');
    row.style.cssText = 'padding:4px 14px;border-bottom:1px dashed rgba(255,255,255,0.04);cursor:pointer;';

    const head = document.createElement('div');
    const ts = entry.ts.slice(11, 19);
    const color = CAT_COLOR[entry.cat] || '#94a3b8';

    const tsSpan = document.createElement('span');
    tsSpan.style.color = '#64748b'; tsSpan.textContent = ts + ' ';
    head.appendChild(tsSpan);
    const catSpan = document.createElement('span');
    catSpan.style.cssText = 'color:' + color + ';font-weight:600;';
    catSpan.textContent = entry.cat.toUpperCase(); head.appendChild(catSpan);
    head.appendChild(document.createTextNode(' '));
    const typeSpan = document.createElement('span');
    typeSpan.style.color = '#94a3b8';
    typeSpan.textContent = '[' + entry.type + ']'; head.appendChild(typeSpan);
    head.appendChild(document.createTextNode(' '));
    const msgSpan = document.createElement('span');
    msgSpan.textContent = entry.msg; head.appendChild(msgSpan);

    const copyBtn = document.createElement('button');
    copyBtn.type = 'button'; copyBtn.textContent = '📋'; copyBtn.title = 'Copia entry';
    copyBtn.style.cssText = 'float:right;margin-left:6px;background:transparent;border:0;color:inherit;cursor:pointer;font-size:11px;';
    copyBtn.onclick = (ev) => {
      ev.stopPropagation();
      _copyToClipboard(_entryToText(entry), copyBtn);
    };
    head.appendChild(copyBtn);
    row.appendChild(head);

    if (entry.detail) {
      const det = document.createElement('div');
      det.style.cssText = 'display:none;margin-top:4px;padding:6px 8px;background:rgba(0,0,0,0.25);border-radius:4px;white-space:pre-wrap;word-break:break-all;color:#cbd5e1;';
      det.textContent = entry.detail;
      row.appendChild(det);
      row.onclick = () => { det.style.display = det.style.display === 'none' ? 'block' : 'none'; };
    }
    body.appendChild(row);
    body.scrollTop = body.scrollHeight;
  }

  function _refreshPanel() {
    const body = window._mfLogPanel && window._mfLogPanel.querySelector('#mf-log-body');
    if (!body) return;
    while (body.firstChild) body.removeChild(body.firstChild);
    _load().forEach(_renderRow);
  }

  function togglePanel(forceOpen) {
    const panel = _buildPanel();
    const open = forceOpen != null ? forceOpen : (panel.style.display === 'none');
    panel.style.display = open ? 'flex' : 'none';
    if (open) {
      panel.classList.add('mf-log-open');
      _refreshPanel();
    } else {
      panel.classList.remove('mf-log-open');
    }
  }
  window.mfLogTogglePanel = togglePanel;

  document.addEventListener('keydown', (e) => {
    if (e.ctrlKey && e.shiftKey && (e.key === 'L' || e.key === 'l')) {
      e.preventDefault();
      togglePanel();
    }
  });
})();
