/* MediaFlow — global.js
   Toast, modal helpers, API fetch wrapper, tema, riordino sidebar
*/

// ── Tema (preset CSS variables) ────────────────────────────────
const MF_THEMES = ['indigo', 'slate', 'forest', 'sand', 'paper', 'linen', 'sage', 'midnight', 'copper', 'plum', 'teal', 'mono', 'broadcast'];
const MF_FONTS = ['dmsans', 'inter', 'roboto', 'ibmplex', 'source', 'system'];

function applyTheme() {
  const theme = localStorage.getItem('mf_theme') || 'indigo';
  document.documentElement.classList.remove(...MF_THEMES.map(t => 'theme-' + t));
  document.documentElement.classList.add('theme-' + (MF_THEMES.includes(theme) ? theme : 'indigo'));
}
function setTheme(theme) {
  if (!MF_THEMES.includes(theme)) return;
  localStorage.setItem('mf_theme', theme);
  applyTheme();
  // v3.5.0-alpha.66.19: aggiorna popover topbar se montato
  if (typeof window._topbarThemeRender === 'function') window._topbarThemeRender();
}

// v3.5.0-alpha.66.19: topbar theme switcher — cycle + popover
const MF_THEME_META = {
  indigo:    { name:'Indigo',    sw:['#0f1117','#1f2436','#6272f5','#e8ecf5'] },
  slate:     { name:'Slate',     sw:['#11141a','#232730','#5b8def','#e6e9ef'] },
  forest:    { name:'Forest',    sw:['#0c1410','#1a261f','#4ade80','#e7f0e9'] },
  sand:      { name:'Sand',      sw:['#f5f1e8','#e1dac5','#a0522d','#2b2620'] },
  paper:     { name:'Paper',     sw:['#fafafa','#e7e7ea','#475569','#1d1d1f'] },
  linen:     { name:'Linen',     sw:['#faf6f1','#e7ddd0','#c2410c','#2a221b'] },
  sage:      { name:'Sage',      sw:['#f0f3ee','#d9e0d2','#15803d','#1c2a1c'] },
  midnight:  { name:'Midnight',  sw:['#0a0d1a','#161c39','#818cf8','#e4e9f5'] },
  copper:    { name:'Copper',    sw:['#1a1310','#2d201d','#ea8a5b','#f0e4dc'] },
  plum:      { name:'Plum',      sw:['#14101a','#271f33','#c084fc','#ede5f5'] },
  teal:      { name:'Teal',      sw:['#0a1418','#182b32','#2dd4bf','#e1f0f0'] },
  mono:      { name:'Mono',      sw:['#0d0d0d','#1f1f1f','#d4d4d4','#f0f0f0'] },
  broadcast: { name:'Broadcast', sw:['#1c1c1f','#2a2a30','#00d4ff','#e8eaed'] },
};
function topbarThemeCycle() {
  const current = localStorage.getItem('mf_theme') || 'indigo';
  const idx = MF_THEMES.indexOf(current);
  const next = MF_THEMES[(idx + 1) % MF_THEMES.length];
  setTheme(next);
  if (typeof toast === 'function') toast('Tema: ' + (MF_THEME_META[next]?.name || next), 'success');
}
function _topbarThemeRender() {
  const pop = document.getElementById('topbar-theme-pop');
  if (!pop) return;
  const current = localStorage.getItem('mf_theme') || 'indigo';
  while (pop.firstChild) pop.removeChild(pop.firstChild);
  for (const id of MF_THEMES) {
    const meta = MF_THEME_META[id]; if (!meta) continue;
    const cell = document.createElement('button');
    cell.type = 'button';
    cell.className = 'tt-cell' + (id === current ? ' active' : '');
    cell.title = meta.name;
    cell.setAttribute('data-theme-id', id);
    cell.addEventListener('click', () => setTheme(id));
    const swwrap = document.createElement('div');
    swwrap.className = 'tt-sw';
    for (const c of meta.sw) {
      const s = document.createElement('div');
      s.style.background = c;
      swwrap.appendChild(s);
    }
    const lbl = document.createElement('div');
    lbl.className = 'tt-lbl';
    lbl.textContent = meta.name;
    cell.appendChild(swwrap);
    cell.appendChild(lbl);
    pop.appendChild(cell);
  }
}
window._topbarThemeRender = _topbarThemeRender;
document.addEventListener('DOMContentLoaded', () => {
  _topbarThemeRender();
  // Click outside chiude (gestito da CSS via :focus-within, ma fallback JS)
});

// v3.4.32.1: variante font opzionale (default = dmsans)
function applyFont() {
  const f = localStorage.getItem('mf_font') || 'dmsans';
  document.documentElement.classList.remove(...MF_FONTS.map(x => 'font-' + x));
  document.documentElement.classList.add('font-' + (MF_FONTS.includes(f) ? f : 'dmsans'));
}
function setFont(font) {
  if (!MF_FONTS.includes(font)) return;
  localStorage.setItem('mf_font', font);
  applyFont();
}

// ── Riordino sidebar (drag-drop, salvato in localStorage) ──────
// Due livelli indipendenti, persistiti in chiavi distinte:
//
// - `mf_sidebar_section_order` (v3.5.0-alpha.5): lista ordinata di nomi
//   sezione (es. ["Operativo","Anagrafica","Amministrazione",…]). Riordina
//   i `.nav-section` dentro `.sidebar-nav`. Sezioni nuove non in lista
//   restano in coda nell'ordine sorgente di base.html.
//
// - `mf_sidebar_order` (v3.4.28): mappa {sectionName: [navId, navId, …]}.
//   Riordina le voci DENTRO ciascuna sezione. Il vecchio formato array
//   piatto viene ignorato (utente vede default e può ripersonalizzare).
function applySidebarOrder() {
  const sidebar = document.querySelector('.sidebar-nav');
  if (!sidebar) return;

  // 1) Riordino sezioni
  let secOrder;
  try { secOrder = JSON.parse(localStorage.getItem('mf_sidebar_section_order') || 'null'); }
  catch (e) { secOrder = null; }
  if (Array.isArray(secOrder) && secOrder.length) {
    const sections = [...sidebar.querySelectorAll('.nav-section')];
    const byName = {};
    for (const sec of sections) {
      const labelEl = sec.querySelector('.nav-section-label');
      if (!labelEl) continue;
      byName[labelEl.textContent.trim()] = sec;
    }
    sections.forEach(sec => sec.remove());
    for (const name of secOrder) {
      if (byName[name]) { sidebar.appendChild(byName[name]); delete byName[name]; }
    }
    // Sezioni rimaste (non presenti nel saved order) tornano in coda nell'ordine originale.
    for (const sec of sections) {
      const labelEl = sec.querySelector('.nav-section-label');
      const name = labelEl ? labelEl.textContent.trim() : null;
      if (name && byName[name]) sidebar.appendChild(byName[name]);
    }
  }

  // 2) Riordino voci dentro ciascuna sezione
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
applyFont();
document.addEventListener('DOMContentLoaded', applySidebarOrder);


// ── Suoni soft (v3.5.0-alpha.29) ──────────────────────────────
// WebAudio-synthesized: niente file MP3, niente CORS, latenza zero.
// Stile macOS (ping discreto). Throttle 1s per evitare spam.
// Toggle salvati in localStorage:
//   mf_sound_notify (default: '1')   — suoni su toast success/error/warning
//   mf_sound_ai     (default: '0')   — suono al completamento AI copilot
const _SOUND_THROTTLE_MS = 800;
let _lastSoundAt = 0;
let _soundCtx = null;

function _soundCtxLazy() {
  if (_soundCtx) return _soundCtx;
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    _soundCtx = new AC();
    return _soundCtx;
  } catch (e) { return null; }
}

