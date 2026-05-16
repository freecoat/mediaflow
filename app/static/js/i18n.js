// v3.5.0-alpha.133 — Sistema i18n GUI base.
//
// Architettura: dictionary client-side + data-i18n attributes nei template.
// applyI18n() scansiona il DOM e sostituisce textContent (o attributi
// specifici via data-i18n-attr) con la traduzione della lingua corrente.
//
// Persistenza: localStorage mf_lang. Default: 'it' (lingua sorgente).
//
// Scope iniziale α.133: sidebar nav + topbar + login. Espandibile: aggiungere
// data-i18n="key" agli elementi + chiave al dictionary qui sotto.
//
// Pattern di uso template:
//   <span data-i18n="nav.dashboard">Dashboard</span>
//   <input data-i18n="auth.email" data-i18n-attr="placeholder" placeholder="Email">
// Il testo IT inline resta come fallback se applyI18n() non gira o key manca.

window.MF_LANGS = ['it', 'en', 'fr', 'de'];
window.MF_LANG_META = {
  it: {flag: '🇮🇹', name: 'Italiano'},
  en: {flag: '🇬🇧', name: 'English'},
  fr: {flag: '🇫🇷', name: 'Français'},
  de: {flag: '🇩🇪', name: 'Deutsch'},
};

