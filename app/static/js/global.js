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
// Riordino flat cross-section: quando l'utente personalizza l'ordine,
// le sezioni originali (Anagrafica, Operativo…) vengono nascoste e tutte
// le voci appaiono in un'unica lista nell'ordine scelto.
function applySidebarOrder() {
  const sidebar = document.querySelector('.sidebar-nav');
  if (!sidebar) return;
  const order = JSON.parse(localStorage.getItem('mf_sidebar_order') || 'null');
  if (!order || !Array.isArray(order) || !order.length) {
    // Nessun ordine custom: lascia struttura server (sezioni come da base.html)
    return;
  }
  // Raccogli tutti i nav-item esistenti
  const allItems = {};
  sidebar.querySelectorAll('.nav-item[data-nav-id]').forEach(el => {
    allItems[el.dataset.navId] = el;
  });
  // Costruisci nuovo container flat
  const flat = document.createElement('div');
  flat.className = 'nav-section nav-section-custom';
  for (const id of order) {
    const el = allItems[id];
    if (el) flat.appendChild(el);
  }
  // Aggiungi eventuali item nuovi non presenti nell'ordine salvato (in fondo)
  for (const [id, el] of Object.entries(allItems)) {
    if (!order.includes(id)) flat.appendChild(el);
  }
  // Rimpiazza tutto il contenuto nav con il flat
  sidebar.innerHTML = '';
  sidebar.appendChild(flat);
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
async function api(method, url, formData) {
  const opts = { method };
  if (formData instanceof FormData) {
    opts.body = formData;
  } else if (formData) {
    opts.headers = { 'Content-Type': 'application/x-www-form-urlencoded' };
    opts.body = new URLSearchParams(formData).toString();
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