function isSoundEnabled(kind) {
  // Default: notify=on, ai=off (meno invasivo)
  const key = kind === 'ai' ? 'mf_sound_ai' : 'mf_sound_notify';
  const def = kind === 'ai' ? '0' : '1';
  return (localStorage.getItem(key) || def) === '1';
}

function setSoundEnabled(kind, on) {
  const key = kind === 'ai' ? 'mf_sound_ai' : 'mf_sound_notify';
  localStorage.setItem(key, on ? '1' : '0');
}

function playSound(name) {
  // name: 'notify' | 'ai_done'
  const kind = name === 'ai_done' ? 'ai' : 'notify';
  if (!isSoundEnabled(kind)) return;
  const now = Date.now();
  if (now - _lastSoundAt < _SOUND_THROTTLE_MS) return;
  _lastSoundAt = now;
  const ctx = _soundCtxLazy();
  if (!ctx) return;
  // Resume se sospeso da policy autoplay browser
  if (ctx.state === 'suspended') { try { ctx.resume(); } catch (e) {} }

  const t = ctx.currentTime;
  if (name === 'notify') {
    // macOS-style "Tink": due note brevi ascendenti, sine, decay rapido
    [880, 1320].forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.value = freq;
      const start = t + i * 0.06;
      gain.gain.setValueAtTime(0, start);
      gain.gain.linearRampToValueAtTime(0.12, start + 0.005);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.18);
      osc.connect(gain).connect(ctx.destination);
      osc.start(start);
      osc.stop(start + 0.2);
    });
  } else if (name === 'ai_done') {
    // Bell soft: fondamentale + 3a armonica + decay più lungo (~600ms)
    [{f: 660, g: 0.08}, {f: 1980, g: 0.025}].forEach(({f, g}) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.value = f;
      gain.gain.setValueAtTime(0, t);
      gain.gain.linearRampToValueAtTime(g, t + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.6);
      osc.connect(gain).connect(ctx.destination);
      osc.start(t);
      osc.stop(t + 0.65);
    });
  }
}

// ── Toast ─────────────────────────────────────────────────────
function toast(msg, type = 'info', duration = 3500) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  container.appendChild(el);
  // v3.5.0-alpha.29: suono soft per toast non-info (success/error/warning).
  // Skipped per 'info' che è troppo frequente. Throttle 800ms in playSound.
  if (type && type !== 'info') {
    try { playSound('notify'); } catch (e) {}
  }
  setTimeout(() => {
    el.style.opacity = '0';
    el.style.transition = 'opacity 300ms';
    setTimeout(() => el.remove(), 300);
  }, duration);
}

// ── Modal ─────────────────────────────────────────────────────
// v3.5.0-alpha.9: openModal ora rinfresca searchable selects + timepickers
// dentro il modal dopo averlo aperto.
// v3.5.0-alpha.66.14: a11y completa - focus trap, Esc handler, aria-modal,
// restore focus al close, stack di modali aperti (chiudi solo il top sul click
// outside o su Esc), idempotente.
const MF_MODAL_STACK = [];

function _mfFocusableIn(el) {
  if (!el) return [];
  const sel = 'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';
  return Array.from(el.querySelectorAll(sel)).filter(n => n.offsetParent !== null || n === document.activeElement);
}

function _mfModalKeydown(e) {
  if (!MF_MODAL_STACK.length) return;
  const top = MF_MODAL_STACK[MF_MODAL_STACK.length - 1];
  if (e.key === 'Escape') {
    e.preventDefault();
    closeModal(top.id);
    return;
  }
  if (e.key === 'Tab') {
    const focusables = _mfFocusableIn(top.el);
    if (!focusables.length) { e.preventDefault(); return; }
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    const active = document.activeElement;
    if (e.shiftKey && (active === first || !top.el.contains(active))) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && (active === last || !top.el.contains(active))) {
      e.preventDefault();
      first.focus();
    }
  }
}

function openModal(id) {
  const el = document.getElementById(id);
  if (!el) return;
  // Evita double-push se già aperto
  if (MF_MODAL_STACK.some(m => m.id === id)) {
    el.classList.add('open');
    return;
  }
  const previousFocus = document.activeElement;
  el.classList.add('open');
  // ARIA: il container del modal è il dialog
  el.setAttribute('role', el.getAttribute('role') || 'dialog');
  el.setAttribute('aria-modal', 'true');
  if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '-1');
  MF_MODAL_STACK.push({ id, el, previousFocus });
  // Listener globale solo sulla prima apertura
  if (MF_MODAL_STACK.length === 1) {
    document.addEventListener('keydown', _mfModalKeydown, true);
  }
  // L'innerHTML del modal potrebbe essere stato appena popolato: ritarda di
  // un tick così i value impostati nel medesimo turno sincrono sono visibili.
  setTimeout(() => {
    try {
      if (typeof mfApplySearchable === 'function') mfApplySearchable(el);
      if (typeof mfApplyTimePickers === 'function') mfApplyTimePickers(el);
      if (typeof window.mfRenderIcons === 'function') window.mfRenderIcons(el);
      // Sposta focus sul primo focusable dentro il modal (o sul container)
      const focusables = _mfFocusableIn(el);
      if (focusables.length) focusables[0].focus();
      else el.focus();
    } catch (e) { /* fail-safe: non bloccare apertura */ }
  }, 0);
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove('open');
  // Pop dallo stack se presente, restore focus
  const idx = MF_MODAL_STACK.findIndex(m => m.id === id);
  if (idx !== -1) {
    const m = MF_MODAL_STACK.splice(idx, 1)[0];
    el.removeAttribute('aria-modal');
    if (m.previousFocus && typeof m.previousFocus.focus === 'function') {
      try { m.previousFocus.focus(); } catch (e) { /* dom gone */ }
    }
  }
  if (!MF_MODAL_STACK.length) {
    document.removeEventListener('keydown', _mfModalKeydown, true);
  }
}

// Click outside: chiudi SOLO il modal in cima allo stack (non tutti).
document.addEventListener('click', (e) => {
  if (!e.target.classList.contains('modal-overlay')) return;
  if (!MF_MODAL_STACK.length) {
    // Fallback legacy: modal aperto via classe ma non tracciato
    e.target.classList.remove('open');
    return;
  }
  const top = MF_MODAL_STACK[MF_MODAL_STACK.length - 1];
  if (e.target === top.el) closeModal(top.id);
});