window.MF_I18N = {
  // ── Sidebar nav sections ──────────────────────────
  'nav.section.main':           {it: 'Principale',      en: 'Main',             fr: 'Principal',        de: 'Hauptmenü'},
  'nav.section.records':        {it: 'Anagrafica',      en: 'Records',          fr: 'Annuaire',         de: 'Stammdaten'},
  'nav.section.operations':     {it: 'Operativo',       en: 'Operations',       fr: 'Opérations',       de: 'Betrieb'},
  'nav.section.quotes':         {it: 'Preventivi',      en: 'Quotes',           fr: 'Devis',            de: 'Angebote'},
  'nav.section.finance':        {it: 'Finanza',         en: 'Finance',          fr: 'Finance',          de: 'Finanzen'},
  'nav.section.media':          {it: 'Media',           en: 'Media',            fr: 'Médias',           de: 'Medien'},
  'nav.section.platform':       {it: 'Platform',        en: 'Platform',         fr: 'Plateforme',       de: 'Plattform'},
  'nav.section.configuration':  {it: 'Configurazione',  en: 'Configuration',    fr: 'Configuration',    de: 'Konfiguration'},
  'nav.section.help':           {it: 'Aiuto',           en: 'Help',             fr: 'Aide',             de: 'Hilfe'},
  'nav.section.administration': {it: 'Amministrazione', en: 'Administration',   fr: 'Administration',   de: 'Verwaltung'},

  // ── Sidebar nav items ─────────────────────────────
  'nav.dashboard':           {it: 'Dashboard',         en: 'Dashboard',         fr: 'Tableau de bord',  de: 'Übersicht'},
  'nav.clients':             {it: 'Clienti',           en: 'Clients',           fr: 'Clients',          de: 'Kunden'},
  'nav.projects':            {it: 'Progetti',          en: 'Projects',          fr: 'Projets',          de: 'Projekte'},
  'nav.planning':            {it: 'Pianificazione',    en: 'Planning',          fr: 'Planification',    de: 'Planung'},
  'nav.team':                {it: 'Team',              en: 'Team',              fr: 'Équipe',           de: 'Team'},
  'nav.hours':               {it: 'Ore lavoro',        en: 'Work hours',        fr: 'Heures travail',   de: 'Arbeitszeiten'},
  'nav.my_hours':            {it: 'Le mie ore',        en: 'My hours',          fr: 'Mes heures',       de: 'Meine Stunden'},
  'nav.pricelist':           {it: 'Listino Prezzi',    en: 'Price List',        fr: 'Tarifs',           de: 'Preisliste'},
  'nav.quotes':              {it: 'Quotazioni',        en: 'Quotes',            fr: 'Devis',            de: 'Angebote'},
  'nav.cost_report':         {it: 'Cost Report',       en: 'Cost Report',       fr: 'Rapport coûts',    de: 'Kostenbericht'},
  'nav.finance':             {it: 'Fatturazione',      en: 'Invoicing',         fr: 'Facturation',      de: 'Rechnungen'},
  'nav.cashflow':            {it: 'Cashflow & Forecast', en: 'Cashflow & Forecast', fr: 'Trésorerie & Prévisions', de: 'Cashflow & Prognose'},
  'nav.finance_reports':     {it: 'Report YoY + Export', en: 'YoY Reports + Export', fr: 'Rapports annuels + Export', de: 'Jahresberichte + Export'},
  'nav.suppliers':           {it: 'Fornitori',         en: 'Suppliers',         fr: 'Fournisseurs',     de: 'Lieferanten'},
  'nav.overhead':            {it: 'Spese aziendali',   en: 'Overhead costs',    fr: 'Frais généraux',   de: 'Gemeinkosten'},
  'nav.dam':                 {it: 'Asset Library',     en: 'Asset Library',     fr: 'Médiathèque',      de: 'Asset-Bibliothek'},
  'nav.fs_scan':             {it: 'Scan filesystem',   en: 'Filesystem scan',   fr: 'Scan fichiers',    de: 'Dateisystem-Scan'},
  'nav.assets_inout':        {it: 'In/Out Asset',      en: 'Asset In/Out',      fr: 'Entrée/Sortie',    de: 'Asset Ein/Aus'},
  'nav.physical_assets':     {it: 'Asset Fisici',      en: 'Physical Assets',   fr: 'Supports physiques', de: 'Physische Medien'},
  'nav.delivery_templates':  {it: 'Capitolati',        en: 'Delivery Specs',    fr: 'Cahiers techniques', de: 'Lieferspezifikationen'},
  'nav.capitolati_import':   {it: 'Import → Quote',    en: 'Import → Quote',    fr: 'Importer → Devis', de: 'Import → Angebot'},
  'nav.tenants':             {it: 'Tenants',           en: 'Tenants',           fr: 'Locataires',       de: 'Mandanten'},
  'nav.departments':         {it: 'Reparti',           en: 'Departments',       fr: 'Départements',     de: 'Abteilungen'},
  'nav.settings':            {it: 'Impostazioni',      en: 'Settings',          fr: 'Paramètres',       de: 'Einstellungen'},
  'nav.manual':              {it: 'Manuale',           en: 'Manual',            fr: 'Manuel',           de: 'Handbuch'},
  'nav.users':               {it: 'Utenti',            en: 'Users',             fr: 'Utilisateurs',     de: 'Benutzer'},
  'nav.roles':               {it: 'Ruoli & Permessi',  en: 'Roles & Permissions', fr: 'Rôles & permissions', de: 'Rollen & Berechtigungen'},
  'nav.audit_log':           {it: 'Audit log',         en: 'Audit log',         fr: 'Journal audit',    de: 'Audit-Protokoll'},
  'nav.trash':               {it: 'Cestino',           en: 'Trash',             fr: 'Corbeille',        de: 'Papierkorb'},

  // ── Topbar / global UI ────────────────────────────
  'topbar.theme':            {it: 'Apri palette tema', en: 'Open theme palette', fr: 'Ouvrir palette', de: 'Farbpalette öffnen'},
  'topbar.notifications':    {it: 'Notifiche',         en: 'Notifications',     fr: 'Notifications',    de: 'Benachrichtigungen'},
  'topbar.logout':           {it: 'Logout',            en: 'Logout',            fr: 'Déconnexion',      de: 'Abmelden'},
  'topbar.language':         {it: 'Lingua',            en: 'Language',          fr: 'Langue',           de: 'Sprache'},

  // ── Auth / login page ─────────────────────────────
  'auth.title':              {it: 'Accedi',            en: 'Sign in',           fr: 'Connexion',        de: 'Anmelden'},
  'auth.email':              {it: 'Email',             en: 'Email',             fr: 'E-mail',           de: 'E-Mail'},
  'auth.password':           {it: 'Password',          en: 'Password',          fr: 'Mot de passe',     de: 'Passwort'},
  'auth.submit':             {it: 'Accedi',            en: 'Sign in',           fr: 'Se connecter',     de: 'Anmelden'},
  'auth.invalid':            {it: 'Email o password non corretti', en: 'Invalid email or password', fr: 'Email ou mot de passe incorrect', de: 'Ungültige E-Mail oder Passwort'},
};

/**
 * Ritorna la lingua corrente da localStorage (default 'it').
 */
function mfCurrentLang() {
  const v = localStorage.getItem('mf_lang') || 'it';
  return window.MF_LANGS.includes(v) ? v : 'it';
}

/**
 * Traduzione singola key. Fallback: it → key letterale.
 */
function mfT(key) {
  const lang = mfCurrentLang();
  const entry = window.MF_I18N[key];
  if (!entry) return key;
  return entry[lang] || entry.it || key;
}
window.mfT = mfT;

