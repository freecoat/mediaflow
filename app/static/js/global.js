/* MediaFlow — global.js
   Toast, modal helpers, API fetch wrapper, tema, riordino sidebar
*/

// ── Tema (preset CSS variables) ────────────────────────────────
const MF_THEMES = ['indigo', 'slate', 'forest', 'sand'];
function applyTheme() {
  const theme = localStorage.getItem('mf_theme') || 'indigo';
  document.documentElement.classList.remove(...MF_THEMES.map(t => 'theme-' + t));
  document.documentElement.classList.add('theme-' + (MF_THEMES.includes(theme) ? theme : 'indigo'));
}
function setTheme(theme) {
  if (!MF_THEMES.includes(theme)) return;
  localStorage.setItem('mf_theme', theme);
  applyTheme();
}

// ── Riordino sidebar (drag-drop, salvato in localStorage) ──────
// v3.4.28: riordino DENTRO ciascuna sezione (preserva i raggruppamenti
// "Anagrafica", "Operativo", … di base.html). Formato saved: object
// {sectionName: [navId, navId, …]}. Il vecchio formato array piatto viene
// ignorato silenziosamente (l'utente vede l'ordine default e può ripersonalizzare).
function applySidebarOrder() {
  const sidebar = document.querySelector('.sidebar-nav');
  if (!sidebar) return;
  let saved;
  try { saved = JSON.parse(localStorage.getItem('mf_sidebar_order') || 'null'); }
  catch (e) { saved = null; }
  if (!saved || Array.isArray(saved) || typeof saved !== 'object') return;

  const sections = [...sidebar.querySelectorAll('.nav-section')];
  for (const sec of sections) {
    const labelEl = sec.querySelector('.nav-section-label');
    if (!labelEl) continue;
    const sectionName = labelEl.textContent.trim();
    const order = saved[sectionName];
    if (!order || !Array.isArray(order) || !order.length) continue;

    const items = [...sec.querySelectorAll('.nav-item[data-nav-id]')];
    if (!items.length) continue;
    const itemMap = {};
    items.forEach(it => itemMap[it.dataset.navId] = it);

    items.forEach(it => it.remove());
    for (const id of order) {
      if (itemMap[id]) { sec.appendChild(itemMap[id]); delete itemMap[id]; }
    }
    for (const it of items) {
      if (itemMap[it.dataset.navId]) sec.appendChild(it);
    }
  }
}

// Applica subito (prima del rendering completo) per evitare flash di stile
applyTheme();
document.addEventListener('DOMContentLoaded', applySidebarOrder);


// ── Toast ─────────────────────────────────────────────────────
function toast(msg, type = 'info', duration = 3500) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => {
    el.style.opacity = '0';
    el.style.transition = 'opacity 300ms';
    setTimeout(() => el.remove(), 300);
  }, duration);
}

// ── Modal ─────────────────────────────────────────────────────
function openModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add('open');
}
function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove('open');
}
// Chiudi cliccando fuori
document.addEventListener('click', (e) => {
  if (e.target.classList.contains('modal-overlay')) {
    e.target.classList.remove('open');
  }
});

// ── API helper ────────────────────────────────────────────────
async function api(method, url, body, options) {
  // body: FormData (multipart) | plain object (urlencoded by default,
  //       or JSON if options.json === true) | undefined.
  const opts = { method };
  const useJson = options && options.json === true;
  if (body instanceof FormData) {
    opts.body = body;
  } else if (useJson && body && typeof body === 'object') {
    opts.headers = { 'Content-Type': 'application/json' };
    opts.body = JSON.stringify(body);
  } else if (body) {
    opts.headers = { 'Content-Type': 'application/x-www-form-urlencoded' };
    opts.body = new URLSearchParams(body).toString();
  }
  const resp = await fetch(url, opts);
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(err.detail || 'Errore sconosciuto');
  }
  return resp.json();
}

// ── HTML escape ───────────────────────────────────────────────
function escapeHtml(s) {
  if (s == null) return '';
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// ── Format helpers ────────────────────────────────────────────
function fmtCurrency(n) {
  return new Intl.NumberFormat('it-IT', { style: 'currency', currency: 'EUR' }).format(n || 0);
}
function fmtDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('it-IT');
}
function fmtSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

// ── Status badge ──────────────────────────────────────────────
const STATUS_CLASS = {
  draft: 'badge-draft', active: 'badge-active', on_hold: 'badge-hold',
  completed: 'badge-done', invoiced: 'badge-invoiced', cancelled: 'badge-cancelled',
  tentative: 'badge-draft', confirmed: 'badge-active', paid: 'badge-paid',
  sent: 'badge-done', overdue: 'badge-cancelled',
};
const STATUS_LABEL = {
  draft: 'Bozza', active: 'Attivo', on_hold: 'In pausa',
  completed: 'Completato', invoiced: 'Fatturato', cancelled: 'Annullato',
  tentative: 'Provvisorio', confirmed: 'Confermato', paid: 'Pagato',
  sent: 'Inviato', overdue: 'Scaduto',
};
function statusBadge(status) {
  const cls = STATUS_CLASS[status] || 'badge-draft';
  const lbl = STATUS_LABEL[status] || status;
  return `<span class="badge ${cls}">${lbl}</span>`;
}

// ── Asset type icon ───────────────────────────────────────────
const ASSET_ICONS = {
  video: '🎬', audio: '🎵', image: '🖼️', document: '📄', other: '📦',
};
function assetIcon(type) { return ASSET_ICONS[type] || '📦'; }