// ── API helper ────────────────────────────────────────────────
async function api(method, url, body, options) {
  // body: FormData (multipart) | plain object (urlencoded by default,
  //       or JSON if options.json === true) | undefined.
  // v3.5.0-alpha.66.3: gestisce automaticamente SLICE_LOCK_CONFIRM_REQUIRED
  // (booking confirmed in periodo fatturato) → confirm + retry con
  // force_slice_unlock=true. Single retry, no loop. Se l'utente annulla,
  // throw l'errore originale.
  const _doRequest = async (b) => {
    const opts = { method };
    const useJson = options && options.json === true;
    if (b instanceof FormData) {
      opts.body = b;
    } else if (useJson && b && typeof b === 'object') {
      opts.headers = { 'Content-Type': 'application/json' };
      opts.body = JSON.stringify(b);
    } else if (b) {
      opts.headers = { 'Content-Type': 'application/x-www-form-urlencoded' };
      opts.body = new URLSearchParams(b).toString();
    }
    return fetch(url, opts);
  };
  const _parseError = async (resp) => {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    let humanMsg;
    if (typeof err.detail === 'string') {
      humanMsg = err.detail;
    } else if (Array.isArray(err.detail)) {
      // v3.5.0-alpha.92 — Pydantic validation 422: detail è array di
      // {type, loc, msg, input}. Concatena msg leggibili per UI.
      humanMsg = err.detail.map(d => {
        const where = Array.isArray(d.loc) ? d.loc.slice(-2).join('.') : '';
        return `[${where}] ${d.msg || d.type || 'invalid'}`;
      }).join(' · ') || `Validation error (${resp.status})`;
    } else if (err.detail && typeof err.detail === 'object') {
      humanMsg = err.detail.message || err.detail.code || JSON.stringify(err.detail);
    } else if (err.message) {
      humanMsg = String(err.message);
    } else {
      humanMsg = `HTTP ${resp.status} ${resp.statusText || ''}`.trim();
    }
    const e = new Error(humanMsg);
    e.detail = err.detail;
    e.status = resp.status;
    return e;
  };

  let resp = await _doRequest(body);
  if (!resp.ok) {
    const e = await _parseError(resp);
    // v3.5.0-alpha.66.3: intercetta SLICE_LOCK_CONFIRM_REQUIRED automaticamente.
    // Booking confirmed in periodo fatturato → chiede conferma esplicita
    // all'utente, poi re-invia con force_slice_unlock=true. Pattern globale:
    // tutti i call site beneficiano senza modifiche puntuali.
    const det = e.detail;
    const isSliceLock = e.status === 409 && det && typeof det === 'object'
      && det.code === 'SLICE_LOCK_CONFIRM_REQUIRED';
    if (isSliceLock) {
      const slc = det.slice || {};
      const inv = slc.invoice_number ? ` (fattura ${slc.invoice_number})` : '';
      const period = (slc.period_start && slc.period_end)
        ? ` ${slc.period_start} → ${slc.period_end}` : '';
      // v3.5.0-alpha.111.23 — Solo admin può sbloccare. Non-admin: messaggio
      // chiaro, nessun confirm fuorviante.
      const isAdmin = typeof window.mfIsAdmin === 'function' ? window.mfIsAdmin() : false;
      if (!isAdmin) {
        const blockE = new Error(
          '🔒 Booking bloccato — periodo fatturato' + period + inv + '.\n\n' +
          'Solo amministratore può sbloccare. Contattare admin per modifica.'
        );
        blockE.detail = det;
        blockE.status = 403;
        throw blockE;
      }
      const ok = confirm(
        '⚠ ADMIN OVERRIDE — Sblocco booking in periodo fatturato' + period + inv + '.\n\n' +
        'Il maturato ricalcolato potrebbe divergere da quello già fatturato.\n' +
        'La fattura emessa resta inalterata, ma il cost-report può cambiare.\n\n' +
        'Confermi sblocco e modifica?'
      );
      if (!ok) throw e;
      // Retry con force_slice_unlock=true. Per FormData clona; per object
      // ricostruisci; per query DELETE aggiungi al URL.
      let retryBody = body, retryUrl = url;
      if (body instanceof FormData) {
        const cloned = new FormData();
        for (const [k, v] of body.entries()) cloned.append(k, v);
        cloned.set('force_slice_unlock', 'true');
        retryBody = cloned;
      } else if (body && typeof body === 'object') {
        retryBody = { ...body, force_slice_unlock: 'true' };
      } else {
        // No body (es. DELETE): aggiungi al query string
        retryUrl = url + (url.includes('?') ? '&' : '?') + 'force_slice_unlock=true';
      }
      // Riusa la pipeline ma evita ricorsione infinita: nuovo fetch diretto.
      const retryResp = await (async () => {
        const opts = { method };
        if (retryBody instanceof FormData) {
          opts.body = retryBody;
        } else if (options && options.json && retryBody && typeof retryBody === 'object') {
          opts.headers = { 'Content-Type': 'application/json' };
          opts.body = JSON.stringify(retryBody);
        } else if (retryBody) {
          opts.headers = { 'Content-Type': 'application/x-www-form-urlencoded' };
          opts.body = new URLSearchParams(retryBody).toString();
        }
        return fetch(retryUrl, opts);
      })();
      if (!retryResp.ok) throw await _parseError(retryResp);
      return retryResp.json();
    }
    throw e;
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


// ── v3.4.40 — Searchable select (autocomplete) ────────────────
//
// Trasforma ogni <select> in un combobox cercabile. Il <select> originale
// resta nel DOM (display:none), in modo che form/api lo leggano normalmente.
// Auto-attach su DOMContentLoaded a tutti i <select> NON `multiple` e
// senza attributo `data-no-search`. Per select popolati dinamicamente,
// chiamare `mfApplySearchable(parentEl)` dopo aver settato innerHTML.

const _MF_SS_INSTANCES = new WeakMap();

function mfMakeSearchableSelect(selectEl) {
  if (_MF_SS_INSTANCES.has(selectEl)) return _MF_SS_INSTANCES.get(selectEl);
  if (selectEl.multiple) return null;
  if (selectEl.dataset.noSearch === 'true') return null;

  const wrap = document.createElement('div');
  wrap.className = 'mf-ss';
  if (selectEl.style.width) wrap.style.width = selectEl.style.width;

  const display = document.createElement('button');
  display.type = 'button';
  display.className = 'mf-ss-display form-select';
  display.setAttribute('aria-haspopup', 'listbox');
  display.setAttribute('aria-expanded', 'false');

  const dropdown = document.createElement('div');
  dropdown.className = 'mf-ss-dropdown';
  dropdown.setAttribute('role', 'listbox');

  const search = document.createElement('input');
  search.type = 'text';
  search.className = 'mf-ss-search';
  search.placeholder = 'Cerca…';
  search.setAttribute('autocomplete', 'off');

  const list = document.createElement('div');
  list.className = 'mf-ss-list';

  dropdown.appendChild(search);
  dropdown.appendChild(list);
  wrap.appendChild(display);
  wrap.appendChild(dropdown);

  selectEl.parentNode.insertBefore(wrap, selectEl);
  wrap.insertBefore(selectEl, wrap.firstChild);
  selectEl.classList.add('mf-ss-native');

  let activeIdx = -1;

  function refreshDisplay() {
    const opt = selectEl.options[selectEl.selectedIndex];
    const txt = opt ? (opt.textContent || '').trim() : '';
    if (!txt || (opt && !opt.value && opt.textContent.trim().startsWith('—'))) {
      display.classList.add('mf-ss-placeholder');
      display.textContent = txt || '— seleziona —';
    } else {
      display.classList.remove('mf-ss-placeholder');
      display.textContent = txt;
    }
  }

  function buildList(filter) {
    list.innerHTML = '';
    activeIdx = -1;
    const f = (filter || '').toLowerCase().trim();
    const opts = Array.from(selectEl.options);
    const matches = opts.map((o, i) => ({ o, i })).filter(({ o }) => {
      const t = (o.textContent || '').toLowerCase();
      return !f || t.includes(f);
    });
    if (!matches.length) {
      const empty = document.createElement('div');
      empty.className = 'mf-ss-empty';
      empty.textContent = 'Nessun risultato';
      list.appendChild(empty);
      return;
    }
    matches.forEach(({ o, i }) => {
      const item = document.createElement('div');
      item.className = 'mf-ss-item' + (i === selectEl.selectedIndex ? ' mf-ss-selected' : '');
      item.setAttribute('role', 'option');
      item.dataset.idx = i;
      item.textContent = o.textContent;
      if (o.disabled) item.classList.add('mf-ss-disabled');
      item.addEventListener('mousedown', (ev) => {
        ev.preventDefault();
        if (o.disabled) return;
        pick(i);
      });
      list.appendChild(item);
    });
  }

  function pick(idx) {
    selectEl.selectedIndex = idx;
    selectEl.dispatchEvent(new Event('change', { bubbles: true }));
    refreshDisplay();
    close();
  }

  function open() {
    buildList('');
    wrap.classList.add('open');
    display.setAttribute('aria-expanded', 'true');
    const rect = wrap.getBoundingClientRect();
    const below = window.innerHeight - rect.bottom;
    dropdown.classList.toggle('mf-ss-up', below < 220 && rect.top > 220);
    setTimeout(() => search.focus(), 0);
  }

  function close() {
    wrap.classList.remove('open');
    display.setAttribute('aria-expanded', 'false');
    search.value = '';
  }

  display.addEventListener('click', (e) => {
    e.preventDefault();
    if (selectEl.disabled) return;
    if (wrap.classList.contains('open')) close();
    else open();
  });

  search.addEventListener('input', () => buildList(search.value));
  search.addEventListener('keydown', (e) => {
    const items = list.querySelectorAll('.mf-ss-item:not(.mf-ss-disabled)');
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      activeIdx = Math.min(items.length - 1, activeIdx + 1);
      items.forEach((el, k) => el.classList.toggle('mf-ss-active', k === activeIdx));
      if (items[activeIdx]) items[activeIdx].scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      activeIdx = Math.max(0, activeIdx - 1);
      items.forEach((el, k) => el.classList.toggle('mf-ss-active', k === activeIdx));
      if (items[activeIdx]) items[activeIdx].scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (activeIdx >= 0 && items[activeIdx]) {
        pick(parseInt(items[activeIdx].dataset.idx, 10));
      } else if (items.length === 1) {
        pick(parseInt(items[0].dataset.idx, 10));
      }
    } else if (e.key === 'Escape') {
      e.preventDefault();
      close(); display.focus();
    }
  });

  document.addEventListener('mousedown', (e) => {
    if (!wrap.contains(e.target) && wrap.classList.contains('open')) close();
  });

  // Sync display quando il select viene ripopolato dinamicamente
  const observer = new MutationObserver(() => refreshDisplay());
  observer.observe(selectEl, { childList: true, attributes: true, attributeFilter: ['value'] });
  selectEl.addEventListener('change', refreshDisplay);
  // API esterna: chi setta `select.value = ...` programmaticamente
  // (senza dispatch change) può chiamare select._mfSsRefresh() per
  // riallineare il display, oppure mfApplySearchable() che lo fa per tutti.
  selectEl._mfSsRefresh = refreshDisplay;

  refreshDisplay();
  _MF_SS_INSTANCES.set(selectEl, wrap);
  return wrap;
}

function mfApplySearchable(root) {
  root = root || document;
  const sels = root.querySelectorAll('select');
  sels.forEach(sel => {
    if (sel.classList.contains('mf-ss-native')) {
      // già wrappato: rinfrescà il display per riflettere `value=` programmatico
      if (sel._mfSsRefresh) sel._mfSsRefresh();
    } else {
      mfMakeSearchableSelect(sel);
    }
  });
}


// ── v3.5.0-alpha.85 — MFAutocomplete: searchable + chips reusable ────────────
// Helper riusabile per dropdown searchable con UI esplicita (input + chip +
// box suggerimenti). Pattern già in /planning sidebar (FA_CONFIG) ma estratto
// per cashflow/forecast/fatturazione/cost-report dove il typeahead del
// <select> nativo soffre con 100+ opzioni.
//
// Single OR multi mode. Valore in <input type=hidden>. DOM-safe (no innerHTML
// con interpolazione).
//
// Usage:
//   <div class="mf-ac" id="cf-client-ac"></div>
//   <input type="hidden" id="cf-client" name="client_id">
//   MFAutocomplete({
//     host: document.getElementById('cf-client-ac'),
//     hidden: document.getElementById('cf-client'),
//     data: () => CLIENTS,
//     search: (it, q) => (it.name||'').toLowerCase().includes(q),
//     display: it => it.name,
//     placeholder: 'Tutti i clienti',
//     onChange: (ids) => loadCashflow(),
//     multi: false,
//   });

function MFAutocomplete(opts) {
  const host = opts.host;
  const hidden = opts.hidden;
  if (!host || !hidden) {
    console.warn('MFAutocomplete: host + hidden required');
    return null;
  }
  const multi = !!opts.multi;
  const placeholder = opts.placeholder || 'Cerca…';

  host.classList.add('mf-ac');
  host.replaceChildren();
  host.style.position = 'relative';
  const wrap = document.createElement('div');
  wrap.className = 'mf-ac-wrap fa-multi';
  const inp = document.createElement('input');
  inp.type = 'text';
  inp.className = 'mf-ac-input fa-input';
  inp.placeholder = placeholder;
  inp.autocomplete = 'off';
  wrap.appendChild(inp);
  const box = document.createElement('div');
  box.className = 'mf-ac-suggestions fa-suggestions';
  host.appendChild(wrap);
  host.appendChild(box);

  function getIds() {
    const v = (hidden.value || '').trim();
    if (!v) return [];
    return v.split(',').map(s => Number(s.trim())).filter(n => Number.isFinite(n) && n > 0);
  }
  function setIds(ids) {
    const cleaned = (ids || []).filter((v, i, arr) => arr.indexOf(v) === i);
    const prev = hidden.value;
    hidden.value = cleaned.join(',');
    renderChips();
    if (prev !== hidden.value && typeof opts.onChange === 'function') {
      opts.onChange(cleaned);
    }
  }

  function renderChips() {
    wrap.querySelectorAll('.mf-ac-chip, .fa-chip').forEach(c => c.remove());
    const ids = getIds();
    for (const id of ids) {
      const item = (opts.data() || []).find(x => x.id === id);
      if (!item) continue;
      const chip = document.createElement('span');
      chip.className = 'mf-ac-chip fa-chip';
      const lbl = document.createElement('span');
      lbl.textContent = opts.display ? opts.display(item) : (item.name || ('#'+id));
      const x = document.createElement('button');
      x.type = 'button';
      x.className = 'mf-ac-chip-x fa-chip-x';
      x.title = 'Rimuovi';
      x.textContent = '✕';
      x.addEventListener('click', (ev) => {
        ev.preventDefault();
        const next = getIds().filter(v => v !== id);
        setIds(next);
      });
      chip.appendChild(lbl); chip.appendChild(x);
      wrap.insertBefore(chip, inp);
    }
    inp.style.display = (multi || ids.length === 0) ? '' : 'none';
  }

  function search() {
    const q = (inp.value || '').toLowerCase().trim();
    const selected = new Set(getIds());
    let items = (opts.data() || []).filter(it => !selected.has(it.id));
    if (q) {
      const matcher = opts.search || ((it, qq) => (opts.display ? opts.display(it) : (it.name || '')).toLowerCase().includes(qq));
      items = items.filter(it => matcher(it, q));
    }
    items = items.slice(0, 20);
    box.replaceChildren();
    if (!items.length) {
      const empty = document.createElement('div');
      empty.className = 'mf-ac-item fa-item';
      empty.style.color = 'var(--text3, #888)';
      empty.style.cursor = 'default';
      empty.textContent = q ? ('Nessun risultato per "'+q+'"') : 'Nessun elemento';
      box.appendChild(empty);
      box.style.display = 'block';
      return;
    }
    for (const it of items) {
      const el = document.createElement('div');
      el.className = 'mf-ac-item fa-item';
      if (typeof opts.render === 'function') {
        const node = opts.render(it);
        if (node instanceof HTMLElement) {
          el.appendChild(node);
        } else {
          el.textContent = String(node);
        }
      } else {
        el.textContent = opts.display ? opts.display(it) : (it.name || ('#'+it.id));
      }
      el.addEventListener('mousedown', (ev) => {
        ev.preventDefault();
        if (multi) {
          const ids = getIds();
          ids.push(it.id);
          setIds(ids);
          inp.value = '';
          box.style.display = 'none';
        } else {
          setIds([it.id]);
          inp.value = '';
          box.style.display = 'none';
          inp.blur();
        }
      });
      box.appendChild(el);
    }
    box.style.display = 'block';
  }

  inp.addEventListener('input', search);
  inp.addEventListener('focus', search);
  inp.addEventListener('blur', () => setTimeout(() => { box.style.display = 'none'; }, 150));
  inp.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { box.style.display = 'none'; inp.blur(); }
    if (e.key === 'Backspace' && !inp.value) {
      const ids = getIds();
      if (ids.length) setIds(ids.slice(0, -1));
    }
  });

  const api = {
    refresh: renderChips,
    setIds,
    getIds,
    setValue(id) { setIds(id ? [id] : []); },
    clear() { setIds([]); },
  };
  host._mfAutocomplete = api;
  renderChips();
  return api;
}

