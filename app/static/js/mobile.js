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
