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

window.MF_LANGS = ['it', 'en', 'fr', 'de', 'es'];
window.MF_LANG_META = {
  it: {flag: '🇮🇹', name: 'Italiano'},
  en: {flag: '🇬🇧', name: 'English'},
  fr: {flag: '🇫🇷', name: 'Français'},
  de: {flag: '🇩🇪', name: 'Deutsch'},
  es: {flag: '🇪🇸', name: 'Español'},
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

  // ── Planning (v3.5.0-alpha.149 F29 round 3) ───────
  'plan.title':              {it: 'Pianificazione',    en: 'Planning',          fr: 'Planification',    de: 'Planung'},
  'plan.tab.calendar':       {it: 'Calendario',        en: 'Calendar',          fr: 'Calendrier',       de: 'Kalender'},
  'plan.tab.timeline':       {it: 'Timeline',          en: 'Timeline',          fr: 'Chronologie',      de: 'Zeitleiste'},
  'plan.tab.gantt':          {it: 'Gantt',             en: 'Gantt',             fr: 'Gantt',            de: 'Gantt'},
  'plan.tab.kanban':         {it: 'Kanban',            en: 'Kanban',            fr: 'Kanban',           de: 'Kanban'},
  'plan.tab.list':           {it: 'Lista',             en: 'List',              fr: 'Liste',            de: 'Liste'},
  'plan.tab.todo':           {it: 'Le mie',            en: 'Mine',              fr: 'Les miens',        de: 'Meine'},
  'plan.new_booking':        {it: '+ Nuovo booking',   en: '+ New booking',     fr: '+ Nouvelle résa',  de: '+ Neue Buchung'},
  'plan.filter.resource':    {it: 'Risorse',           en: 'Resources',         fr: 'Ressources',       de: 'Ressourcen'},
  'plan.filter.job':         {it: 'Job',               en: 'Job',               fr: 'Job',              de: 'Job'},
  'plan.filter.status':      {it: 'Stato',             en: 'Status',            fr: 'Statut',           de: 'Status'},
  'plan.filter.from':        {it: 'Dal',               en: 'From',              fr: 'Du',               de: 'Von'},
  'plan.filter.to':          {it: 'Al',                en: 'To',                fr: 'Au',               de: 'Bis'},
  'plan.status.tentative':   {it: 'Tentativo',         en: 'Tentative',         fr: 'Provisoire',       de: 'Vorläufig'},
  'plan.status.confirmed':   {it: 'Confermato',        en: 'Confirmed',         fr: 'Confirmé',         de: 'Bestätigt'},
  'plan.status.done':        {it: 'Eseguito',          en: 'Done',              fr: 'Effectué',         de: 'Erledigt'},
  'plan.status.not_done':    {it: 'Non fatto',         en: 'Not done',          fr: 'Non fait',         de: 'Nicht erledigt'},

  // ── Finance ────────────────────────────────────────
  'fin.title':               {it: 'Fatturazione',      en: 'Invoicing',         fr: 'Facturation',      de: 'Rechnungen'},
  'fin.tab.invoices':        {it: 'Fatture',           en: 'Invoices',          fr: 'Factures',         de: 'Rechnungen'},
  'fin.tab.batches':         {it: '📦 Batch fatturazione', en: '📦 Billing batches', fr: '📦 Lots facturation', de: '📦 Rechnungsbatches'},
  'fin.tab.anomalies':       {it: '⚠ Anomalie',        en: '⚠ Anomalies',       fr: '⚠ Anomalies',      de: '⚠ Anomalien'},
  'fin.tab.advances_drafts': {it: '💰 Bozze acconti',  en: '💰 Advance drafts', fr: '💰 Brouillons acomptes', de: '💰 Anzahlungsentwürfe'},
  'fin.new_invoice':         {it: '+ Nuova fattura',   en: '+ New invoice',     fr: '+ Nouvelle facture', de: '+ Neue Rechnung'},
  'fin.compose_invoice':     {it: '📦 Componi fattura', en: '📦 Compose invoice', fr: '📦 Composer facture', de: '📦 Rechnung erstellen'},
  'fin.col.invoice_number':  {it: 'Numero',            en: 'Number',            fr: 'Numéro',           de: 'Nummer'},
  'fin.col.issue_date':      {it: 'Data emiss.',       en: 'Issue date',        fr: 'Émission',         de: 'Ausstellung'},
  'fin.col.due_date':        {it: 'Scadenza',          en: 'Due date',          fr: 'Échéance',         de: 'Fälligkeit'},
  'fin.col.total':           {it: 'Totale',            en: 'Total',             fr: 'Total',            de: 'Gesamt'},
  'fin.col.paid':            {it: 'Pagato',            en: 'Paid',              fr: 'Payé',             de: 'Bezahlt'},
  'fin.col.outstanding':     {it: 'Aperto',            en: 'Outstanding',       fr: 'Ouvert',           de: 'Offen'},
  'fin.anom.legend':         {it: '📖 Legenda tipi anomalie e azioni', en: '📖 Anomaly types & actions legend', fr: '📖 Légende types d\'anomalies', de: '📖 Anomalietypen-Legende'},
  'fin.adv.open':            {it: '💰 Acconti aperti (da scomputare o ancora attivi)', en: '💰 Open advances (to consume or still active)', fr: '💰 Acomptes ouverts', de: '💰 Offene Anzahlungen'},
  'fin.adv.drafts':          {it: '💰 Acconti in bozza — da emettere o confermare', en: '💰 Advance drafts — to emit or confirm', fr: '💰 Acomptes en brouillon', de: '💰 Anzahlungsentwürfe'},

  // ── Cost Report ────────────────────────────────────
  'cr.title':                {it: 'Cost Report',       en: 'Cost Report',       fr: 'Rapport coûts',    de: 'Kostenbericht'},
  'cr.search':               {it: 'Cerca job…',        en: 'Search job…',       fr: 'Rechercher job…',  de: 'Job suchen…'},
  'cr.view_mode':            {it: 'Vista',             en: 'View',              fr: 'Vue',              de: 'Ansicht'},
  'cr.view.now':             {it: 'Maturato (ora)',    en: 'Accrued (now)',     fr: 'Couru (maintenant)', de: 'Aufgelaufen (jetzt)'},
  'cr.view.forecast':        {it: 'Stima (a finire)',  en: 'Forecast (to-go)',  fr: 'Prévu (à venir)',  de: 'Prognose (bis Ende)'},
  'cr.summary.budget':       {it: 'Budget quotato',    en: 'Quoted budget',     fr: 'Budget devis',     de: 'Angebotsbudget'},
  'cr.summary.billed_locked': {it: 'Fatturato chiuso', en: 'Locked billed',     fr: 'Facturé clôturé',  de: 'Fakturiert (fest)'},
  'cr.summary.accrued_post': {it: 'Maturato post-periodo', en: 'Accrued post-period', fr: 'Couru post-période', de: 'Aufgelaufen nachher'},
  'cr.summary.forecast':     {it: 'Stimato futuro',    en: 'Forecast future',   fr: 'Prévu futur',      de: 'Zukünftig'},
  'cr.summary.margin':       {it: 'Margine stimato',   en: 'Estimated margin',  fr: 'Marge estimée',    de: 'Geschätzte Marge'},
  'cr.summary.invoiced_total': {it: 'Fatturato totale', en: 'Total invoiced',   fr: 'Facturé total',    de: 'Gesamt fakturiert'},
  'cr.summary.advances':     {it: 'Acconti del progetto', en: 'Project advances', fr: 'Acomptes projet', de: 'Projekt-Anzahlungen'},
  'cr.col.unit':             {it: 'Unità',             en: 'Unit',              fr: 'Unité',            de: 'Einheit'},
  'cr.col.quoted':           {it: 'Quotato',           en: 'Quoted',            fr: 'Devisé',           de: 'Angeboten'},
  'cr.col.billed':           {it: 'Fatturato',         en: 'Billed',            fr: 'Facturé',          de: 'Fakturiert'},
  'cr.col.accrued_post':     {it: 'Maturato post',     en: 'Accrued post',      fr: 'Couru post',       de: 'Aufgelaufen'},
  'cr.col.forecast':         {it: 'Stim. futuro',      en: 'Forecast',          fr: 'Prévu',            de: 'Prognose'},
  'cr.col.over_under':       {it: 'Over/Under',        en: 'Over/Under',        fr: 'Sur/Sous',         de: 'Über/Unter'},
  'cr.col.real_cost':        {it: 'Costo reale',       en: 'Real cost',         fr: 'Coût réel',        de: 'Echte Kosten'},
  'cr.col.real_margin':      {it: 'Margine reale',     en: 'Real margin',       fr: 'Marge réelle',     de: 'Echte Marge'},

  // ── Suppliers (v3.5.0-alpha.150 F29 round 4) ──────
  'sup.title':               {it: 'Fornitori',         en: 'Suppliers',         fr: 'Fournisseurs',     de: 'Lieferanten'},
  'sup.new':                 {it: '+ Nuovo fornitore', en: '+ New supplier',    fr: '+ Nouveau fournisseur', de: '+ Neuer Lieferant'},
  'sup.search':              {it: 'Cerca fornitore…',  en: 'Search supplier…',  fr: 'Rechercher fournisseur…', de: 'Lieferant suchen…'},
  'sup.col.vat':             {it: 'P.IVA',             en: 'VAT',               fr: 'TVA',              de: 'USt-IdNr'},
  'sup.col.contact':         {it: 'Contatto',          en: 'Contact',           fr: 'Contact',          de: 'Kontakt'},
  'sup.col.invoices':        {it: 'Fatture',           en: 'Invoices',          fr: 'Factures',         de: 'Rechnungen'},
  'sup.col.outstanding':     {it: 'Aperto',            en: 'Outstanding',       fr: 'Ouvert',           de: 'Offen'},
  'sup.invoices.title':      {it: 'Fatture passive',   en: 'Supplier invoices', fr: 'Factures fournisseurs', de: 'Lieferantenrechnungen'},
  'sup.new_invoice':         {it: '+ Nuova fattura passiva', en: '+ New supplier invoice', fr: '+ Nouvelle facture fourn.', de: '+ Neue Lieferantenrechnung'},

  // ── Resources / Team ──────────────────────────────
  'res.title':               {it: 'Risorse',           en: 'Resources',         fr: 'Ressources',       de: 'Ressourcen'},
  'res.new':                 {it: '+ Nuova risorsa',   en: '+ New resource',    fr: '+ Nouvelle ressource', de: '+ Neue Ressource'},
  'res.search':              {it: 'Cerca risorsa…',    en: 'Search resource…',  fr: 'Rechercher ressource…', de: 'Ressource suchen…'},
  'res.tab.all':             {it: 'Tutte',             en: 'All',               fr: 'Toutes',           de: 'Alle'},
  'res.tab.people':          {it: 'Persone',           en: 'People',            fr: 'Personnes',        de: 'Personen'},
  'res.tab.studios':         {it: 'Sale',              en: 'Studios',           fr: 'Studios',          de: 'Studios'},
  'res.tab.equipment':       {it: 'Attrezzature',      en: 'Equipment',         fr: 'Équipement',       de: 'Ausrüstung'},
  'res.col.type':            {it: 'Tipo',              en: 'Type',              fr: 'Type',             de: 'Typ'},
  'res.col.role':            {it: 'Ruolo',             en: 'Role',              fr: 'Rôle',             de: 'Rolle'},
  'res.col.dept':            {it: 'Reparto',           en: 'Department',        fr: 'Département',      de: 'Abteilung'},
  'res.col.rate':            {it: 'Tariffa',           en: 'Rate',              fr: 'Tarif',            de: 'Tarif'},
  'res.show_inactive':       {it: 'Mostra inattive',   en: 'Show inactive',     fr: 'Afficher inactives', de: 'Inaktive anzeigen'},

  // ── Departments ───────────────────────────────────
  'dept.title':              {it: 'Reparti',           en: 'Departments',       fr: 'Départements',     de: 'Abteilungen'},
  'dept.new':                {it: '+ Nuovo reparto',   en: '+ New department',  fr: '+ Nouveau département', de: '+ Neue Abteilung'},
  'dept.col.name':           {it: 'Nome',              en: 'Name',              fr: 'Nom',              de: 'Name'},
  'dept.col.head':           {it: 'Responsabile',      en: 'Head',              fr: 'Responsable',      de: 'Leitung'},
  'dept.col.budget':         {it: 'Budget annuale',    en: 'Annual budget',     fr: 'Budget annuel',    de: 'Jahresbudget'},
  'dept.col.resources':      {it: 'Risorse',           en: 'Resources',         fr: 'Ressources',       de: 'Ressourcen'},

  // ── Settings ──────────────────────────────────────
  'set.title':               {it: 'Impostazioni',      en: 'Settings',          fr: 'Paramètres',       de: 'Einstellungen'},
  'set.tab.company':         {it: 'Azienda',           en: 'Company',           fr: 'Entreprise',       de: 'Unternehmen'},
  'set.tab.ai':              {it: '🤖 AI',             en: '🤖 AI',             fr: '🤖 IA',            de: '🤖 KI'},
  'set.tab.numbering':       {it: 'Numerazione',       en: 'Numbering',         fr: 'Numérotation',     de: 'Nummerierung'},
  'set.tab.security':        {it: 'Sicurezza',         en: 'Security',          fr: 'Sécurité',         de: 'Sicherheit'},
  'set.tab.data':            {it: 'Dati',              en: 'Data',              fr: 'Données',          de: 'Daten'},
  'set.tab.brand':           {it: 'Branding',          en: 'Branding',          fr: 'Image de marque',  de: 'Markenbild'},
  'set.tab.policies':        {it: 'Politiche',         en: 'Policies',          fr: 'Politiques',       de: 'Richtlinien'},
  'set.fiscal_info':         {it: 'Anagrafica fiscale', en: 'Fiscal info',      fr: 'Données fiscales', de: 'Steuerdaten'},
  'set.base_currency':       {it: 'Valuta base (ISO 4217)', en: 'Base currency (ISO 4217)', fr: 'Devise de base (ISO 4217)', de: 'Basiswährung (ISO 4217)'},
  'set.vat_default':         {it: 'Aliquota IVA default (%)', en: 'Default VAT rate (%)', fr: 'Taux TVA défaut (%)', de: 'Standard-USt-Satz (%)'},
  'set.save':                {it: 'Salva impostazioni', en: 'Save settings',    fr: 'Enregistrer',      de: 'Speichern'},

  // ── α.151 round 5 — Modal commons + Form labels ────
  'modal.new':               {it: 'Nuovo',             en: 'New',               fr: 'Nouveau',          de: 'Neu'},
  'modal.edit':              {it: 'Modifica',          en: 'Edit',              fr: 'Modifier',         de: 'Bearbeiten'},
  'modal.confirm_delete':    {it: 'Confermi eliminazione?', en: 'Confirm delete?', fr: 'Confirmer suppression?', de: 'Löschen bestätigen?'},
  'modal.required_fields':   {it: 'Campi obbligatori', en: 'Required fields',   fr: 'Champs requis',    de: 'Pflichtfelder'},

  // Form labels comuni (riusabili)
  'form.name':               {it: 'Nome',              en: 'Name',              fr: 'Nom',              de: 'Name'},
  'form.email':              {it: 'Email',             en: 'Email',             fr: 'E-mail',           de: 'E-Mail'},
  'form.phone':              {it: 'Telefono',          en: 'Phone',             fr: 'Téléphone',        de: 'Telefon'},
  'form.address':            {it: 'Indirizzo',         en: 'Address',           fr: 'Adresse',          de: 'Adresse'},
  'form.city':               {it: 'Città',             en: 'City',              fr: 'Ville',            de: 'Stadt'},
  'form.country':            {it: 'Paese',             en: 'Country',           fr: 'Pays',             de: 'Land'},
  'form.zip':                {it: 'CAP',               en: 'ZIP',               fr: 'Code postal',      de: 'PLZ'},
  'form.province':           {it: 'Provincia',         en: 'Province',          fr: 'Province',         de: 'Provinz'},
  'form.vat_number':         {it: 'P.IVA',             en: 'VAT number',        fr: 'N° TVA',           de: 'USt-IdNr'},
  'form.tax_code':           {it: 'Codice fiscale',    en: 'Tax code',          fr: 'Code fiscal',      de: 'Steuernummer'},
  'form.notes':              {it: 'Note',              en: 'Notes',             fr: 'Notes',            de: 'Notizen'},
  'form.description':        {it: 'Descrizione',       en: 'Description',       fr: 'Description',      de: 'Beschreibung'},
  'form.title':              {it: 'Titolo',            en: 'Title',             fr: 'Titre',            de: 'Titel'},
  'form.start_date':         {it: 'Data inizio',       en: 'Start date',        fr: 'Date début',       de: 'Startdatum'},
  'form.end_date':           {it: 'Data fine',         en: 'End date',          fr: 'Date fin',         de: 'Enddatum'},
  'form.date':               {it: 'Data',              en: 'Date',              fr: 'Date',             de: 'Datum'},
  'form.amount':             {it: 'Importo',           en: 'Amount',            fr: 'Montant',          de: 'Betrag'},
  'form.quantity':           {it: 'Quantità',          en: 'Quantity',          fr: 'Quantité',         de: 'Menge'},
  'form.unit':               {it: 'Unità',             en: 'Unit',              fr: 'Unité',            de: 'Einheit'},
  'form.unit_price':         {it: 'Prezzo unitario',   en: 'Unit price',        fr: 'Prix unitaire',    de: 'Stückpreis'},
  'form.discount':           {it: 'Sconto',            en: 'Discount',          fr: 'Remise',           de: 'Rabatt'},
  'form.vat_rate':           {it: 'IVA %',             en: 'VAT %',             fr: 'TVA %',            de: 'USt %'},
  'form.required_mark':      {it: '*',                 en: '*',                 fr: '*',                de: '*'},

  // Toast messages comuni (per JS via mfT())
  'toast.saved':             {it: 'Salvato',           en: 'Saved',             fr: 'Enregistré',       de: 'Gespeichert'},
  'toast.deleted':           {it: 'Eliminato',         en: 'Deleted',           fr: 'Supprimé',         de: 'Gelöscht'},
  'toast.created':           {it: 'Creato',            en: 'Created',           fr: 'Créé',             de: 'Erstellt'},
  'toast.updated':           {it: 'Aggiornato',        en: 'Updated',           fr: 'Mis à jour',       de: 'Aktualisiert'},
  'toast.error':             {it: 'Errore',            en: 'Error',             fr: 'Erreur',           de: 'Fehler'},
  'toast.error_loading':     {it: 'Errore caricamento', en: 'Error loading',    fr: 'Erreur de chargement', de: 'Ladefehler'},
  'toast.error_save':        {it: 'Errore salvataggio', en: 'Save error',       fr: 'Erreur d\'enregistrement', de: 'Speicherfehler'},
  'toast.required_fields':   {it: 'Compila i campi obbligatori', en: 'Fill required fields', fr: 'Remplir champs requis', de: 'Pflichtfelder ausfüllen'},
  'toast.access_denied':     {it: 'Accesso negato',    en: 'Access denied',     fr: 'Accès refusé',     de: 'Zugriff verweigert'},
  'toast.not_found':         {it: 'Non trovato',       en: 'Not found',         fr: 'Non trouvé',       de: 'Nicht gefunden'},
  'toast.unsaved_changes':   {it: 'Modifiche non salvate', en: 'Unsaved changes', fr: 'Modifications non enregistrées', de: 'Ungespeicherte Änderungen'},

  // Status / billing badge dinamici (per JS render)
  'badge.not_billed':        {it: 'Da fatturare',      en: 'To bill',           fr: 'À facturer',       de: 'Zu fakturieren'},
  'badge.in_batch':          {it: 'In approv.',        en: 'In review',         fr: 'En revue',         de: 'In Prüfung'},
  'badge.billed':            {it: 'Fatturato',         en: 'Billed',            fr: 'Facturé',          de: 'Fakturiert'},
  'badge.paid':              {it: 'Pagato',            en: 'Paid',              fr: 'Payé',             de: 'Bezahlt'},
  'badge.lost':              {it: 'Perso',             en: 'Lost',              fr: 'Perdu',            de: 'Verloren'},

  // Generic UI text
  'ui.yes':                  {it: 'Sì',                en: 'Yes',               fr: 'Oui',              de: 'Ja'},
  'ui.no':                   {it: 'No',                en: 'No',                fr: 'Non',              de: 'Nein'},
  'ui.all':                  {it: 'Tutti',             en: 'All',               fr: 'Tous',             de: 'Alle'},
  'ui.none':                 {it: 'Nessuno',           en: 'None',              fr: 'Aucun',            de: 'Keiner'},
  'ui.optional':             {it: 'opzionale',         en: 'optional',          fr: 'optionnel',        de: 'optional'},
  'ui.required':             {it: 'obbligatorio',      en: 'required',          fr: 'requis',           de: 'erforderlich'},
  'ui.total':                {it: 'Totale',            en: 'Total',             fr: 'Total',            de: 'Gesamt'},
  'ui.subtotal':             {it: 'Subtotale',         en: 'Subtotal',          fr: 'Sous-total',       de: 'Zwischensumme'},
  'ui.from':                 {it: 'Dal',               en: 'From',              fr: 'Du',               de: 'Vom'},
  'ui.to':                   {it: 'Al',                en: 'To',                fr: 'Au',               de: 'Bis'},
  'ui.show':                 {it: 'Mostra',            en: 'Show',              fr: 'Afficher',         de: 'Anzeigen'},
  'ui.hide':                 {it: 'Nascondi',          en: 'Hide',              fr: 'Masquer',          de: 'Ausblenden'},

  // ── α.165 sweep: column headers tabelle lista ─────
  'col.type':                {it: 'Tipo',              en: 'Type',              fr: 'Type',             de: 'Typ'},
  'col.unit':                {it: 'Unità',             en: 'Unit',              fr: 'Unité',            de: 'Einheit'},
  'col.price':               {it: 'Prezzo €',          en: 'Price €',           fr: 'Prix €',           de: 'Preis €'},
  'col.hardcost':            {it: 'Hardcost €',        en: 'Hardcost €',        fr: 'Coût direct €',    de: 'Direktkosten €'},
  'col.category':            {it: 'Categoria',         en: 'Category',          fr: 'Catégorie',        de: 'Kategorie'},
  'col.name':                {it: 'Nome',              en: 'Name',              fr: 'Nom',              de: 'Name'},
  'col.role':                {it: 'Ruolo',             en: 'Role',              fr: 'Rôle',             de: 'Rolle'},
  'col.dept':                {it: 'Reparto',           en: 'Department',        fr: 'Département',      de: 'Abteilung'},
  'col.rate_day':            {it: 'Tariffa/g',         en: 'Rate/day',          fr: 'Tarif/j',          de: 'Tagessatz'},
  'col.rate_hour':           {it: 'Tariffa/h',         en: 'Rate/h',            fr: 'Tarif/h',          de: 'Stundensatz'},
  'col.contacts':            {it: 'Contatti',          en: 'Contacts',          fr: 'Contacts',         de: 'Kontakte'},
  'col.created':             {it: 'Creato',            en: 'Created',           fr: 'Créé',             de: 'Erstellt'},
  'col.items':               {it: 'Voci',              en: 'Items',             fr: 'Postes',           de: 'Posten'},
  'col.subcategories':       {it: 'Categ.',            en: 'Subcat.',           fr: 'Sous-cat.',        de: 'Unterkat.'},
  'col.duration':            {it: 'Durata',            en: 'Duration',          fr: 'Durée',            de: 'Dauer'},
  'col.delivery':            {it: 'Consegna',          en: 'Delivery',          fr: 'Livraison',        de: 'Lieferung'},
  'col.quote_job':           {it: 'Quote / Job',       en: 'Quote / Job',       fr: 'Devis / Job',      de: 'Angebot / Job'},
  'col.location':            {it: 'Sede',              en: 'Location',          fr: 'Siège',            de: 'Standort'},
  'col.contact':             {it: 'Contatto',          en: 'Contact',           fr: 'Contact',          de: 'Kontakt'},
  'col.number':              {it: 'Numero',            en: 'Number',            fr: 'Numéro',           de: 'Nummer'},
  'col.deadline':            {it: 'Scadenza',          en: 'Deadline',          fr: 'Échéance',         de: 'Frist'},
  'col.total':               {it: 'Totale',            en: 'Total',             fr: 'Total',            de: 'Gesamt'},
  'col.supplier':            {it: 'Fornitore',         en: 'Supplier',          fr: 'Fournisseur',      de: 'Lieferant'},
  'col.issue':               {it: 'Emissione',         en: 'Issue',             fr: 'Émission',         de: 'Ausstellung'},
  'col.taxable':             {it: 'Imponibile',        en: 'Taxable',           fr: 'Imposable',        de: 'Steuerbar'},
  'col.vat':                 {it: 'IVA',               en: 'VAT',               fr: 'TVA',              de: 'USt'},
  'col.paid':                {it: 'Pagato',            en: 'Paid',              fr: 'Paid',             de: 'Bezahlt'},
  'col.outstanding':         {it: 'Aperto',            en: 'Outstanding',       fr: 'Ouvert',           de: 'Offen'},
  'col.invoices':            {it: 'Fatture',           en: 'Invoices',          fr: 'Factures',         de: 'Rechnungen'},
  'col.vat_cf':              {it: 'P.IVA / CF',        en: 'VAT / Tax ID',      fr: 'TVA / CF',         de: 'USt / Steuer-Nr'},
  'col.head':                {it: 'Responsabile',      en: 'Head',              fr: 'Responsable',      de: 'Leitung'},
  'col.budget':              {it: 'Budget',            en: 'Budget',            fr: 'Budget',           de: 'Budget'},
  'col.budget_annual':       {it: 'Budget annuo',      en: 'Annual budget',     fr: 'Budget annuel',    de: 'Jahresbudget'},
  'col.resources':           {it: 'Risorse',           en: 'Resources',         fr: 'Ressources',       de: 'Ressourcen'},
  'col.price_items':         {it: 'Voci listino',      en: 'Price items',       fr: 'Postes tarif',     de: 'Preispositionen'},
  'col.user':                {it: 'Utente',            en: 'User',              fr: 'Utilisateur',      de: 'Benutzer'},
  'col.email':               {it: 'Email',             en: 'Email',             fr: 'E-mail',           de: 'E-Mail'},
  'col.linked_resource':     {it: 'Risorsa collegata', en: 'Linked resource',   fr: 'Ressource liée',   de: 'Verknüpfte Ressource'},
  'col.last_access':         {it: 'Ultimo accesso',    en: 'Last access',       fr: 'Dernier accès',    de: 'Letzter Zugriff'},
  'col.timestamp':           {it: 'Timestamp',         en: 'Timestamp',         fr: 'Horodatage',       de: 'Zeitstempel'},
  'col.action':              {it: 'Action',            en: 'Action',            fr: 'Action',           de: 'Aktion'},
  'col.asset':               {it: 'Asset',             en: 'Asset',             fr: 'Actif',            de: 'Asset'},
  'col.ip':                  {it: 'IP',                en: 'IP',                fr: 'IP',               de: 'IP'},
  'col.ua':                  {it: 'UA',                en: 'UA',                fr: 'UA',               de: 'UA'},
  'col.extra':               {it: 'Extra',             en: 'Extra',             fr: 'Extra',            de: 'Extra'},
  'col.period':              {it: 'Periodo',           en: 'Period',            fr: 'Période',          de: 'Zeitraum'},
  'col.progress':            {it: 'Avanzamento',       en: 'Progress',          fr: 'Progression',      de: 'Fortschritt'},
  'col.label':               {it: 'Etichetta',         en: 'Label',             fr: 'Étiquette',        de: 'Bezeichnung'},
  'col.serial':              {it: 'Serial / Barcode',  en: 'Serial / Barcode',  fr: 'Série / Code-barres', de: 'Seriennr / Barcode'},
  'col.capacity':            {it: 'Capacità',          en: 'Capacity',          fr: 'Capacité',         de: 'Kapazität'},
  'col.flags':               {it: 'Flags',             en: 'Flags',             fr: 'Drapeaux',         de: 'Flags'},
  'col.issuer':              {it: 'Emittente',         en: 'Issuer',            fr: 'Émetteur',         de: 'Aussteller'},
  'col.version':             {it: 'Versione',          en: 'Version',           fr: 'Version',          de: 'Version'},
  'col.blocks':              {it: 'Blocchi',           en: 'Blocks',            fr: 'Blocs',            de: 'Blöcke'},
  'col.file':                {it: 'File',              en: 'File',              fr: 'Fichier',          de: 'Datei'},
  'col.size':                {it: 'Dimensione',        en: 'Size',              fr: 'Taille',           de: 'Größe'},
  'col.ext':                 {it: 'Estensione',        en: 'Extension',         fr: 'Extension',        de: 'Erweiterung'},
  'col.template':            {it: 'Template',          en: 'Template',          fr: 'Modèle',           de: 'Vorlage'},
  'col.direction':           {it: 'Direzione',         en: 'Direction',         fr: 'Direction',        de: 'Richtung'},
  'col.carrier':             {it: 'Vettore',           en: 'Carrier',           fr: 'Transporteur',     de: 'Spediteur'},
  'col.tracking':            {it: 'Tracking',          en: 'Tracking',          fr: 'Suivi',            de: 'Sendungsverfolgung'},
  'col.cost':                {it: 'Costo',             en: 'Cost',              fr: 'Coût',             de: 'Kosten'},
  'col.payer':               {it: 'Payer',             en: 'Payer',             fr: 'Payeur',           de: 'Zahler'},
  'col.pickup':              {it: 'Pickup',            en: 'Pickup',            fr: 'Enlèvement',       de: 'Abholung'},
  'col.packages':            {it: 'Colli',             en: 'Packages',          fr: 'Colis',            de: 'Pakete'},
  'col.workitem':            {it: 'Lavorazione',       en: 'Work item',         fr: 'Travail',          de: 'Bearbeitung'},
  'col.from_to':             {it: 'Da → A',            en: 'From → To',         fr: 'De → À',           de: 'Von → An'},
  'col.nature':              {it: 'Natura',            en: 'Nature',            fr: 'Nature',           de: 'Natur'},
  'col.ddt':                 {it: 'DDT',               en: 'DDT',               fr: 'DDT',              de: 'DDT'},
  'col.month':               {it: 'Mese',              en: 'Month',             fr: 'Mois',             de: 'Monat'},
  'col.revenue':             {it: 'Revenue',           en: 'Revenue',           fr: 'Revenu',           de: 'Umsatz'},
  'col.outflow_suppliers':   {it: 'Outflow fornitori', en: 'Supplier outflow',  fr: 'Sortie fournisseurs', de: 'Lieferanten-Abfluss'},
  'col.margin':              {it: 'Margine',           en: 'Margin',            fr: 'Marge',            de: 'Marge'},
  'col.margin_pct':          {it: '% margine',         en: '% margin',          fr: '% marge',          de: '% Marge'},
  'col.invoiced':            {it: 'Fatturato',         en: 'Invoiced',          fr: 'Facturé',          de: 'Fakturiert'},
  'col.cashed':              {it: 'Incassato',         en: 'Cashed in',         fr: 'Encaissé',         de: 'Eingenommen'},
  'col.supplier_invoices':   {it: 'Fatt. passive',     en: 'Supplier inv.',     fr: 'Factures fourn.',  de: 'Eingangsrechn.'},
  'col.outflow':             {it: 'Outflow',           en: 'Outflow',           fr: 'Sortie',           de: 'Abfluss'},
  'col.net_cash':            {it: 'Cassa netta',       en: 'Net cash',          fr: 'Trésorerie nette', de: 'Netto-Kasse'},
  'col.cash_in_pct':         {it: '% Incasso',         en: '% Collection',      fr: '% Encaiss.',       de: '% Inkasso'},
  'col.when':                {it: 'Quando',            en: 'When',              fr: 'Quand',            de: 'Wann'},
  'col.method':              {it: 'Metodo',            en: 'Method',            fr: 'Méthode',          de: 'Methode'},
  'col.ref':                 {it: 'Rif.',              en: 'Ref.',              fr: 'Réf.',             de: 'Ref.'},
  'col.resource':            {it: 'Risorsa',           en: 'Resource',          fr: 'Ressource',        de: 'Ressource'},
  'col.regular':             {it: 'Regolari',          en: 'Regular',           fr: 'Régulier',         de: 'Regulär'},
  'col.overtime':            {it: 'Straord.',          en: 'Overtime',          fr: 'Suppl.',           de: 'Überstd.'},
  'col.pending':             {it: 'Pending',           en: 'Pending',           fr: 'En attente',       de: 'Ausstehend'},
  'col.night':               {it: 'Notturno',          en: 'Night',             fr: 'Nuit',             de: 'Nacht'},
  'col.holiday':             {it: 'Festivo/Dom.',      en: 'Holiday/Sun',       fr: 'Férié/Dim',        de: 'Feiertag/So'},
  'col.equiv':               {it: 'Equiv.',            en: 'Equiv.',            fr: 'Équiv.',           de: 'Äquiv.'},
  'col.cost_estimated':      {it: 'Costo stimato',     en: 'Est. cost',         fr: 'Coût estimé',      de: 'Gesch. Kosten'},
  'col.hours':               {it: 'Ore',               en: 'Hours',             fr: 'Heures',           de: 'Stunden'},
  'col.hours_linear':        {it: 'Ore lineari',       en: 'Linear hours',      fr: 'Heures linéaires', de: 'Linear-Stunden'},
  'col.hours_weighted':      {it: 'Ore pesate',        en: 'Weighted hours',    fr: 'Heures pondérées', de: 'Gewichtete Std.'},
  'col.kind_distribution':   {it: 'Distribuzione per kind', en: 'Kind distribution', fr: 'Distribution par type', de: 'Verteilung nach Art'},
  'col.start_time':          {it: 'Inizio',            en: 'Start',             fr: 'Début',            de: 'Beginn'},
  'col.end_time':            {it: 'Fine',              en: 'End',               fr: 'End',              de: 'Ende'},
  'col.breakdown':           {it: 'Breakdown',         en: 'Breakdown',         fr: 'Détail',           de: 'Aufschlüsselung'},
  'col.job_note':            {it: 'Job / Note',        en: 'Job / Notes',       fr: 'Job / Notes',      de: 'Job / Notizen'},
  'col.motivation':          {it: 'Motivazione',       en: 'Reason',            fr: 'Motif',            de: 'Begründung'},
  'col.delta_quote':         {it: 'Δ vs Quote',        en: 'Δ vs Quote',        fr: 'Δ vs Devis',       de: 'Δ vs Angebot'},
  'col.slice_linked':        {it: 'Slice-linked',      en: 'Slice-linked',      fr: 'Lié à slice',      de: 'Slice-verknüpft'},
  'col.admin':               {it: 'Admin',             en: 'Admin',             fr: 'Admin',            de: 'Admin'},
  'col.proposed':            {it: 'Proposto',          en: 'Proposed',          fr: 'Proposé',          de: 'Vorgeschlagen'},
  'col.approved':            {it: 'Approvato',         en: 'Approved',          fr: 'Approuvé',         de: 'Genehmigt'},
  'col.lost':                {it: 'Perso',             en: 'Lost',              fr: 'Perdu',            de: 'Verloren'},
  'col.invoice':             {it: 'Fattura',           en: 'Invoice',           fr: 'Facture',          de: 'Rechnung'},
  'col.accrued':             {it: 'Maturato',          en: 'Accrued',           fr: 'Couru',            de: 'Aufgelaufen'},
  'col.estimated':           {it: 'Stimato',           en: 'Estimated',         fr: 'Estimé',           de: 'Geschätzt'},
  'col.over_under':          {it: 'Over/Under',        en: 'Over/Under',        fr: 'Sur/Sous',         de: 'Über/Unter'},
  'col.real_margin':         {it: 'Marg. reale',       en: 'Real margin',       fr: 'Marge réelle',     de: 'Echte Marge'},
  'col.section':             {it: 'Sez.',              en: 'Section',           fr: 'Section',          de: 'Abschnitt'},
  'col.qty':                 {it: 'Q.tà',              en: 'Qty',               fr: 'Qté',              de: 'Menge'},
  'col.discount_pct':        {it: 'Sconto %',          en: 'Discount %',        fr: 'Remise %',         de: 'Rabatt %'},
  'col.match_pricelist':     {it: 'Match listino',     en: 'Pricelist match',   fr: 'Corresp. tarifs',  de: 'Preisliste-Treffer'},
  'col.qty_hint':            {it: 'Qty hint',          en: 'Qty hint',          fr: 'Indice qté',       de: 'Mengenhinweis'},
  'col.confidence':          {it: 'Conf.',             en: 'Conf.',             fr: 'Conf.',            de: 'Konf.'},
  'col.unit_price':          {it: 'Prezzo unit.',      en: 'Unit price',        fr: 'Prix unit.',       de: 'Stückpreis'},
  'col.year_a':              {it: 'Anno A',            en: 'Year A',            fr: 'Année A',          de: 'Jahr A'},
  'col.year_b':              {it: 'Anno B',            en: 'Year B',            fr: 'Année B',          de: 'Jahr B'},
  'col.delta_cashed':        {it: 'Δ Incassato',       en: 'Δ Cashed',          fr: 'Δ Encaissé',       de: 'Δ Eingenommen'},
  'col.delta_pct':           {it: '% Δ',               en: '% Δ',               fr: '% Δ',              de: '% Δ'},
  'col.forecast_a':          {it: 'Forecast pesato A', en: 'Weighted forecast A', fr: 'Prévision pondérée A', de: 'Gewichtete Prognose A'},
  'col.forecast_b':          {it: 'Forecast B',        en: 'Forecast B',        fr: 'Prévision B',      de: 'Prognose B'},
  'col.net_cash_a':          {it: 'Cassa netta A',     en: 'Net cash A',        fr: 'Trésor. nette A',  de: 'Netto-Kasse A'},
  'col.net_cash_b':          {it: 'Cassa netta B',     en: 'Net cash B',        fr: 'Trésor. nette B',  de: 'Netto-Kasse B'},
  'col.metric':              {it: 'Metrica',           en: 'Metric',            fr: 'Métrique',         de: 'Metrik'},
  'col.ytd':                 {it: 'YTD',               en: 'YTD',               fr: 'Cumul ann.',       de: 'YTD'},
  'col.linear_full_year':    {it: 'Linear full-year',  en: 'Linear full-year',  fr: 'Linéaire ann. comp.', de: 'Linear Gesamtjahr'},
  'col.realistic_full_year': {it: 'Realistic full-year', en: 'Realistic full-year', fr: 'Réaliste ann. comp.', de: 'Realistisch Gesamtjahr'},
  'col.sent':                {it: 'Sent',              en: 'Sent',              fr: 'Envoyé',           de: 'Gesendet'},
  'col.rejected':            {it: 'Rejected',          en: 'Rejected',          fr: 'Rejeté',           de: 'Abgelehnt'},
  'col.forecast':            {it: 'Forecast',          en: 'Forecast',          fr: 'Prévision',        de: 'Prognose'},
  'col.cash_projected':      {it: 'Cassa proiettata',  en: 'Projected cash',    fr: 'Trésorerie proj.', de: 'Geplante Kasse'},
  'col.path_rel':            {it: 'Path relativo',     en: 'Relative path',     fr: 'Chemin relatif',   de: 'Relativer Pfad'},
  'col.mime':                {it: 'MIME',              en: 'MIME',              fr: 'MIME',             de: 'MIME'},
  'col.over':                {it: 'Over',              en: 'Over',              fr: 'Dépass.',          de: 'Über'},
  'col.real_cost':           {it: 'Costo reale',       en: 'Real cost',         fr: 'Coût réel',        de: 'Echte Kosten'},
  'col.forecast_future':     {it: 'Stim. futuro',      en: 'Forecast',          fr: 'Prévu',            de: 'Prognose'},
  'col.invoiced_short':      {it: 'Fatt.',             en: 'Inv.',              fr: 'Fact.',            de: 'Rg.'},
  'col.preview_next':        {it: 'Anteprima next',    en: 'Next preview',      fr: 'Aperçu suivant',   de: 'Vorschau nächste'},
  'col.prefix':              {it: 'Prefisso',          en: 'Prefix',            fr: 'Préfixe',          de: 'Präfix'},
  'col.counter':              {it: 'Counter',          en: 'Counter',           fr: 'Compteur',         de: 'Zähler'},
  'col.pad':                 {it: 'Pad',               en: 'Pad',               fr: 'Pad',              de: 'Pad'},
  'col.detected':            {it: 'Rilevata',          en: 'Detected',          fr: 'Détectée',         de: 'Erkannt'},
  'col.ai':                  {it: 'AI',                en: 'AI',                fr: 'IA',               de: 'KI'},
  'quotes.col.project_title':{it: 'Progetto / Titolo quote', en: 'Project / Quote title', fr: 'Projet / Titre devis', de: 'Projekt / Angebotstitel'},
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
