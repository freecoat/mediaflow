// mobile.js — helper condivisi area /m. v3.5.0-alpha.172.158
async function mapi(method, url, formData) {
  const opt = { method, headers: {}, credentials: 'same-origin' };
  if (formData) opt.body = formData;
  const r = await fetch(url, opt);
  if (r.status === 401 || r.status === 403) { location.href = '/auth/login?next=' + encodeURIComponent(location.pathname); throw new Error('auth'); }
  const ct = r.headers.get('content-type') || '';
  const data = ct.includes('application/json') ? await r.json() : await r.text();
  if (!r.ok) throw new Error((data && data.detail) ? data.detail : ('HTTP ' + r.status));
  return data;
}
function mEl(tag, cls, html) { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }
function mEsc(s) { const d = document.createElement('div'); d.textContent = (s == null ? '' : String(s)); return d.innerHTML; }
function mToast(msg) {
  const t = mEl('div', 'm-toast', mEsc(msg)); document.body.appendChild(t);
  setTimeout(() => t.classList.add('show'), 10); setTimeout(() => { t.classList.remove('show'); setTimeout(()=>t.remove(), 300); }, 2600);
}
function mFmtDate(iso) { if(!iso) return ''; const d = new Date(iso); return d.toLocaleDateString('it-IT', {day:'2-digit', month:'2-digit'}); }
function mFmtTime(iso) { if(!iso) return ''; const d = new Date(iso); return d.toLocaleTimeString('it-IT', {hour:'2-digit', minute:'2-digit'}); }

function mDrawerOpen() {
  document.getElementById('m-drawer')?.classList.add('open');
  document.getElementById('m-drawer-overlay')?.classList.add('open');
  document.body.classList.add('m-no-scroll');
}
function mDrawerClose() {
  document.getElementById('m-drawer')?.classList.remove('open');
  document.getElementById('m-drawer-overlay')?.classList.remove('open');
  document.body.classList.remove('m-no-scroll');
}
function mDrawerToggle() {
  document.getElementById('m-drawer')?.classList.contains('open') ? mDrawerClose() : mDrawerOpen();
}

// ── v3.5.0-alpha.172.167 — helper compatti per le schermate "business" ──
function mClear(el) { if (el) while (el.firstChild) el.removeChild(el.firstChild); }
function mIcon(name) { const i = document.createElement('i'); i.setAttribute('data-lucide', name); return i; }
function mLucide() { try { window.lucide && window.lucide.createIcons(); } catch (e) {} }
function mMoney(n, cur) {
  if (n == null || isNaN(n)) return '—';
  const s = Number(n).toLocaleString('it-IT', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
  return (cur === 'USD' ? '$' : cur === 'GBP' ? '£' : cur === 'CHF' ? 'CHF ' : '€ ') + s;
}
// Riga-lista cliccabile: titolo + sottotitolo + badge opzionale. Tutto via textContent (no XSS).
function mListRow(href, title, subtitle, badgeText, badgeCls) {
  const a = document.createElement('a'); a.className = 'm-list-row'; a.href = href;
  const main = mEl('div', 'm-list-main');
  const t = mEl('div', 'm-list-title'); t.textContent = title || '—'; main.appendChild(t);
  if (subtitle) { const s = mEl('div', 'm-list-sub'); s.textContent = subtitle; main.appendChild(s); }
  a.appendChild(main);
  if (badgeText) { const b = mEl('span', 'm-badge ' + (badgeCls || '')); b.textContent = badgeText; a.appendChild(b); }
  const chev = mIcon('chevron-right'); chev.className = 'm-list-chev'; a.appendChild(chev);
  return a;
}
// Riga label/valore per le schede dettaglio. value può essere stringa o nodo.
function mField(label, value) {
  const row = mEl('div', 'm-field');
  const l = mEl('div', 'm-field-label'); l.textContent = label; row.appendChild(l);
  const v = mEl('div', 'm-field-val');
  if (value instanceof Node) v.appendChild(value); else v.textContent = (value == null || value === '') ? '—' : String(value);
  row.appendChild(v); return row;
}
function mCard(titleText, iconName) {
  const c = mEl('div', 'm-card');
  if (titleText) {
    const h = mEl('div', 'm-card-title');
    if (iconName) h.appendChild(mIcon(iconName));
    h.appendChild(document.createTextNode((iconName ? ' ' : '') + titleText));
    c.appendChild(h);
  }
  return c;
}
function mEmpty(msg) { const e = mEl('div', 'm-empty'); e.textContent = msg || 'Nessun dato.'; return e; }
function mError(root, msg) { mClear(root); root.appendChild(mEmpty(msg || 'Errore di caricamento.')); }
// Badge per stato (mappa colori coerente desktop). Ritorna {text, cls}.
function mStatusBadge(status) {
  const s = (status || '').toLowerCase();
  const map = {
    approved: 'm-badge-in', approvata: 'm-badge-in', in_progress: 'm-badge-accent',
    in_lavorazione: 'm-badge-accent', completed: 'm-badge-in', completato: 'm-badge-in',
    draft: 'm-badge-out', bozza: 'm-badge-out', rejected: 'm-badge-err', rifiutata: 'm-badge-err',
    cancelled: 'm-badge-err', planning: 'm-badge-out', delivered: 'm-badge-in',
  };
  return { text: status || '—', cls: map[s] || 'm-badge-out' };
}