window.MFAutocomplete = MFAutocomplete;


// ── v3.5.0-alpha.86 — MFFilterBar: barra filtri componente generico ──────────
// Costruisce una barra filtri orizzontale composta da N filter spec.
// Pattern usato in /finance, /suppliers, /cost-report, /dam, /assets_inout
// per uniformare cliente/progetto/periodo + filtri custom.
//
// Spec filter:
//   { kind: 'autocomplete', id: 'client_id', label: 'Cliente', data, search, display, placeholder, multi }
//   { kind: 'autocomplete', id: 'project_id', label: 'Progetto', data, search, display, placeholder, multi, dependsOn: 'client_id' }
//   { kind: 'date', id: 'from_date', label: 'Dal' }
//   { kind: 'date', id: 'to_date', label: 'Al' }
//   { kind: 'select', id: 'status', label: 'Stato', options: [{value, label}] }
//   { kind: 'text', id: 'q', label: 'Cerca', placeholder: 'codice, titolo...' }
//
// Output: oggetto API con getValues(), setValue(id, v), reset(), values.
// onChange invoked con dict {id: value}.

function MFFilterBar(opts) {
  const host = opts.host;
  if (!host) { console.warn('MFFilterBar: host required'); return null; }
  const specs = opts.filters || [];
  const onChange = opts.onChange || (() => {});

  host.classList.add('mf-filterbar');
  host.replaceChildren();
  host.style.display = 'flex';
  host.style.flexWrap = 'wrap';
  host.style.gap = '10px';
  host.style.alignItems = 'flex-end';
  host.style.marginBottom = '14px';

  const state = {};      // id → value (string for date/select/text, array for autocomplete)
  const widgets = {};    // id → { spec, getValue, setValue, refresh }

  function emit() {
    const vals = {};
    for (const id in widgets) vals[id] = widgets[id].getValue();
    onChange(vals);
  }

  function makeFieldWrap(label, minWidth) {
    const w = document.createElement('div');
    w.className = 'form-group mf-fb-field';
    w.style.cssText = 'display:flex;flex-direction:column;gap:3px;min-width:' + (minWidth||'140px') + ';';
    if (label) {
      const l = document.createElement('label');
      l.className = 'form-label';
      l.style.cssText = 'font-size:11px;color:var(--text2);';
      l.textContent = label;
      w.appendChild(l);
    }
    return w;
  }

  for (const spec of specs) {
    if (spec.kind === 'autocomplete') {
      const wrap = makeFieldWrap(spec.label, spec.minWidth || '180px');
      const ac = document.createElement('div');
      ac.className = 'mf-ac';
      ac.style.width = '100%';
      const hidden = document.createElement('input');
      hidden.type = 'hidden';
      hidden.id = 'mffb-' + spec.id;
      wrap.appendChild(ac);
      wrap.appendChild(hidden);
      host.appendChild(wrap);
      const api = MFAutocomplete({
        host: ac, hidden,
        data: spec.data || (() => []),
        search: spec.search,
        display: spec.display || (it => it.name || ('#'+it.id)),
        render: spec.render,
        placeholder: spec.placeholder || ('Tutti i ' + (spec.label || 'elementi').toLowerCase()),
        multi: !!spec.multi,
        onChange: (ids) => {
          // refresh dependent autocompletes (e.g., project depends on client)
          for (const id in widgets) {
            const w = widgets[id];
            if (w.spec.dependsOn === spec.id && w.refresh) w.refresh();
          }
          emit();
        },
      });
      widgets[spec.id] = {
        spec,
        getValue: () => {
          const v = hidden.value;
          if (!v) return spec.multi ? [] : null;
          const ids = v.split(',').map(Number).filter(Boolean);
          return spec.multi ? ids : (ids[0] || null);
        },
        setValue: (v) => {
          if (Array.isArray(v)) api.setIds(v);
          else api.setValue(v);
        },
        refresh: () => api.refresh && api.refresh(),
      };
    } else if (spec.kind === 'date') {
      const wrap = makeFieldWrap(spec.label, '130px');
      const inp = document.createElement('input');
      inp.type = 'date';
      inp.className = 'form-input';
      inp.id = 'mffb-' + spec.id;
      inp.style.cssText = 'height:32px;font-size:13px;';
      inp.addEventListener('change', emit);
      wrap.appendChild(inp);
      host.appendChild(wrap);
      widgets[spec.id] = {
        spec,
        getValue: () => inp.value || null,
        setValue: (v) => { inp.value = v || ''; },
      };
    } else if (spec.kind === 'select') {
      const wrap = makeFieldWrap(spec.label, spec.minWidth || '140px');
      const sel = document.createElement('select');
      sel.className = 'form-select';
      sel.id = 'mffb-' + spec.id;
      sel.dataset.noSearch = spec.searchable === false ? 'true' : 'false';
      sel.addEventListener('change', emit);
      const opts = spec.options || [];
      for (const o of opts) {
        const opt = document.createElement('option');
        opt.value = o.value;
        opt.textContent = o.label || o.value;
        sel.appendChild(opt);
      }
      wrap.appendChild(sel);
      host.appendChild(wrap);
      widgets[spec.id] = {
        spec,
        getValue: () => sel.value || null,
        setValue: (v) => { sel.value = v || ''; },
      };
    } else if (spec.kind === 'text') {
      const wrap = makeFieldWrap(spec.label, spec.minWidth || '180px');
      const inp = document.createElement('input');
      inp.type = 'text';
      inp.className = 'form-input';
      inp.id = 'mffb-' + spec.id;
      inp.placeholder = spec.placeholder || 'Cerca...';
      inp.style.cssText = 'height:32px;font-size:13px;';
      let timer = null;
      inp.addEventListener('input', () => {
        if (timer) clearTimeout(timer);
        timer = setTimeout(emit, 200);
      });
      wrap.appendChild(inp);
      host.appendChild(wrap);
      widgets[spec.id] = {
        spec,
        getValue: () => inp.value.trim() || null,
        setValue: (v) => { inp.value = v || ''; },
      };
    }
  }

  // Reset button
  if (opts.reset !== false) {
    const btnWrap = makeFieldWrap('', '80px');
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn btn-ghost btn-sm';
    btn.textContent = opts.resetLabel || 'Reset';
    btn.addEventListener('click', () => {
      for (const id in widgets) widgets[id].setValue(null);
      emit();
    });
    btnWrap.appendChild(btn);
    host.appendChild(btnWrap);
  }

  const api = {
    getValues() {
      const v = {};
      for (const id in widgets) v[id] = widgets[id].getValue();
      return v;
    },
    setValue(id, v) {
      if (widgets[id]) widgets[id].setValue(v);
    },
    refresh(id) {
      if (id && widgets[id] && widgets[id].refresh) widgets[id].refresh();
      else for (const k in widgets) widgets[k].refresh && widgets[k].refresh();
    },
    reset() {
      for (const id in widgets) widgets[id].setValue(null);
      emit();
    },
    buildQS() {
      const v = this.getValues();
      const parts = [];
      for (const id in v) {
        const val = v[id];
        if (val === null || val === undefined || val === '') continue;
        if (Array.isArray(val)) {
          if (val.length) parts.push(encodeURIComponent(id) + '=' + encodeURIComponent(val.join(',')));
        } else {
          parts.push(encodeURIComponent(id) + '=' + encodeURIComponent(val));
        }
      }
      return parts.join('&');
    },
  };
  host._mfFilterBar = api;
  return api;
}

