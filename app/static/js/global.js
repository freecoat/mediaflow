/* MediaFlow — global.js
   Toast, modal helpers, API fetch wrapper, tema, riordino sidebar
*/

// ── Tema (preset CSS variables) ────────────────────────────────
const MF_THEMES = ['indigo', 'slate', 'forest', 'sand', 'midnight', 'copper', 'plum', 'teal', 'mono'];
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
}

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
// dentro il modal dopo averlo aperto. Fix generico per i casi in cui un
// template setta `select.value = ...` programmaticamente PRIMA di aprire
// il modal: il wrapper mf-ss non rifletteva il nuovo valore (es. "department
// non visibile nel modal risorsa"). Idempotente.
function openModal(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.add('open');
  // L'innerHTML del modal potrebbe essere stato appena popolato: ritarda di
  // un tick così i value impostati nel medesimo turno sincrono sono visibili.
  setTimeout(() => {
    try {
      if (typeof mfApplySearchable === 'function') mfApplySearchable(el);
      if (typeof mfApplyTimePickers === 'function') mfApplyTimePickers(el);
    } catch (e) { /* fail-safe: non bloccare apertura */ }
  }, 0);
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


// ── Auto-init ────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  mfApplySearchable(document);
  mfApplyTimePickers(document);
  // Quando si apre un modal i select interni potrebbero essere stati ri-popolati
  // dopo il DOMContentLoaded; li ricontrolliamo (idempotente).
  document.addEventListener('click', (e) => {
    const t = e.target;
    if (t && t.matches && (t.matches('[onclick*="openModal"]') || t.closest && t.closest('[onclick*="openModal"]'))) {
      setTimeout(() => { mfApplySearchable(document); mfApplyTimePickers(document); }, 80);
    }
  }, true);
});