/**
 * Scansiona DOM e applica traduzioni a tutti gli elementi con data-i18n.
 * - default: sostituisce textContent
 * - se data-i18n-attr="placeholder": sostituisce attributo invece di textContent
 *   (utile per input placeholder, title, aria-label)
 */
function applyI18n(root) {
  root = root || document;
  const lang = mfCurrentLang();
  document.documentElement.setAttribute('lang', lang);
  root.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    const attr = el.getAttribute('data-i18n-attr');
    const translated = mfT(key);
    if (attr) {
      el.setAttribute(attr, translated);
    } else {
      // Preserva eventuali figli (es. <span class="nav-icon">) modificando
      // SOLO il primo text node trovato. Se non c'è text node, fallback
      // a textContent (rimpiazza tutto).
      let replaced = false;
      for (const node of el.childNodes) {
        if (node.nodeType === Node.TEXT_NODE && node.nodeValue.trim()) {
          node.nodeValue = ' ' + translated;
          replaced = true;
          break;
        }
      }
      if (!replaced) el.textContent = translated;
    }
  });
}
window.applyI18n = applyI18n;

/**
 * Cambia lingua: salva in localStorage + ri-applica al DOM corrente.
 */
function mfSetLang(lang) {
  if (!window.MF_LANGS.includes(lang)) return;
  localStorage.setItem('mf_lang', lang);
  applyI18n();
  // Aggiorna chip lingua nel topbar (se presente)
  const chip = document.getElementById('topbar-lang-current');
  if (chip) {
    const meta = window.MF_LANG_META[lang];
    chip.textContent = meta ? meta.flag : lang.toUpperCase();
  }
  // Aggiorna selezione popover
  document.querySelectorAll('.topbar-lang-pop .tl-cell').forEach(c => {
    c.classList.toggle('active', c.dataset.lang === lang);
  });
  if (typeof toast === 'function') {
    toast(`${window.MF_LANG_META[lang].flag} ${window.MF_LANG_META[lang].name}`, 'success');
  }
}
window.mfSetLang = mfSetLang;

/**
 * Toggle popover lingua (sticky click, no hover).
 */
function topbarLangToggleOpen(ev) {
  if (ev) ev.stopPropagation();
  const wrap = document.getElementById('topbar-lang-wrap');
  if (!wrap) return;
  const wasOpen = wrap.classList.contains('is-open');
  document.querySelectorAll('.topbar-lang-wrap.is-open').forEach(w => w.classList.remove('is-open'));
  if (!wasOpen) {
    wrap.classList.add('is-open');
    setTimeout(() => {
      const off = (e) => {
        if (!wrap.contains(e.target)) {
          wrap.classList.remove('is-open');
          document.removeEventListener('click', off);
        }
      };
      document.addEventListener('click', off);
    }, 0);
  }
}
window.topbarLangToggleOpen = topbarLangToggleOpen;

/**
 * Renderizza il popover lingua (8 lingue celle).
 */
function _topbarLangRender() {
  const pop = document.getElementById('topbar-lang-pop');
  if (!pop) return;
  while (pop.firstChild) pop.removeChild(pop.firstChild);
  const current = mfCurrentLang();
  for (const id of window.MF_LANGS) {
    const meta = window.MF_LANG_META[id]; if (!meta) continue;
    const cell = document.createElement('button');
    cell.type = 'button';
    cell.className = 'tl-cell' + (id === current ? ' active' : '');
    cell.dataset.lang = id;
    cell.title = meta.name;
    cell.addEventListener('click', () => {
      mfSetLang(id);
      const wrap = document.getElementById('topbar-lang-wrap');
      if (wrap) wrap.classList.remove('is-open');
    });
    const flag = document.createElement('span');
    flag.className = 'tl-flag';
    flag.textContent = meta.flag;
    const lbl = document.createElement('span');
    lbl.className = 'tl-lbl';
    lbl.textContent = meta.name;
    cell.appendChild(flag);
    cell.appendChild(lbl);
    pop.appendChild(cell);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  _topbarLangRender();
  // Aggiorna chip iniziale
  const chip = document.getElementById('topbar-lang-current');
  if (chip) {
    const meta = window.MF_LANG_META[mfCurrentLang()];
    chip.textContent = meta ? meta.flag : '🇮🇹';
  }
  // Applica i18n se almeno un data-i18n presente
  if (document.querySelector('[data-i18n]')) {
    applyI18n();
  }
});