window.MFFilterBar = MFFilterBar;


// ── v3.5.0-alpha.88 — Generic sortable tables ──────────────────
//
// Aggiungere `mf-sortable` alla <table>: ogni <th> diventa cliccabile e
// ordina la tbody secondo la colonna. Doppio click = ordine inverso.
// Per disabilitare un <th>: `data-no-sort="true"`.
// Per override del valore: `data-sort-value="..."` sulle <td>.
//
// v3.5.0-alpha.90: refactor con event delegation a livello document — risolve
// bug "sort non funziona" in cost_report list (e altre tabelle innerHTML-replaced).
// Era attaccato direttamente alle TH a DOMContentLoaded; dopo render asincrono
// la tabella restava nominalmente "sortable" ma alcune pagine vedevano gli
// handler perdersi (race/ordine init). La delegation evita il problema.
function mfEnableSortableTables(root) {
  (root || document).querySelectorAll('table.mf-sortable').forEach(table => {
    if (table.dataset.mfSortInit) return;
    table.dataset.mfSortInit = '1';
    table.querySelectorAll('thead th').forEach((th, idx) => {
      if (th.dataset.noSort === 'true') return;
      th.style.cursor = 'pointer';
      th.classList.add('mf-th-sortable');
      th.dataset.mfSortIdx = String(idx);
    });
  });
}

