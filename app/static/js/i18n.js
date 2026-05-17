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

  // ── Dashboard (v3.5.0-alpha.147 — F29 round 1) ────
  'dash.stat.jobs':          {it: 'Job attivi',        en: 'Active jobs',       fr: 'Jobs actifs',      de: 'Aktive Jobs'},
  'dash.stat.jobs.sub':      {it: 'in corso questo mese', en: 'in progress this month', fr: 'en cours ce mois', de: 'in diesem Monat'},
  'dash.stat.resources':     {it: 'Risorse',           en: 'Resources',         fr: 'Ressources',       de: 'Ressourcen'},
  'dash.stat.resources.sub': {it: 'persone e attrezzature', en: 'people and equipment', fr: 'personnes et équipement', de: 'Personen und Ausrüstung'},
  'dash.stat.revenue':       {it: 'Fatturato (anno)',  en: 'Revenue (year)',    fr: 'Chiffre d\'affaires (année)', de: 'Umsatz (Jahr)'},
  'dash.stat.revenue.sub':   {it: 'fatture emesse/pagate', en: 'invoiced/paid',  fr: 'facturé/payé',     de: 'fakturiert/bezahlt'},
  'dash.stat.assets':        {it: 'Asset in libreria', en: 'Library assets',    fr: 'Médias bibliothèque', de: 'Bibliothek-Assets'},
  'dash.stat.assets.sub':    {it: 'video, audio, immagini', en: 'video, audio, images', fr: 'vidéo, audio, images', de: 'Video, Audio, Bilder'},
  'dash.capacity_week':      {it: 'Capacità settimana', en: 'Week capacity',    fr: 'Capacité semaine', de: 'Wochenkapazität'},
  'dash.recent_jobs':        {it: 'Job recenti',       en: 'Recent jobs',       fr: 'Jobs récents',     de: 'Aktuelle Jobs'},
  'dash.see_all':            {it: 'Vedi tutti',        en: 'See all',           fr: 'Voir tout',        de: 'Alle anzeigen'},
  'dash.pl_year':            {it: 'P&L',               en: 'P&L',               fr: 'Compte de résultat', de: 'GuV'},
  'dash.detail':             {it: 'Dettaglio',         en: 'Detail',            fr: 'Détail',           de: 'Detail'},
  'dash.my_bookings':        {it: 'I miei booking di oggi', en: 'My bookings today', fr: 'Mes réservations aujourd\'hui', de: 'Meine Buchungen heute'},
  'dash.go_my_tasks':        {it: 'Vai a "Le mie"',    en: 'Go to "Mine"',      fr: 'Voir "Les miens"', de: 'Zu "Meine"'},
  'dash.upcoming':           {it: 'Prossime scadenze · 14 gg', en: 'Upcoming deadlines · 14d', fr: 'Échéances · 14 j', de: 'Bevorstehende · 14 T.'},
  'dash.all_jobs':           {it: 'Tutti i job',       en: 'All jobs',          fr: 'Tous les jobs',    de: 'Alle Jobs'},
  'dash.margin_dept':        {it: 'Margine per reparto', en: 'Margin by department', fr: 'Marge par département', de: 'Marge nach Abteilung'},
  'dash.cost_report':        {it: 'Cost report',       en: 'Cost report',       fr: 'Rapport coûts',    de: 'Kostenbericht'},
  'dash.today_bookings':     {it: 'Booking di oggi · tutti', en: 'Today bookings · all', fr: 'Réservations du jour · toutes', de: 'Heutige Buchungen · alle'},
  'dash.go_calendar':        {it: 'Vai al calendario', en: 'Go to calendar',    fr: 'Voir calendrier',  de: 'Zum Kalender'},

  // ── Table headers commons ─────────────────────────
  'col.code':                {it: 'Codice',            en: 'Code',              fr: 'Code',             de: 'Code'},
  'col.title':               {it: 'Titolo',            en: 'Title',             fr: 'Titre',            de: 'Titel'},
  'col.client':              {it: 'Cliente',           en: 'Client',            fr: 'Client',           de: 'Kunde'},
  'col.status':              {it: 'Stato',             en: 'Status',            fr: 'Statut',           de: 'Status'},
  'col.time':                {it: 'Orario',            en: 'Time',              fr: 'Horaire',          de: 'Zeit'},
  'col.amount':              {it: 'Importo',           en: 'Amount',            fr: 'Montant',          de: 'Betrag'},
  'col.date':                {it: 'Data',              en: 'Date',              fr: 'Date',             de: 'Datum'},
  'col.project':             {it: 'Progetto',          en: 'Project',           fr: 'Projet',           de: 'Projekt'},
  'col.job':                 {it: 'Job',               en: 'Job',               fr: 'Job',              de: 'Job'},
  'col.description':         {it: 'Descrizione',       en: 'Description',       fr: 'Description',      de: 'Beschreibung'},
  'col.actions':             {it: 'Azioni',            en: 'Actions',           fr: 'Actions',          de: 'Aktionen'},
  'col.notes':               {it: 'Note',              en: 'Notes',             fr: 'Notes',            de: 'Notizen'},

  // ── Common buttons ────────────────────────────────
  'btn.save':                {it: 'Salva',             en: 'Save',              fr: 'Enregistrer',      de: 'Speichern'},
  'btn.cancel':              {it: 'Annulla',           en: 'Cancel',            fr: 'Annuler',          de: 'Abbrechen'},
  'btn.delete':              {it: 'Elimina',           en: 'Delete',            fr: 'Supprimer',        de: 'Löschen'},
  'btn.edit':                {it: 'Modifica',          en: 'Edit',              fr: 'Modifier',         de: 'Bearbeiten'},
  'btn.new':                 {it: 'Nuovo',             en: 'New',               fr: 'Nouveau',          de: 'Neu'},
  'btn.add':                 {it: 'Aggiungi',          en: 'Add',               fr: 'Ajouter',          de: 'Hinzufügen'},
  'btn.confirm':             {it: 'Conferma',          en: 'Confirm',           fr: 'Confirmer',        de: 'Bestätigen'},
  'btn.close':               {it: 'Chiudi',            en: 'Close',             fr: 'Fermer',           de: 'Schließen'},
  'btn.search':              {it: 'Cerca',             en: 'Search',            fr: 'Rechercher',       de: 'Suchen'},
  'btn.export':              {it: 'Esporta',           en: 'Export',            fr: 'Exporter',         de: 'Exportieren'},
  'btn.import':              {it: 'Importa',           en: 'Import',            fr: 'Importer',         de: 'Importieren'},
  'btn.filter':              {it: 'Filtra',            en: 'Filter',            fr: 'Filtrer',          de: 'Filtern'},
  'btn.reset':               {it: 'Reimposta',         en: 'Reset',             fr: 'Réinitialiser',    de: 'Zurücksetzen'},
  'btn.refresh':             {it: 'Aggiorna',          en: 'Refresh',           fr: 'Actualiser',       de: 'Aktualisieren'},
  'btn.loading':              {it: 'Caricamento…',     en: 'Loading…',          fr: 'Chargement…',      de: 'Wird geladen…'},

  // ── Status commons ────────────────────────────────
  'status.active':           {it: 'Attivo',            en: 'Active',            fr: 'Actif',            de: 'Aktiv'},
  'status.inactive':         {it: 'Inattivo',          en: 'Inactive',          fr: 'Inactif',          de: 'Inaktiv'},
  'status.draft':            {it: 'Bozza',             en: 'Draft',             fr: 'Brouillon',        de: 'Entwurf'},
  'status.sent':             {it: 'Inviata',           en: 'Sent',              fr: 'Envoyé',           de: 'Gesendet'},
  'status.approved':         {it: 'Approvato',         en: 'Approved',          fr: 'Approuvé',         de: 'Genehmigt'},
  'status.rejected':         {it: 'Rifiutato',         en: 'Rejected',          fr: 'Rejeté',           de: 'Abgelehnt'},
  'status.expired':          {it: 'Scaduto',           en: 'Expired',           fr: 'Expiré',           de: 'Abgelaufen'},
  'status.cancelled':        {it: 'Annullato',         en: 'Cancelled',         fr: 'Annulé',           de: 'Abgebrochen'},
  'status.paid':             {it: 'Pagato',            en: 'Paid',              fr: 'Payé',             de: 'Bezahlt'},
  'status.overdue':          {it: 'Scaduto',           en: 'Overdue',           fr: 'En retard',        de: 'Überfällig'},
  'status.completed':        {it: 'Completato',        en: 'Completed',         fr: 'Terminé',          de: 'Abgeschlossen'},

  // ── Common misc ────────────────────────────────────
  'misc.no_data':            {it: 'Nessun dato',       en: 'No data',           fr: 'Aucune donnée',    de: 'Keine Daten'},
  'misc.loading':            {it: 'Caricamento…',      en: 'Loading…',          fr: 'Chargement…',      de: 'Wird geladen…'},

  // ── Clients page (v3.5.0-alpha.148 F29 round 2) ──
  'clients.title':           {it: 'Clienti',           en: 'Clients',           fr: 'Clients',          de: 'Kunden'},
  'clients.new':             {it: '+ Nuovo cliente',   en: '+ New client',      fr: '+ Nouveau client', de: '+ Neuer Kunde'},
  'clients.col.name':        {it: 'Nome',              en: 'Name',              fr: 'Nom',              de: 'Name'},
  'clients.col.vat':         {it: 'P.IVA',             en: 'VAT',               fr: 'TVA',              de: 'USt-IdNr'},
  'clients.col.email':       {it: 'Email',             en: 'Email',             fr: 'E-mail',           de: 'E-Mail'},
  'clients.col.phone':       {it: 'Telefono',          en: 'Phone',             fr: 'Téléphone',        de: 'Telefon'},
  'clients.col.projects':    {it: 'Progetti',          en: 'Projects',          fr: 'Projets',          de: 'Projekte'},
  'clients.col.industry':    {it: 'Settore',           en: 'Industry',          fr: 'Secteur',          de: 'Branche'},
  'clients.search':          {it: 'Cerca cliente…',    en: 'Search client…',    fr: 'Rechercher client…', de: 'Kunde suchen…'},
  'clients.ai_enrich':       {it: '✨ Crea + popola con AI', en: '✨ Create + AI-enrich', fr: '✨ Créer + enrichir IA', de: '✨ Erstellen + KI'},
  'clients.empty':           {it: 'Nessun cliente. Crea il primo.', en: 'No clients. Create the first.', fr: 'Aucun client. Créer le premier.', de: 'Keine Kunden. Erstelle den ersten.'},

  // ── Projects page ─────────────────────────────────
  'projects.title':          {it: 'Progetti',          en: 'Projects',          fr: 'Projets',          de: 'Projekte'},
  'projects.new':            {it: '+ Nuovo progetto',  en: '+ New project',     fr: '+ Nouveau projet', de: '+ Neues Projekt'},
  'projects.search':         {it: 'Cerca progetto…',   en: 'Search project…',   fr: 'Rechercher projet…', de: 'Projekt suchen…'},
  'projects.col.start':      {it: 'Inizio',            en: 'Start',             fr: 'Début',            de: 'Beginn'},
  'projects.col.end':        {it: 'Fine',              en: 'End',               fr: 'Fin',              de: 'Ende'},
  'projects.col.budget':     {it: 'Budget',            en: 'Budget',            fr: 'Budget',           de: 'Budget'},
  'projects.status.active':  {it: 'Attivo',            en: 'Active',            fr: 'Actif',            de: 'Aktiv'},
  'projects.status.on_hold': {it: 'In pausa',          en: 'On hold',           fr: 'En pause',         de: 'Pausiert'},
  'projects.status.completed': {it: 'Completato',      en: 'Completed',         fr: 'Terminé',          de: 'Abgeschlossen'},
  'projects.status.cancelled': {it: 'Annullato',       en: 'Cancelled',         fr: 'Annulé',           de: 'Abgebrochen'},
  'projects.empty':          {it: 'Nessun progetto. Crea il primo.', en: 'No projects. Create the first.', fr: 'Aucun projet. Créer le premier.', de: 'Keine Projekte. Erstelle das erste.'},

  // ── Quotes page ───────────────────────────────────
  'quotes.title':            {it: 'Quotazioni',        en: 'Quotes',            fr: 'Devis',            de: 'Angebote'},
  'quotes.new':              {it: '+ Nuova quotazione', en: '+ New quote',      fr: '+ Nouveau devis',  de: '+ Neues Angebot'},
  'quotes.search':           {it: 'Cerca quotazione…', en: 'Search quote…',     fr: 'Rechercher devis…', de: 'Angebot suchen…'},
  'quotes.col.number':       {it: 'Numero',            en: 'Number',            fr: 'Numéro',           de: 'Nummer'},
  'quotes.col.version':      {it: 'Ver.',              en: 'Ver.',              fr: 'Vers.',            de: 'Ver.'},
  'quotes.col.total':        {it: 'Totale',            en: 'Total',             fr: 'Total',            de: 'Gesamt'},
  'quotes.col.issue_date':   {it: 'Data emiss.',       en: 'Issue date',        fr: 'Date émission',    de: 'Ausstellungsdatum'},
  'quotes.col.valid_until':  {it: 'Valido fino',       en: 'Valid until',       fr: 'Valable jusqu\'à', de: 'Gültig bis'},
  'quotes.economic_summary': {it: 'Riepilogo economico', en: 'Economic summary', fr: 'Résumé économique', de: 'Wirtschaftliche Übersicht'},
  'quotes.conditions':       {it: 'Condizioni economiche & scadenze', en: 'Economic conditions & deadlines', fr: 'Conditions économiques & échéances', de: 'Wirtschaftliche Bedingungen & Fristen'},
  'quotes.advance_terms':    {it: '💰 Termini di acconto strutturati', en: '💰 Structured advance terms', fr: '💰 Conditions d\'acompte structurées', de: '💰 Strukturierte Anzahlungsbedingungen'},
  'quotes.add_installment':  {it: '+ Aggiungi rata',   en: '+ Add installment', fr: '+ Ajouter échéance', de: '+ Rate hinzufügen'},
  'quotes.items':            {it: 'Voci preventivo',   en: 'Quote items',       fr: 'Postes devis',     de: 'Angebotspositionen'},
  'quotes.actions':          {it: 'Stato & azioni',    en: 'Status & actions',  fr: 'Statut & actions', de: 'Status & Aktionen'},
  'quotes.versions':         {it: 'Versioni quotazione', en: 'Quote versions',  fr: 'Versions devis',   de: 'Angebotsversionen'},
  'quotes.payment_terms':    {it: 'Termini di pagamento', en: 'Payment terms',  fr: 'Conditions paiement', de: 'Zahlungsbedingungen'},
  'quotes.billing_frequency': {it: 'Periodicità fatturazione', en: 'Billing frequency', fr: 'Fréquence facturation', de: 'Abrechnungsfrequenz'},
  'quotes.vat':              {it: 'IVA',               en: 'VAT',               fr: 'TVA',              de: 'USt'},
  'quotes.subtotal':         {it: 'Subtotale',         en: 'Subtotal',          fr: 'Sous-total',       de: 'Zwischensumme'},
  'quotes.total_net':        {it: 'Totale netto (base IVA)', en: 'Net total (VAT base)', fr: 'Total net (base TVA)', de: 'Nettogesamt (USt-Basis)'},
  'quotes.total_final':      {it: 'TOTALE',            en: 'TOTAL',             fr: 'TOTAL',            de: 'GESAMT'},
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