// Delegated click handler: 1 solo listener globale, funziona anche per
// tabelle create dinamicamente senza bisogno di re-attach.
if (!window.__mfSortDelegated) {
  window.__mfSortDelegated = true;
  document.addEventListener('click', (ev) => {
    const th = ev.target.closest && ev.target.closest('th.mf-th-sortable');
    if (!th) return;
    const table = th.closest('table.mf-sortable');
    if (!table) return;
    const idx = parseInt(th.dataset.mfSortIdx || '-1', 10);
    if (idx < 0) return;
    ev.preventDefault();
    mfSortTableBy(table, idx, th);
  }, true);
}

function mfSortTableBy(table, idx, th) {
  const tbody = table.querySelector('tbody');
  if (!tbody) return;
  const rows = Array.from(tbody.rows);
  if (!rows.length) return;
  const isAsc = th.dataset.sortDir !== 'asc';
  table.querySelectorAll('thead th').forEach(t => {
    t.dataset.sortDir = '';
    t.classList.remove('sorted-asc', 'sorted-desc');
  });
  th.dataset.sortDir = isAsc ? 'asc' : 'desc';
  th.classList.add(isAsc ? 'sorted-asc' : 'sorted-desc');
  const cellValue = (r) => {
    const c = r.cells[idx];
    if (!c) return '';
    if (c.dataset && c.dataset.sortValue != null) return c.dataset.sortValue;
    return (c.textContent || '').trim();
  };
  const tryNumber = (s) => {
    if (!s || s === '—') return NaN;
    const cleaned = String(s).replace(/[€$\s%h]/g, '').replace(/\.(?=\d{3}(\D|$))/g, '').replace(',', '.');
    const n = Number(cleaned);
    return isNaN(n) ? NaN : n;
  };
  const isoDate = (s) => /^\d{4}-\d{2}-\d{2}$/.test(s) ? s : null;
  const sampleVals = rows.slice(0, Math.min(rows.length, 6)).map(r => cellValue(r));
  const isNumeric = sampleVals.length > 0 && sampleVals.every(v => v === '' || v === '—' || !isNaN(tryNumber(v)));
  const isDate = !isNumeric && sampleVals.length > 0 && sampleVals.every(v => !v || v === '—' || isoDate(v));
  rows.sort((a, b) => {
    const av = cellValue(a), bv = cellValue(b);
    let cmp;
    if (isNumeric) {
      const an = tryNumber(av), bn = tryNumber(bv);
      const A = isNaN(an) ? -Infinity : an;
      const B = isNaN(bn) ? -Infinity : bn;
      cmp = A - B;
    } else if (isDate) {
      cmp = av.localeCompare(bv);
    } else {
      cmp = av.localeCompare(bv, 'it', { numeric: true, sensitivity: 'base' });
    }
    return isAsc ? cmp : -cmp;
  });
  const frag = document.createDocumentFragment();
  rows.forEach(r => frag.appendChild(r));
  tbody.appendChild(frag);
}

window.mfEnableSortableTables = mfEnableSortableTables;

document.addEventListener('DOMContentLoaded', () => mfEnableSortableTables());
// Tabelle riempite via API → riapplica al primo append in body.
(function watchSortable() {
  if (!('MutationObserver' in window)) return;
  let scheduled = false;
  // v3.5.0-alpha.106 fix: requestIdleCallback accetta options object, NON
  // numero come setTimeout. Wrapper unificato per evitare TypeError
  // "not of type IdleRequestOptions" su Chrome con SES/lockdown attivo.
  const schedule = window.requestIdleCallback
    ? (fn) => window.requestIdleCallback(fn, { timeout: 80 })
    : (fn) => setTimeout(fn, 80);
  const obs = new MutationObserver(() => {
    if (scheduled) return;
    scheduled = true;
    schedule(() => {
      scheduled = false;
      mfEnableSortableTables();
    });
  });
  obs.observe(document.body, { childList: true, subtree: true });
})();


// ── v3.4.40 — Time picker popup ───────────────────────────────
//
// Popup HH:MM grid che si attacca a ogni <input type="time"> non
// `data-no-time-picker`. Step 15min default (override `data-time-step`).
// Quick row con orari frequenti. Coesiste col native (typing manuale OK).

// v3.5.0-alpha.9: quick options estese per coprire turni serali/notturni
// e granulità mezz'ora sui passaggi giornata standard. La griglia completa
// resta sotto (HH:MM ogni 15min).
const _MF_TP_QUICK = [
  '07:00','08:00','08:30','09:00','09:30','10:00','10:30',
  '11:00','12:00','12:30','13:00','13:30','14:00','14:30',
  '15:00','16:00','17:00','17:30','18:00','18:30','19:00',
  '19:30','20:00','21:00','22:00','23:00','00:00',
];
let _mfTpHost = null;

function _mfTpEnsureHost() {
  if (_mfTpHost) return _mfTpHost;
  const el = document.createElement('div');
  el.className = 'mf-tp-popup';
  el.style.display = 'none';
  document.body.appendChild(el);
  _mfTpHost = el;
  document.addEventListener('mousedown', (e) => {
    if (_mfTpHost.style.display === 'none') return;
    if (!_mfTpHost.contains(e.target) && !e.target.matches('input[type="time"]')) {
      _mfTpHost.style.display = 'none';
    }
  });
  return el;
}

function _mfTpRender(input) {
  const host = _mfTpEnsureHost();
  const step = parseInt(input.dataset.timeStep || '15', 10);
  const cur = input.value || '';
  let html = '<div class="mf-tp-quick">';
  _MF_TP_QUICK.forEach(t => {
    html += `<button type="button" class="mf-tp-q ${t === cur ? 'active' : ''}" data-t="${t}">${t}</button>`;
  });
  html += '</div><div class="mf-tp-grid">';
  for (let h = 0; h < 24; h++) {
    for (let m = 0; m < 60; m += step) {
      const t = `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}`;
      html += `<button type="button" class="mf-tp-cell ${t === cur ? 'active' : ''}" data-t="${t}">${t}</button>`;
    }
  }
  html += '</div>';
  host.innerHTML = html;
  host.querySelectorAll('button[data-t]').forEach(b => {
    b.addEventListener('mousedown', (ev) => {
      ev.preventDefault();
      input.value = b.dataset.t;
      input.dispatchEvent(new Event('change', { bubbles: true }));
      input.dispatchEvent(new Event('input', { bubbles: true }));
      host.style.display = 'none';
    });
  });
  const r = input.getBoundingClientRect();
  host.style.display = 'block';
  const ph = host.offsetHeight;
  const below = window.innerHeight - r.bottom;
  host.style.left = `${Math.max(8, Math.min(window.innerWidth - host.offsetWidth - 8, r.left)) + window.scrollX}px`;
  host.style.top = (below < ph + 12 && r.top > ph + 12)
    ? `${r.top - ph - 4 + window.scrollY}px`
    : `${r.bottom + 4 + window.scrollY}px`;
}

function mfAttachTimePicker(input) {
  if (input._mfTpAttached) return;
  if (input.dataset.noTimePicker === 'true') return;
  input._mfTpAttached = true;
  input.addEventListener('focus', () => _mfTpRender(input));
  input.addEventListener('click', () => _mfTpRender(input));
}

function mfApplyTimePickers(root) {
  root = root || document;
  root.querySelectorAll('input[type="time"]').forEach(mfAttachTimePicker);
  root.querySelectorAll('input[type="datetime-local"]').forEach(mfWrapDateTimeLocal);
}


// Wrappa <input type="datetime-local"> in due input affiancati (date + time)
// per permettere al time-picker custom di operare sul time. Mantiene
// l'originale (hidden) come "verità" che riceve i value combinati e dispatcha
// `input`/`change` come prima → handlers oninput="..." continuano a funzionare.
function mfWrapDateTimeLocal(input) {
  if (input._mfDtAttached) {
    // Già wrappato → ri-allinea i sub-input al value corrente del nascosto
    if (input._mfDtReparse) input._mfDtReparse();
    return;
  }
  if (input.dataset.noMfDt === 'true') return;
  input._mfDtAttached = true;

  const wrap = document.createElement('div');
  wrap.className = 'mf-dt';
  const dateInp = document.createElement('input');
  dateInp.type = 'date';
  dateInp.className = 'form-input mf-dt-date';
  const timeInp = document.createElement('input');
  timeInp.type = 'time';
  timeInp.className = 'form-input mf-dt-time';
  timeInp.step = input.step || '900';

  input.parentNode.insertBefore(wrap, input);
  wrap.appendChild(dateInp);
  wrap.appendChild(timeInp);
  wrap.appendChild(input);
  input.style.display = 'none';

  function parseValue() {
    const v = input.value || '';
    // Formato YYYY-MM-DDTHH:MM[:SS]
    const m = v.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/);
    // v3.5.0-alpha.13 — bug timbratura "fine cancellata":
    // non sovrascriviamo i sub-input se contengono già un valore digitato
    // dall'utente. Il bug pre-alpha.13: utente apre modal con punch open
    // (no end), digita data nel sub date, syncBack scrive '' in hidden
    // (perché time è ancora vuoto), poi al focus su time → parseValue legge
    // hidden vuoto → cancellava sia date che time. Patch: se hidden ha un
    // valore valido, riempi solo i sub vuoti; se hidden è vuoto, lascia stare.
    if (m) {
      if (!dateInp.value) dateInp.value = m[1];
      if (!timeInp.value) timeInp.value = m[2];
    }
    // Se hidden vuoto e i sub-input contengono qualcosa: non toccare —
    // l'utente sta digitando, syncBack è già consistente.
  }
  function syncBack() {
    if (dateInp.value && timeInp.value) {
      input.value = `${dateInp.value}T${timeInp.value}`;
    } else {
      input.value = '';
    }
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }

  input._mfDtReparse = parseValue;
  parseValue();
  dateInp.addEventListener('change', syncBack);
  dateInp.addEventListener('input', syncBack);
  timeInp.addEventListener('change', syncBack);
  timeInp.addEventListener('input', syncBack);
  // Quando il template setta input.value programmaticamente
  const obs = new MutationObserver(parseValue);
  obs.observe(input, { attributes: true, attributeFilter: ['value'] });
  // value setter non triggera attribute change → polling leggero su focus tab
  // alternativo: hook su Object.defineProperty del prototype. Compromesso:
  // re-parse a ogni focus dei sub-input.
  dateInp.addEventListener('focus', parseValue);
  timeInp.addEventListener('focus', parseValue);

  // Attacca il time-picker custom sul time wrapper
  mfAttachTimePicker(timeInp);
}


// ── Sidebar collapse + tooltip (v3.5.0-alpha.43) ─────────────
// Toggle sidebar collassata/espansa via pulsante in topbar.
// Persistenza in localStorage. Quando collassata: hover 1s su un nav-item
// → tooltip flottante con la label completa (testo nascosto via font-size:0,
// ancora leggibile da textContent).
function mfToggleSidebar() {
  const sb = document.getElementById('sidebar');
  if (!sb) return;
  const collapsed = !sb.classList.contains('collapsed');
  sb.classList.toggle('collapsed', collapsed);
  document.body.classList.toggle('sidebar-collapsed', collapsed);
  try { localStorage.setItem('mf_sidebar_collapsed', collapsed ? '1' : '0'); } catch (_) {}
  _mfUpdateSidebarToggleIcon(collapsed);
  // Nascondi tooltip eventuale al toggle
  const tip = document.getElementById('mf-sidebar-tip');
  if (tip) tip.classList.remove('visible');
}
function _mfUpdateSidebarToggleIcon(collapsed) {
  const wrap = document.getElementById('mf-sidebar-toggle');
  if (!wrap) return;
  const newName = collapsed ? 'panel-left-open' : 'panel-left-close';
  wrap.innerHTML = `<i data-lucide="${newName}"></i>`;
  if (window.mfRenderIcons) window.mfRenderIcons(wrap);
}
function _mfInitSidebarTooltip() {
  let timer = null;
  let tipEl = null;
  function ensureTip() {
    if (tipEl) return tipEl;
    tipEl = document.createElement('div');
    tipEl.id = 'mf-sidebar-tip';
    document.body.appendChild(tipEl);
    return tipEl;
  }
  function show(item) {
    const sb = document.getElementById('sidebar');
    if (!sb || !sb.classList.contains('collapsed')) return;
    const label = (item.textContent || '').trim();
    if (!label) return;
    const t = ensureTip();
    t.textContent = label;
    const rect = item.getBoundingClientRect();
    // Posiziona a destra dell'icona, centrato verticalmente sull'item
    t.style.top = (rect.top + rect.height / 2) + 'px';
    t.style.left = (rect.right + 10) + 'px';
    t.classList.add('visible');
  }
  function hide() {
    if (timer) { clearTimeout(timer); timer = null; }
    if (tipEl) tipEl.classList.remove('visible');
  }
  document.addEventListener('mouseover', (e) => {
    const sb = document.getElementById('sidebar');
    if (!sb || !sb.classList.contains('collapsed')) { hide(); return; }
    const target = e.target.closest && e.target.closest('.nav-item, .sidebar-logo');
    if (!target || !sb.contains(target)) { hide(); return; }
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => show(target), 1000);
  });
  document.addEventListener('mouseout', (e) => {
    // Se esci dall'item o dalla sidebar, nascondi
    const target = e.target.closest && e.target.closest('.nav-item, .sidebar-logo');
    if (!target) return;
    const related = e.relatedTarget && e.relatedTarget.closest && e.relatedTarget.closest('.nav-item, .sidebar-logo');
    if (related === target) return;  // movimento interno
    hide();
  });
  // Scroll sidebar → invalida tooltip (l'item potrebbe essersi spostato)
  const sb = document.getElementById('sidebar');
  if (sb) sb.addEventListener('scroll', hide);
}
function _mfInitSidebarFromStorage() {
  const sb = document.getElementById('sidebar');
  if (!sb) return;
  let collapsed = false;
  try { collapsed = localStorage.getItem('mf_sidebar_collapsed') === '1'; } catch (_) {}
  if (collapsed) {
    sb.classList.add('collapsed');
    document.body.classList.add('sidebar-collapsed');
    _mfUpdateSidebarToggleIcon(true);
  }
}
// Scorciatoia tastiera: Ctrl+B (Cmd+B su Mac) → toggle sidebar
function _mfBindSidebarShortcut() {
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b' && !e.shiftKey && !e.altKey) {
      // Skip se utente sta scrivendo in un input/textarea/contenteditable
      const t = e.target;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
      e.preventDefault();
      mfToggleSidebar();
    }
  });
}

// ── Auto-init ────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  mfApplySearchable(document);
  mfApplyTimePickers(document);
  _mfInitSidebarFromStorage();
  _mfInitSidebarTooltip();
  _mfBindSidebarShortcut();
  // Quando si apre un modal i select interni potrebbero essere stati ri-popolati
  // dopo il DOMContentLoaded; li ricontrolliamo (idempotente).
  document.addEventListener('click', (e) => {
    const t = e.target;
    if (t && t.matches && (t.matches('[onclick*="openModal"]') || t.closest && t.closest('[onclick*="openModal"]'))) {
      setTimeout(() => { mfApplySearchable(document); mfApplyTimePickers(document); }, 80);
    }
  }, true);
});
