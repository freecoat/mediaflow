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
  'nav.storage':             {it: 'Storage',           en: 'Storage',           fr: 'Stockage',         de: 'Speicher'},
  'nav.kdm':                 {it: 'KDM/DKDM',          en: 'KDM/DKDM',          fr: 'KDM/DKDM',         de: 'KDM/DKDM',         es: 'KDM/DKDM'},
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

  // ── Time picker (quadrante analogico) ─────────────
  'tp.hour':                 {it: 'Ore',               en: 'Hours',             fr: 'Heures',           de: 'Stunden',          es: 'Horas'},
  'tp.minute':               {it: 'Minuti',            en: 'Minutes',           fr: 'Minutes',          de: 'Minuten',          es: 'Minutos'},
  'tp.quick':                {it: 'Rapidi',            en: 'Quick',             fr: 'Rapides',          de: 'Schnell',          es: 'Rápidos'},
  'tp.now':                  {it: 'Adesso',            en: 'Now',               fr: 'Maintenant',       de: 'Jetzt',            es: 'Ahora'},

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
  'projects.status.prospect':  {it: 'Prospect',         en: 'Prospect',          fr: 'Prospect',         de: 'Interessent',      es: 'Prospecto'},
  'projects.status.quoting':   {it: 'In quotazione',   en: 'Quoting',           fr: 'En devis',         de: 'Angebot',          es: 'Cotizando'},
  'projects.status.active':    {it: 'Attivo',          en: 'Active',            fr: 'Actif',            de: 'Aktiv',            es: 'Activo'},
  'projects.status.completed': {it: 'Completato',      en: 'Completed',         fr: 'Terminé',          de: 'Abgeschlossen',    es: 'Completado'},
  'projects.status.archived':  {it: 'Archiviato',      en: 'Archived',          fr: 'Archivé',          de: 'Archiviert',       es: 'Archivado'},
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

  // ── α.172.109 — Pagine specifiche (audit round 3) ─────────
  // Settings (configurazione)
  'settings.parse_engine_title':        {it: 'Motore di parsing capitolati',                     en: 'Spec parsing engine',                    fr: 'Moteur d’analyse des cahiers des charges', de: 'Lastenheft-Parsing-Engine',                es: 'Motor de análisis de pliegos'},
  'settings.parse_engine_desc':         {it: 'Quale AI analizza i capitolati di consegna. È indipendente dal provider del copilot: il parser usa sempre il modello più potente, salvo override esplicito qui sotto.', en: 'Which AI analyzes delivery specs. Independent from the copilot provider: the parser always uses the strongest model, unless explicitly overridden below.', fr: 'Quelle IA analyse les cahiers des charges. Indépendant du fournisseur du copilote : l’analyseur utilise toujours le modèle le plus puissant, sauf dérogation explicite ci-dessous.', de: 'Welche KI die Lieferspezifikationen analysiert. Unabhängig vom Copilot-Anbieter: Der Parser nutzt stets das stärkste Modell, sofern unten nicht ausdrücklich überschrieben.', es: 'Qué IA analiza los pliegos de entrega. Independiente del proveedor del copiloto: el analizador siempre usa el modelo más potente, salvo anulación explícita abajo.'},
  'settings.parse_engine_label':        {it: 'Motore:',                                          en: 'Engine:',                                fr: 'Moteur :',                           de: 'Engine:',                                    es: 'Motor:'},
  'settings.parse_engine_auto':         {it: 'Automatico (più potente)',                         en: 'Automatic (strongest)',                  fr: 'Automatique (le plus puissant)',     de: 'Automatisch (stärkstes)',                    es: 'Automático (más potente)'},
  'settings.parse_engine_effective':    {it: 'Modello usato dal parser',                         en: 'Model used by the parser',               fr: 'Modèle utilisé par l’analyseur',     de: 'Vom Parser verwendetes Modell',              es: 'Modelo usado por el analizador'},
  'settings.parse_engine_none':         {it: 'Nessun provider configurato — configura un provider qui sopra.', en: 'No provider configured — set one up above.', fr: 'Aucun fournisseur configuré — configurez-en un ci-dessus.', de: 'Kein Anbieter konfiguriert — oben einen einrichten.', es: 'Ningún proveedor configurado — configura uno arriba.'},
  'settings.parse_engine_saved':        {it: 'Motore di parsing aggiornato',                     en: 'Parsing engine updated',                 fr: 'Moteur d’analyse mis à jour',        de: 'Parsing-Engine aktualisiert',                es: 'Motor de análisis actualizado'},
  'settings.threshold_hours_day':       {it: 'Soglia ore/giorno',                                en: 'Daily hours threshold',                  fr: 'Seuil heures/jour',                  de: 'Schwelle Stunden/Tag',                       es: 'Umbral horas/día'},
  'settings.threshold_hours_week':      {it: 'Soglia ore/settimana',                             en: 'Weekly hours threshold',                 fr: 'Seuil heures/semaine',               de: 'Schwelle Stunden/Woche',                     es: 'Umbral horas/semana'},
  'settings.optional_ccnl_brackets':    {it: '(opzionale, per CCNL con maggiorazioni a fasce)',  en: '(optional, for CBA with bracket surcharges)', fr: '(facultatif, pour CCT à majorations par tranches)', de: '(optional, für Tarifvertrag mit Zuschlagsstufen)', es: '(opcional, para convenio con recargos escalonados)'},
  'settings.vacation_accrued_year_days':{it: 'Ferie maturate / anno (giorni)',                   en: 'Vacation accrued / year (days)',         fr: 'Congés acquis / an (jours)',         de: 'Urlaub erworben / Jahr (Tage)',              es: 'Vacaciones devengadas / año (días)'},
  'settings.rol_accrued_month_hours':   {it: 'ROL maturate / mese (ore)',                        en: 'TOIL accrued / month (hours)',           fr: 'RTT acquis / mois (heures)',         de: 'Freizeitausgleich / Monat (Stunden)',        es: 'Horas compensables / mes'},
  'settings.rol_help':                  {it: 'Default 8h/mese. Riduzione orario di lavoro.',     en: 'Default 8h/month. Working time reduction.', fr: 'Défaut 8h/mois. Réduction temps de travail.', de: 'Standard 8h/Monat. Arbeitszeitverkürzung.', es: 'Por defecto 8h/mes. Reducción horaria.'},
  'settings.permissions_paid_month_hrs':{it: 'Permessi retribuiti / mese (ore)',                 en: 'Paid leave / month (hours)',             fr: 'Congés payés extra / mois (heures)', de: 'Bezahlte Sonderfreistellung / Monat (Stunden)', es: 'Permisos retribuidos / mes (horas)'},
  'settings.permissions_help':          {it: 'Default 8h/mese. Permessi extra (visite mediche, eventi famigliari, ecc).', en: 'Default 8h/month. Extra leave (medical, family events, etc).', fr: 'Défaut 8h/mois. Congés extra (médical, événements familiaux, etc).', de: 'Standard 8h/Monat. Sonderurlaub (Arzt, Familienereignisse usw).', es: 'Por defecto 8h/mes. Permisos extra (médico, familia, etc).'},
  'settings.value_saved':               {it: 'Valore (salvato) *',                               en: 'Value (saved) *',                        fr: 'Valeur (enregistrée) *',             de: 'Wert (gespeichert) *',                       es: 'Valor (guardado) *'},
  'settings.sdi_recipient_code':        {it: 'Codice destinatario SDI proprio (opzionale)',      en: 'Own SDI recipient code (optional)',      fr: 'Code destinataire SDI (facultatif)', de: 'Eigener SDI-Empfängercode (optional)',       es: 'Código destinatario SDI propio (opcional)'},
  'settings.payment_terms_default_days':{it: 'Termini pagamento default (giorni)',               en: 'Default payment terms (days)',           fr: 'Délais de paiement par défaut (jours)', de: 'Standard-Zahlungsziel (Tage)',             es: 'Plazos de pago por defecto (días)'},
  'settings.document_header_optional':  {it: 'Intestazione documento (opzionale)',               en: 'Document header (optional)',             fr: 'En-tête document (facultatif)',      de: 'Dokumentkopf (optional)',                    es: 'Encabezado documento (opcional)'},
  'settings.scope_per_project':         {it: 'scope per-progetto',                               en: 'per-project scope',                      fr: 'portée par projet',                  de: 'projektbezogener Geltungsbereich',           es: 'alcance por proyecto'},
  'settings.soft_deleted_records':      {it: 'Record soft-deleted (clienti, progetti, quote, voci listino).', en: 'Soft-deleted records (clients, projects, quotes, price items).', fr: 'Enregistrements supprimés (clients, projets, devis, articles).', de: 'Soft-gelöschte Datensätze (Kunden, Projekte, Angebote, Preisliste).', es: 'Registros eliminados (clientes, proyectos, cotizaciones, precios).'},
  'settings.aes_password_optional':     {it: '(opzionale) Password per cifratura AES',           en: '(optional) AES encryption password',     fr: '(facultatif) Mot de passe chiffrement AES', de: '(optional) Passwort für AES-Verschlüsselung', es: '(opcional) Contraseña cifrado AES'},

  // Copilot (drawer AI)
  'copilot.placeholder_booking':        {it: 'Crea un booking per … (descrivi job/risorsa/quando)', en: 'Create a booking for … (describe job/resource/when)', fr: 'Créer un booking pour … (décrire job/ressource/quand)', de: 'Booking erstellen für … (Job/Ressource/Wann)', es: 'Crear un booking para … (describe job/recurso/cuándo)'},
  'copilot.placeholder_pricelist':      {it: 'Aggiungi voce listino: color grading 4K HDR, €1500/giorno', en: 'Add price item: color grading 4K HDR, €1500/day', fr: 'Ajouter article: étalonnage 4K HDR, 1500 €/jour', de: 'Preisposten hinzufügen: Color Grading 4K HDR, 1500 €/Tag', es: 'Añadir artículo: color grading 4K HDR, 1500 €/día'},
  'copilot.client_new':                 {it: 'Cliente (nuovo)',           en: 'Client (new)',         fr: 'Client (nouveau)',    de: 'Kunde (neu)',           es: 'Cliente (nuevo)'},
  'copilot.project_new':                {it: 'Progetto (nuovo)',          en: 'Project (new)',        fr: 'Projet (nouveau)',    de: 'Projekt (neu)',         es: 'Proyecto (nuevo)'},
  'copilot.quote_new':                  {it: 'Quote (nuova)',             en: 'Quote (new)',          fr: 'Devis (nouveau)',     de: 'Angebot (neu)',         es: 'Cotización (nueva)'},
  'copilot.quote_edit':                 {it: 'Quote (modifica)',          en: 'Quote (edit)',         fr: 'Devis (modifier)',    de: 'Angebot (bearbeiten)',  es: 'Cotización (editar)'},
  'copilot.resource_new':               {it: 'Risorsa (nuova)',           en: 'Resource (new)',       fr: 'Ressource (nouvelle)',de: 'Ressource (neu)',       es: 'Recurso (nuevo)'},
  'copilot.booking_new':                {it: 'Booking (nuovo)',           en: 'Booking (new)',        fr: 'Booking (nouveau)',   de: 'Booking (neu)',         es: 'Booking (nuevo)'},

  // Quotes (preventivi)
  'quotes.days_after_anchor':           {it: "Giorni dopo l'ancora",      en: 'Days after anchor',    fr: "Jours après l'ancre", de: 'Tage nach Anker',       es: 'Días después del ancla'},
  'quotes.zero_at_anchor':              {it: '0 = subito all\'ancora.',   en: '0 = immediately at anchor.', fr: "0 = immédiatement à l'ancre.", de: '0 = sofort am Anker.', es: '0 = inmediatamente en el ancla.'},
  'quotes.allocation_optional':         {it: 'Allocazione a voci di quote (opzionale)', en: 'Allocation to quote lines (optional)', fr: 'Allocation aux lignes du devis (facultatif)', de: 'Zuweisung zu Angebotszeilen (optional)', es: 'Asignación a líneas de cotización (opcional)'},
  'quotes.hr_short':                    {it: 'hr (ora)',                  en: 'hr (hour)',            fr: 'h (heure)',           de: 'Std (Stunde)',          es: 'h (hora)'},
  'quotes.tooltip_processing':          {it: 'Lavorazione: maturato da ore booking', en: 'Operation: accrued from booking hours', fr: 'Opération: acquis des heures booking', de: 'Arbeitsschritt: aus Booking-Stunden', es: 'Operación: devengado de horas booking'},
  'quotes.tooltip_delivery':            {it: 'Consegna: maturato manuale o auto-fill', en: 'Delivery: manual or auto-fill accrual', fr: 'Livraison: acquis manuel ou auto-fill', de: 'Lieferung: manuell oder Auto-Fill', es: 'Entrega: devengado manual o auto-fill'},
  'quotes.tooltip_currency_change':     {it: 'Cambio valuta: NON converte voci/totali/PDF. I valori restano espressi nella nuova valuta.', en: 'Currency change: does NOT convert lines/totals/PDF. Values remain expressed in the new currency.', fr: 'Changement de devise: ne convertit PAS lignes/totaux/PDF. Les valeurs restent exprimées dans la nouvelle devise.', de: 'Währungswechsel: konvertiert KEINE Zeilen/Summen/PDF. Werte bleiben in der neuen Währung.', es: 'Cambio de divisa: NO convierte líneas/totales/PDF. Los valores siguen expresados en la nueva divisa.'},

  // Finance (fatturazione)
  'finance.tooltip_show_cancelled':     {it: "Mostra fatture in stato 'annullato' (stornate via NC TD04).", en: "Show invoices with 'cancelled' status (reversed via TD04 credit note).", fr: "Afficher factures 'annulées' (extournées par avoir TD04).", de: "Stornierte Rechnungen anzeigen (per TD04-Gutschrift).", es: "Mostrar facturas 'anuladas' (revertidas vía NC TD04)."},
  'finance.extra_post_invoice':         {it: '📅 Extra post-fattura',     en: '📅 Post-invoice extra', fr: '📅 Extra post-facture', de: '📅 Extras nach Rechnung', es: '📅 Extra post-factura'},
  'finance.force_no_project':           {it: '⚠ Forza fattura senza progetto/quotazione', en: '⚠ Force invoice without project/quote', fr: '⚠ Forcer facture sans projet/devis', de: '⚠ Rechnung ohne Projekt/Angebot erzwingen', es: '⚠ Forzar factura sin proyecto/cotización'},

  // Pricelist (listino)
  'pricelist.per_day':                  {it: '€/Giorno',                  en: '€/Day',                fr: '€/Jour',              de: '€/Tag',                 es: '€/Día'},
  'pricelist.per_hour':                 {it: '€/Ora',                     en: '€/Hour',               fr: '€/Heure',             de: '€/Stunde',              es: '€/Hora'},
  'pricelist.preset_builtin':           {it: 'Preset built-in',           en: 'Built-in preset',      fr: 'Préréglage intégré',  de: 'Eingebaute Vorlage',    es: 'Preset integrado'},

  // Resources (risorse — staff)
  'resources.vacation_per_year':        {it: 'Ferie / anno (giorni)',     en: 'Vacation / year (days)', fr: 'Congés / an (jours)', de: 'Urlaub / Jahr (Tage)', es: 'Vacaciones / año (días)'},
  'resources.rol_per_month':            {it: 'ROL / mese (ore)',          en: 'TOIL / month (hours)', fr: 'RTT / mois (heures)', de: 'Freizeitausgleich / Monat (Stunden)', es: 'Horas compensables / mes'},
  'resources.permissions_per_month':    {it: 'Permessi / mese (ore)',     en: 'Leave / month (hours)', fr: 'Congés / mois (heures)', de: 'Sonderurlaub / Monat (Stunden)', es: 'Permisos / mes (horas)'},

  // Planning
  'planning.title_quote_consuntivo':    {it: 'Titolo Quotazione a Consuntivo (opzionale)', en: 'Final Quote Title (optional)', fr: 'Titre devis final (facultatif)', de: 'Titel Schluss-Angebot (optional)', es: 'Título cotización final (opcional)'},
  'planning.hint_done_sync':            {it: 'Marcare "Fatto" triggera il sync col cost report (man-hours). "Non fatto" richiede ricalcolo.', en: 'Marking "Done" triggers cost report sync (man-hours). "Not done" requires recompute.', fr: 'Cocher "Fait" déclenche la synchro du rapport coûts (heures-homme). "Non fait" exige un recalcul.', de: '"Erledigt" markieren synchronisiert den Kostenbericht (Mannstunden). "Nicht erledigt" erfordert Neuberechnung.', es: 'Marcar "Hecho" sincroniza el cost report (horas-hombre). "No hecho" requiere recálculo.'},

  // Project detail
  'project_detail.saved':               {it: 'Salvato.',                  en: 'Saved.',               fr: 'Enregistré.',         de: 'Gespeichert.',          es: 'Guardado.'},

  // Finance reports
  'finance_reports.yoy_comparison':     {it: 'Comparazione anno-su-anno', en: 'Year-over-year comparison', fr: 'Comparaison année sur année', de: 'Jahresvergleich', es: 'Comparación interanual'},

  // Holidays
  'holidays.scope_ccnl_policy':         {it: 'Scope: policy CCNL (opzionale)', en: 'Scope: CBA policy (optional)', fr: 'Portée: politique CCT (facultative)', de: 'Bereich: Tarifvertrag (optional)', es: 'Alcance: política convenio (opcional)'},

  // HR
  'hr.xlsx_help':                       {it: 'XLSX include 2 fogli (Dettaglio + Totali per Risorsa×Mese×Tipo). Range default = anno corrente.', en: 'XLSX includes 2 sheets (Detail + Totals by Resource×Month×Type). Default range = current year.', fr: 'XLSX inclut 2 feuilles (Détail + Totaux par Ressource×Mois×Type). Plage par défaut = année en cours.', de: 'XLSX enthält 2 Blätter (Detail + Summen nach Ressource×Monat×Typ). Standardbereich = laufendes Jahr.', es: 'XLSX incluye 2 hojas (Detalle + Totales por Recurso×Mes×Tipo). Rango por defecto = año actual.'},

  // Overhead (spese aziendali)
  'overhead.useful_life_months':        {it: 'Vita utile (mesi)',         en: 'Useful life (months)', fr: 'Durée utile (mois)',  de: 'Nutzungsdauer (Monate)', es: 'Vida útil (meses)'},

  // Physical assets
  'physical_assets.example_serial':     {it: 'es. WD42-A1B2C3',           en: 'e.g. WD42-A1B2C3',     fr: 'ex. WD42-A1B2C3',     de: 'z.B. WD42-A1B2C3',      es: 'ej. WD42-A1B2C3'},

  // Platform tenants
  'platform_tenants.created':           {it: 'Creato',                    en: 'Created',              fr: 'Créé',                de: 'Erstellt',              es: 'Creado'},

  // Portal project (lato cliente)
  'portal_project.specifications':      {it: 'Specifiche',                en: 'Specifications',       fr: 'Spécifications',      de: 'Spezifikationen',       es: 'Especificaciones'},

  // ── SAL batch (v3.5.0) ──────────────────────────────────────────
  'sal.unit.hours':        {it: 'Ore',        en: 'Hours',      fr: 'Heures',     de: 'Stunden',    es: 'Horas'},
  'sal.unit.budget':       {it: 'Budget (€)', en: 'Budget (€)', fr: 'Budget (€)', de: 'Budget (€)', es: 'Presupuesto (€)'},
  'sal.filter.department': {it: 'Reparto',    en: 'Department', fr: 'Département', de: 'Abteilung',  es: 'Departamento'},
  'sal.filter.category':   {it: 'Tipo lavorazione', en: 'Work type', fr: 'Type de travail', de: 'Arbeitstyp', es: 'Tipo de trabajo'},
  'sal.filter.project':    {it: 'Progetto',   en: 'Project',    fr: 'Projet',     de: 'Projekt',    es: 'Proyecto'},
  'sal.filter.category.hint': {it: 'Filtra i progetti con lavorazioni di questo tipo (non ri-scala le ore).', en: 'Filters projects having this work type (does not rescale hours).', fr: 'Filtre les projets ayant ce type de travail (ne redimensionne pas les heures).', de: 'Filtert Projekte mit diesem Arbeitstyp (skaliert Stunden nicht).', es: 'Filtra proyectos con este tipo de trabajo (no reescala las horas).'},
  'sal.opt.all':           {it: '— tutti —',  en: '— all —',    fr: '— tous —',   de: '— alle —',   es: '— todos —'},
  'sal.col.prev_year':     {it: 'Anno prec.', en: 'Prev. year', fr: 'Année préc.', de: 'Vorjahr',   es: 'Año ant.'},
  'sal.col.next_year':     {it: 'Anno succ.', en: 'Next year',  fr: 'Année suiv.', de: 'Folgejahr', es: 'Año sig.'},
  'sal.col.prev_year.hint':{it: 'Ore lavorate nell\'anno precedente.', en: 'Hours worked in the previous year.', fr: 'Heures travaillées l\'année précédente.', de: 'Im Vorjahr geleistete Stunden.', es: 'Horas trabajadas el año anterior.'},
  'sal.col.next_year.hint':{it: 'Ore pianificate nell\'anno successivo.', en: 'Hours planned in the next year.', fr: 'Heures planifiées l\'année suivante.', de: 'Im Folgejahr geplante Stunden.', es: 'Horas planificadas el año siguiente.'},
  'sal.col.eur_estimate.hint': {it: 'Stima € = ore × tariffa media (quotato/ore quotate).', en: 'Estimate € = hours × blended rate (quoted/quoted hours).', fr: 'Estimation € = heures × tarif moyen (devis/heures devisées).', de: 'Schätzung € = Stunden × Mischsatz (Angebot/angebotene Stunden).', es: 'Estimación € = horas × tarifa media (cotizado/horas cotizadas).'},
  'sal.monte.quoted':      {it: 'Quotate',    en: 'Quoted',     fr: 'Devisé',     de: 'Angeboten',  es: 'Cotizado'},
  'sal.monte.planned':     {it: 'Pianif',     en: 'Planned',    fr: 'Planifié',   de: 'Geplant',    es: 'Planif.'},
  'sal.monte.worked':      {it: 'Lavorate',   en: 'Worked',     fr: 'Travaillé',  de: 'Geleistet',  es: 'Trabajado'},
  'sal.eur.quoted':        {it: 'Quotato',    en: 'Quoted',     fr: 'Devisé',     de: 'Angeboten',  es: 'Cotizado'},
  'sal.eur.accrued':       {it: 'Maturato',   en: 'Accrued',    fr: 'Acquis',     de: 'Aufgelaufen', es: 'Devengado'},
  'sal.legend.title':      {it: 'Legenda',    en: 'Legend',     fr: 'Légende',    de: 'Legende',    es: 'Leyenda'},
  'sal.legend.worked':     {it: 'Lavorato (cumulato)', en: 'Worked (cumulative)', fr: 'Travaillé (cumulé)', de: 'Geleistet (kumuliert)', es: 'Trabajado (acumulado)'},
  'sal.legend.planned':    {it: 'Pianificato (cumulato)', en: 'Planned (cumulative)', fr: 'Planifié (cumulé)', de: 'Geplant (kumuliert)', es: 'Planificado (acumulado)'},
  'sal.legend.overrun':    {it: 'Sforamento (>100%)', en: 'Overrun (>100%)', fr: 'Dépassement (>100%)', de: 'Überschreitung (>100%)', es: 'Exceso (>100%)'},
  'sal.legend.formula':    {it: 'La cella mostra l\'avanzamento cumulativo a fine periodo: ore cumulate ÷ ore quotate.', en: 'The cell shows cumulative progress at end of period: cumulative hours ÷ quoted hours.', fr: 'La cellule montre l\'avancement cumulé en fin de période : heures cumulées ÷ heures devisées.', de: 'Die Zelle zeigt den kumulierten Fortschritt am Periodenende: kumulierte Stunden ÷ angebotene Stunden.', es: 'La celda muestra el avance acumulado al final del período: horas acumuladas ÷ horas cotizadas.'},

  // ── KDM/DKDM (v3.5.0-alpha.172.x — Task 14) ────────────────────────────
  'kdm.title':             {it: 'Richieste KDM/DKDM',       en: 'KDM/DKDM Requests',       fr: 'Demandes KDM/DKDM',       de: 'KDM/DKDM-Anfragen',        es: 'Solicitudes KDM/DKDM'},
  'kdm.new_request':       {it: 'Nuova richiesta',           en: 'New request',              fr: 'Nouvelle demande',        de: 'Neue Anfrage',              es: 'Nueva solicitud'},
  'kdm.tab.requests':      {it: 'Richieste',                 en: 'Requests',                 fr: 'Demandes',                de: 'Anfragen',                  es: 'Solicitudes'},
  'kdm.tab.facilities':    {it: 'Cinema/Server',             en: 'Cinemas/Servers',          fr: 'Cinémas/Serveurs',        de: 'Kinos/Server',              es: 'Cines/Servidores'},
  'kdm.tab.cpl':           {it: 'CPL DCP',                   en: 'DCP CPLs',                 fr: 'CPL DCP',                 de: 'DCP-CPLs',                  es: 'CPL DCP'},
  'kdm.col.status':        {it: 'Stato',                     en: 'Status',                   fr: 'Statut',                  de: 'Status',                    es: 'Estado'},
  'kdm.col.type':          {it: 'Tipo',                      en: 'Type',                     fr: 'Type',                    de: 'Typ',                       es: 'Tipo'},
  'kdm.col.title':         {it: 'Film/CPL',                  en: 'Film/CPL',                 fr: 'Film/CPL',                de: 'Film/CPL',                  es: 'Película/CPL'},
  'kdm.col.window':        {it: 'Finestra',                  en: 'Window',                   fr: 'Fenêtre',                 de: 'Zeitfenster',               es: 'Ventana'},
  'kdm.col.match':         {it: 'Match',                     en: 'Match',                    fr: 'Correspondance',          de: 'Treffer',                   es: 'Coincidencia'},
  'kdm.action.match':      {it: 'Match',                     en: 'Match',                    fr: 'Associer',                de: 'Zuordnen',                  es: 'Asociar'},
  'kdm.candidates':        {it: 'Candidati',                 en: 'Candidates',               fr: 'Candidats',               de: 'Kandidaten',                es: 'Candidatos'},
  'kdm.load_error':        {it: 'Errore caricamento',        en: 'Load error',               fr: 'Erreur de chargement',    de: 'Ladefehler',                es: 'Error de carga'},
  'kdm.empty.facilities':  {it: 'Nessun cinema',             en: 'No cinemas',               fr: 'Aucun cinéma',            de: 'Keine Kinos',               es: 'Sin cines'},
  'kdm.empty.cpl':         {it: 'Nessuna CPL',               en: 'No CPLs',                  fr: 'Aucune CPL',              de: 'Keine CPLs',                es: 'Sin CPL'},
  'kdm.gen_link':          {it: 'Genera link cliente',       en: 'Generate client link',     fr: 'Générer lien client',     de: 'Kundenlink erzeugen',       es: 'Generar enlace cliente'},
  'kdm.link_copied':       {it: 'Link copiato',              en: 'Link copied',              fr: 'Lien copié',              de: 'Link kopiert',              es: 'Enlace copiado'},
  'kdm.prefill_title':     {it: 'Titolo film (opzionale)',   en: 'Film title (optional)',     fr: 'Titre du film (optionnel)', de: 'Filmtitel (optional)',     es: 'Título película (opcional)'},
  'kdm.link_desc':         {it: 'Genera link pubblico per richiesta cliente:', en: 'Generate public link for client request:', fr: 'Générer un lien public pour la demande client :', de: 'Öffentlichen Link für Kundenanfrage erzeugen:', es: 'Generar enlace público para solicitud de cliente:'},
  'kdm.btn.gen_link':      {it: 'Genera link & copia',       en: 'Generate link & copy',     fr: 'Générer lien & copier',   de: 'Link erzeugen & kopieren',  es: 'Generar enlace y copiar'},
  'kdm.btn.show_links':    {it: 'Link attivi',               en: 'Active links',             fr: 'Liens actifs',            de: 'Aktive Links',              es: 'Enlaces activos'},
  'kdm.col.actions':       {it: 'Azioni',                    en: 'Actions',                  fr: 'Actions',                 de: 'Aktionen',                  es: 'Acciones'},
  'kdm.action.transition': {it: 'Stato→',                    en: 'Status→',                  fr: 'Statut→',                 de: 'Status→',                   es: 'Estado→'},
  'kdm.action.delete':     {it: 'Elimina',                   en: 'Delete',                   fr: 'Supprimer',               de: 'Löschen',                   es: 'Eliminar'},
  'kdm.action.edit':       {it: 'Modifica',                  en: 'Edit',                     fr: 'Modifier',                de: 'Bearbeiten',                es: 'Editar'},
  'kdm.empty.requests':    {it: 'Nessuna richiesta KDM.',    en: 'No KDM requests.',         fr: 'Aucune demande KDM.',     de: 'Keine KDM-Anfragen.',       es: 'Sin solicitudes KDM.'},
  'kdm.btn.add_facility':  {it: '+ Cinema',                  en: '+ Cinema',                 fr: '+ Cinéma',                de: '+ Kino',                    es: '+ Cine'},
  'kdm.btn.add_cpl_manual':{it: '+ CPL manuale',             en: '+ Manual CPL',             fr: '+ CPL manuel',            de: '+ Manuelle CPL',            es: '+ CPL manual'},
  'kdm.btn.upload_cpl':    {it: '↑ Upload CPL XML',          en: '↑ Upload CPL XML',         fr: '↑ Importer CPL XML',      de: '↑ CPL-XML hochladen',       es: '↑ Subir CPL XML'},
  'kdm.btn.cancel':        {it: 'Annulla',                   en: 'Cancel',                   fr: 'Annuler',                 de: 'Abbrechen',                 es: 'Cancelar'},
  'kdm.btn.save':          {it: 'Salva',                     en: 'Save',                     fr: 'Enregistrer',             de: 'Speichern',                 es: 'Guardar'},
  'kdm.btn.confirm':       {it: 'Conferma',                  en: 'Confirm',                  fr: 'Confirmer',               de: 'Bestätigen',                es: 'Confirmar'},
  'kdm.col.fac_name':      {it: 'Nome',                      en: 'Name',                     fr: 'Nom',                     de: 'Name',                      es: 'Nombre'},
  'kdm.col.fac_kind':      {it: 'Tipo',                      en: 'Type',                     fr: 'Type',                    de: 'Typ',                       es: 'Tipo'},
  'kdm.col.fac_city':      {it: 'Città',                     en: 'City',                     fr: 'Ville',                   de: 'Stadt',                     es: 'Ciudad'},
  'kdm.col.fac_screens':   {it: 'Sale',                      en: 'Screens',                  fr: 'Salles',                  de: 'Säle',                      es: 'Salas'},
  'kdm.col.cpl_uuid':      {it: 'CPL UUID',                  en: 'CPL UUID',                 fr: 'CPL UUID',                de: 'CPL-UUID',                  es: 'CPL UUID'},
  'kdm.col.cpl_title':     {it: 'Titolo',                    en: 'Title',                    fr: 'Titre',                   de: 'Titel',                     es: 'Título'},
  'kdm.col.cpl_content_kind':{it: 'Tipo',                    en: 'Type',                     fr: 'Type',                    de: 'Typ',                       es: 'Tipo'},
  'kdm.col.cpl_duration':  {it: 'Durata',                    en: 'Duration',                 fr: 'Durée',                   de: 'Dauer',                     es: 'Duración'},
  'kdm.col.cpl_source':    {it: 'Fonte',                     en: 'Source',                   fr: 'Source',                  de: 'Quelle',                    es: 'Fuente'},
  'kdm.modal.new_request': {it: 'Nuova richiesta KDM/DKDM',  en: 'New KDM/DKDM request',     fr: 'Nouvelle demande KDM/DKDM', de: 'Neue KDM/DKDM-Anfrage',   es: 'Nueva solicitud KDM/DKDM'},
  'kdm.modal.transition':  {it: 'Cambia stato richiesta',    en: 'Change request status',    fr: 'Changer le statut',       de: 'Status ändern',             es: 'Cambiar estado'},
  'kdm.modal.facility':    {it: 'Cinema / Server',           en: 'Cinema / Server',          fr: 'Cinéma / Serveur',        de: 'Kino / Server',             es: 'Cine / Servidor'},
  'kdm.modal.cpl_manual':  {it: 'Aggiungi CPL manualmente',  en: 'Add CPL manually',         fr: 'Ajouter CPL manuellement', de: 'CPL manuell hinzufügen',   es: 'Añadir CPL manualmente'},
  'kdm.field.type':        {it: 'Tipo *',                    en: 'Type *',                   fr: 'Type *',                  de: 'Typ *',                     es: 'Tipo *'},
  'kdm.field.delivery':    {it: 'Consegna',                  en: 'Delivery',                 fr: 'Livraison',               de: 'Lieferung',                 es: 'Entrega'},
  'kdm.field.title':       {it: 'Titolo film',               en: 'Film title',               fr: 'Titre du film',           de: 'Filmtitel',                 es: 'Título película'},
  'kdm.field.cpl_uuid':    {it: 'CPL UUID *',                en: 'CPL UUID *',               fr: 'CPL UUID *',              de: 'CPL-UUID *',                es: 'CPL UUID *'},
  'kdm.field.cpl_title':   {it: 'Titolo',                    en: 'Title',                    fr: 'Titre',                   de: 'Titel',                     es: 'Título'},
  'kdm.field.cpl_kind':    {it: 'Content kind',              en: 'Content kind',             fr: 'Type de contenu',         de: 'Inhaltstyp',                es: 'Tipo de contenido'},
  'kdm.field.cpl_duration':{it: 'Durata (frames)',           en: 'Duration (frames)',        fr: 'Durée (images)',          de: 'Dauer (Frames)',            es: 'Duración (fotogramas)'},
  'kdm.field.valid_from':  {it: 'Valido dal',                en: 'Valid from',               fr: 'Valide à partir du',      de: 'Gültig ab',                 es: 'Válido desde'},
  'kdm.field.valid_to':    {it: 'Valido al',                 en: 'Valid until',              fr: 'Valide jusqu’au',         de: 'Gültig bis',                es: 'Válido hasta'},
  'kdm.field.cinema':      {it: 'Cinema/Server destinatario', en: 'Recipient cinema/server', fr: 'Cinéma/serveur destinataire', de: 'Empfänger-Kino/Server', es: 'Cine/servidor destinatario'},
  'kdm.field.notes':       {it: 'Note',                      en: 'Notes',                    fr: 'Notes',                   de: 'Notizen',                   es: 'Notas'},
  'kdm.field.new_status':  {it: 'Nuovo stato',               en: 'New status',               fr: 'Nouveau statut',          de: 'Neuer Status',              es: 'Nuevo estado'},
  'kdm.field.fac_name':    {it: 'Nome *',                    en: 'Name *',                   fr: 'Nom *',                   de: 'Name *',                    es: 'Nombre *'},
  'kdm.field.fac_kind':    {it: 'Tipo',                      en: 'Type',                     fr: 'Type',                    de: 'Typ',                       es: 'Tipo'},
  'kdm.field.fac_city':    {it: 'Città',                     en: 'City',                     fr: 'Ville',                   de: 'Stadt',                     es: 'Ciudad'},
  // ── Step 1 redesign: dettaglio operatore + filtri + azioni ──
  'kdm.action.open':       {it: 'Apri',                      en: 'Open',                     fr: 'Ouvrir',                  de: 'Öffnen',                    es: 'Abrir'},
  'kdm.modal.detail':      {it: 'Dettaglio richiesta',       en: 'Request detail',           fr: 'Détail de la demande',    de: 'Anfragedetails',            es: 'Detalle de solicitud'},
  'kdm.btn.emit':          {it: 'Emetti KDM',                en: 'Issue KDM',                fr: 'Émettre KDM',             de: 'KDM ausstellen',            es: 'Emitir KDM'},
  'kdm.btn.confirm_delivery':{it: 'Conferma consegna',       en: 'Confirm delivery',         fr: 'Confirmer la livraison',  de: 'Lieferung bestätigen',      es: 'Confirmar entrega'},
  'kdm.btn.advanced_status':{it: 'Stato avanzato…',          en: 'Advanced status…',         fr: 'Statut avancé…',          de: 'Erweiterter Status…',       es: 'Estado avanzado…'},
  'kdm.btn.close':         {it: 'Chiudi',                    en: 'Close',                    fr: 'Fermer',                  de: 'Schließen',                 es: 'Cerrar'},
  'kdm.field.cpl_uuid_opt':{it: 'CPL UUID',                  en: 'CPL UUID',                 fr: 'CPL UUID',                de: 'CPL-UUID',                  es: 'CPL UUID'},
  'kdm.fieldset.contacts': {it: 'Contatti',                  en: 'Contacts',                 fr: 'Contacts',                de: 'Kontakte',                  es: 'Contactos'},
  'kdm.field.cinema_name': {it: 'Cinema/Lab — nome',         en: 'Cinema/Lab — name',        fr: 'Cinéma/Lab — nom',        de: 'Kino/Lab — Name',           es: 'Cine/Lab — nombre'},
  'kdm.field.cinema_email':{it: 'Cinema/Lab — email',        en: 'Cinema/Lab — email',       fr: 'Cinéma/Lab — e-mail',     de: 'Kino/Lab — E-Mail',         es: 'Cine/Lab — email'},
  'kdm.field.prod_name':   {it: 'Produzione — referente',    en: 'Production — contact',     fr: 'Production — référent',   de: 'Produktion — Ansprechpartner', es: 'Producción — contacto'},
  'kdm.field.prod_email':  {it: 'Produzione — email',        en: 'Production — email',       fr: 'Production — e-mail',     de: 'Produktion — E-Mail',       es: 'Producción — email'},
  'kdm.field.lab_email':   {it: 'Lab email',                 en: 'Lab email',                fr: 'E-mail labo',             de: 'Lab-E-Mail',                es: 'Email del lab'},
  'kdm.detail.timeline':   {it: 'Cronologia',                en: 'Timeline',                 fr: 'Chronologie',             de: 'Verlauf',                   es: 'Cronología'},
  'kdm.detail.no_events':  {it: 'Nessun evento.',            en: 'No events.',               fr: 'Aucun événement.',        de: 'Keine Ereignisse.',         es: 'Sin eventos.'},
  'kdm.detail.no_cpl':     {it: 'Nessun DCP agganciato',     en: 'No DCP linked',            fr: 'Aucun DCP lié',           de: 'Kein DCP verknüpft',        es: 'Sin DCP vinculado'},
  'kdm.detail.has_cert':   {it: 'Certificato cliente presente', en: 'Client certificate present', fr: 'Certificat client présent', de: 'Kundenzertifikat vorhanden', es: 'Certificado de cliente presente'},
  'kdm.detail.from_link':  {it: 'Da link pubblico',          en: 'From public link',         fr: 'Depuis lien public',      de: 'Über öffentlichen Link',    es: 'Desde enlace público'},
  'kdm.detail.deliverable_done':{it: 'Deliverable creato',   en: 'Deliverable created',      fr: 'Livrable créé',           de: 'Liefergegenstand erstellt', es: 'Entregable creado'},
  'kdm.filter.search':     {it: 'Cerca',                     en: 'Search',                   fr: 'Rechercher',              de: 'Suchen',                    es: 'Buscar'},
  'kdm.filter.search_ph':  {it: 'titolo, CPL…',              en: 'title, CPL…',              fr: 'titre, CPL…',             de: 'Titel, CPL…',               es: 'título, CPL…'},
  'kdm.filter.all':        {it: 'Tutti',                     en: 'All',                      fr: 'Tous',                    de: 'Alle',                      es: 'Todos'},
  'kdm.empty.filtered':    {it: 'Nessun risultato per i filtri.', en: 'No results for filters.', fr: 'Aucun résultat pour les filtres.', de: 'Keine Treffer für Filter.', es: 'Sin resultados para los filtros.'},
  'kdm.toast.saved':       {it: 'Modifiche salvate',         en: 'Changes saved',            fr: 'Modifications enregistrées', de: 'Änderungen gespeichert',  es: 'Cambios guardados'},
  'kdm.toast.emitted':     {it: 'KDM emessa',                en: 'KDM issued',               fr: 'KDM émise',               de: 'KDM ausgestellt',           es: 'KDM emitida'},
  'kdm.toast.confirmed':   {it: 'Consegna confermata',       en: 'Delivery confirmed',       fr: 'Livraison confirmée',     de: 'Lieferung bestätigt',       es: 'Entrega confirmada'},
  'kdm.confirm.emit':      {it: "Registrare l'emissione della KDM? Verrà creato il deliverable.", en: 'Record KDM issuance? The deliverable will be created.', fr: "Enregistrer l'émission de la KDM ? Le livrable sera créé.", de: 'KDM-Ausstellung erfassen? Der Liefergegenstand wird erstellt.', es: '¿Registrar la emisión de la KDM? Se creará el entregable.'},
  'kdm.confirm.delivery':  {it: "Confermare l'avvenuta consegna?", en: 'Confirm that delivery happened?', fr: 'Confirmer que la livraison a eu lieu ?', de: 'Erfolgte Lieferung bestätigen?', es: '¿Confirmar que la entrega se realizó?'},
  // ── Step 1 redesign: form pubblico richiesta (client-facing) ──
  'kdm.pub.heading':       {it: '🔑 Richiesta chiavi DCP (KDM / DKDM)', en: '🔑 DCP key request (KDM / DKDM)', fr: '🔑 Demande de clés DCP (KDM / DKDM)', de: '🔑 DCP-Schlüsselanfrage (KDM / DKDM)', es: '🔑 Solicitud de claves DCP (KDM / DKDM)'},
  'kdm.pub.project':       {it: 'Progetto:',                 en: 'Project:',                 fr: 'Projet :',                de: 'Projekt:',                  es: 'Proyecto:'},
  'kdm.pub.submitted':     {it: '✅ Richiesta inviata. Il team finishing è stato avvisato e riceverai conferma a breve.', en: '✅ Request sent. The finishing team has been notified and you will receive confirmation shortly.', fr: '✅ Demande envoyée. L’équipe finishing a été prévenue et vous recevrez une confirmation sous peu.', de: '✅ Anfrage gesendet. Das Finishing-Team wurde benachrichtigt und Sie erhalten in Kürze eine Bestätigung.', es: '✅ Solicitud enviada. El equipo de finishing ha sido avisado y recibirás confirmación en breve.'},
  'kdm.pub.type':          {it: 'Tipo chiave',               en: 'Key type',                 fr: 'Type de clé',             de: 'Schlüsseltyp',              es: 'Tipo de clave'},
  'kdm.pub.type_kdm':      {it: 'KDM (cinema)',              en: 'KDM (cinema)',             fr: 'KDM (cinéma)',            de: 'KDM (Kino)',                es: 'KDM (cine)'},
  'kdm.pub.type_dkdm':     {it: 'DKDM (distributore)',       en: 'DKDM (distributor)',       fr: 'DKDM (distributeur)',     de: 'DKDM (Verleih)',            es: 'DKDM (distribuidor)'},
  'kdm.pub.title':         {it: 'Titolo film',               en: 'Film title',               fr: 'Titre du film',           de: 'Filmtitel',                 es: 'Título de la película'},
  'kdm.pub.cpl':           {it: 'CPL UUID del DCP',          en: 'DCP CPL UUID',             fr: 'CPL UUID du DCP',         de: 'CPL-UUID des DCP',          es: 'CPL UUID del DCP'},
  'kdm.pub.cpl_hint':      {it: '(opzionale — aiuta il matching automatico)', en: '(optional — helps automatic matching)', fr: '(optionnel — aide à l’association automatique)', de: '(optional — hilft beim automatischen Abgleich)', es: '(opcional — ayuda al emparejamiento automático)'},
  'kdm.pub.valid_from':    {it: 'Sblocco DA (data+ora)',     en: 'Unlock FROM (date+time)',  fr: 'Déblocage À PARTIR DE (date+heure)', de: 'Freischaltung AB (Datum+Zeit)', es: 'Desbloqueo DESDE (fecha+hora)'},
  'kdm.pub.valid_to':      {it: 'Sblocco A (data+ora)',      en: 'Unlock TO (date+time)',    fr: 'Déblocage JUSQU’À (date+heure)', de: 'Freischaltung BIS (Datum+Zeit)', es: 'Desbloqueo HASTA (fecha+hora)'},
  'kdm.pub.cert':          {it: 'Certificato server (.pem)', en: 'Server certificate (.pem)', fr: 'Certificat serveur (.pem)', de: 'Server-Zertifikat (.pem)', es: 'Certificado del servidor (.pem)'},
  'kdm.pub.optional':      {it: '(opzionale)',               en: '(optional)',               fr: '(optionnel)',             de: '(optional)',                es: '(opcional)'},
  'kdm.pub.contacts':      {it: 'Contatti',                  en: 'Contacts',                 fr: 'Contacts',                de: 'Kontakte',                  es: 'Contactos'},
  'kdm.pub.cinema_name':   {it: 'Cinema / Lab destinatario — nome', en: 'Recipient cinema / lab — name', fr: 'Cinéma / labo destinataire — nom', de: 'Empfänger-Kino / Lab — Name', es: 'Cine / lab destinatario — nombre'},
  'kdm.pub.cinema_email':  {it: 'Cinema / Lab destinatario — email', en: 'Recipient cinema / lab — email', fr: 'Cinéma / labo destinataire — e-mail', de: 'Empfänger-Kino / Lab — E-Mail', es: 'Cine / lab destinatario — email'},
  'kdm.pub.lab_email':     {it: 'Lab email',                 en: 'Lab email',                fr: 'E-mail labo',             de: 'Lab-E-Mail',                es: 'Email del lab'},
  'kdm.pub.prod_name':     {it: 'Produzione — nome referente', en: 'Production — contact name', fr: 'Production — nom du référent', de: 'Produktion — Name Ansprechpartner', es: 'Producción — nombre del contacto'},
  'kdm.pub.prod_email':    {it: 'Produzione — email referente', en: 'Production — contact email', fr: 'Production — e-mail du référent', de: 'Produktion — E-Mail Ansprechpartner', es: 'Producción — email del contacto'},
  'kdm.pub.notes':         {it: 'Note',                      en: 'Notes',                    fr: 'Notes',                   de: 'Notizen',                   es: 'Notas'},
  'kdm.pub.submit':        {it: 'Invia richiesta',           en: 'Send request',             fr: 'Envoyer la demande',      de: 'Anfrage senden',            es: 'Enviar solicitud'},
  // ── Step 2: credenziali (certificati multipli + serial) ──
  'kdm.cert.title':        {it: 'Certificati / Serial',      en: 'Certificates / Serials',   fr: 'Certificats / Serials',   de: 'Zertifikate / Seriennummern', es: 'Certificados / Seriales'},
  'kdm.cert.kind_cert':    {it: 'Certificato',               en: 'Certificate',              fr: 'Certificat',              de: 'Zertifikat',                es: 'Certificado'},
  'kdm.cert.kind_serial':  {it: 'Serial number',             en: 'Serial number',            fr: 'Numéro de série',         de: 'Seriennummer',              es: 'Número de serie'},
  'kdm.cert.label_ph':     {it: 'etichetta (opz.)',          en: 'label (opt.)',             fr: 'libellé (opt.)',          de: 'Bezeichnung (opt.)',        es: 'etiqueta (opc.)'},
  'kdm.cert.add':          {it: '+ Aggiungi',                en: '+ Add',                    fr: '+ Ajouter',               de: '+ Hinzufügen',              es: '+ Añadir'},
  'kdm.cert.serial_ph':    {it: 'serial number',             en: 'serial number',            fr: 'numéro de série',         de: 'Seriennummer',              es: 'número de serie'},
  'kdm.cert.none':         {it: 'Nessuna credenziale.',      en: 'No credentials.',          fr: 'Aucune référence.',       de: 'Keine Zugangsdaten.',       es: 'Sin credenciales.'},
  'kdm.cert.pem':          {it: 'PEM',                       en: 'PEM',                      fr: 'PEM',                     de: 'PEM',                       es: 'PEM'},
  'kdm.cert.expires':      {it: 'scade',                     en: 'expires',                  fr: 'expire',                  de: 'läuft ab',                  es: 'caduca'},
  'kdm.cert.need_pem':     {it: 'Incolla il certificato PEM', en: 'Paste the PEM certificate', fr: 'Collez le certificat PEM', de: 'PEM-Zertifikat einfügen',  es: 'Pega el certificado PEM'},
  'kdm.cert.need_serial':  {it: 'Inserisci il serial number', en: 'Enter the serial number', fr: 'Saisissez le numéro de série', de: 'Seriennummer eingeben',  es: 'Introduce el número de serie'},
  'kdm.cert.added':        {it: 'Credenziale aggiunta',      en: 'Credential added',         fr: 'Référence ajoutée',       de: 'Zugangsdaten hinzugefügt',  es: 'Credencial añadida'},
  'kdm.cert.removed':      {it: 'Credenziale rimossa',       en: 'Credential removed',       fr: 'Référence supprimée',     de: 'Zugangsdaten entfernt',     es: 'Credencial eliminada'},
  'kdm.cert.confirm_del':  {it: 'Rimuovere questa credenziale?', en: 'Remove this credential?', fr: 'Supprimer cette référence ?', de: 'Diese Zugangsdaten entfernen?', es: '¿Eliminar esta credencial?'},
  'kdm.cert.required_warn':{it: 'Nessuna credenziale: impossibile emettere', en: 'No credentials: cannot issue', fr: 'Aucune référence : émission impossible', de: 'Keine Zugangsdaten: Ausstellung nicht möglich', es: 'Sin credenciales: no se puede emitir'},
  'kdm.pub.credentials':   {it: 'Certificati / Serial',      en: 'Certificates / Serials',   fr: 'Certificats / Serials',   de: 'Zertifikate / Seriennummern', es: 'Certificados / Seriales'},
  'kdm.pub.credentials_hint':{it: 'Fornisci i certificati server (.pem) e/o i serial number. Almeno uno è necessario per emettere le chiavi.', en: 'Provide server certificates (.pem) and/or serial numbers. At least one is required to issue the keys.', fr: 'Fournissez les certificats serveur (.pem) et/ou les numéros de série. Au moins un est requis pour émettre les clés.', de: 'Server-Zertifikate (.pem) und/oder Seriennummern angeben. Mindestens eines ist zum Ausstellen der Schlüssel erforderlich.', es: 'Proporciona certificados de servidor (.pem) y/o números de serie. Al menos uno es necesario para emitir las claves.'},
  'kdm.pub.cert_multi':    {it: '(uno o più)',               en: '(one or more)',            fr: '(un ou plusieurs)',       de: '(eines oder mehrere)',      es: '(uno o más)'},
  'kdm.pub.serials':       {it: 'Serial number',             en: 'Serial numbers',           fr: 'Numéros de série',        de: 'Seriennummern',             es: 'Números de serie'},
  'kdm.pub.serials_hint':  {it: '(uno per riga)',            en: '(one per line)',           fr: '(un par ligne)',          de: '(eines pro Zeile)',         es: '(uno por línea)'},
  // ── Batch: link attributi + archivio + bulk + CPL filtri/collegate ──
  'kdm.tab.archive':       {it: 'Archivio',                  en: 'Archive',                  fr: 'Archives',                de: 'Archiv',                    es: 'Archivo'},
  'kdm.archive.desc':      {it: 'Richieste completate (KDM emessa). Non cancellabili.', en: 'Completed requests (KDM issued). Not deletable.', fr: 'Demandes terminées (KDM émise). Non supprimables.', de: 'Abgeschlossene Anfragen (KDM ausgestellt). Nicht löschbar.', es: 'Solicitudes completadas (KDM emitida). No eliminables.'},
  'kdm.archive.empty':     {it: 'Archivio vuoto.',           en: 'Archive empty.',           fr: 'Archives vides.',         de: 'Archiv leer.',              es: 'Archivo vacío.'},
  'kdm.bulk.selected':     {it: 'selezionate',               en: 'selected',                 fr: 'sélectionnées',           de: 'ausgewählt',                es: 'seleccionadas'},
  'kdm.bulk.delete':       {it: 'Elimina selezionate',       en: 'Delete selected',          fr: 'Supprimer la sélection',  de: 'Auswahl löschen',           es: 'Eliminar seleccionadas'},
  'kdm.bulk.confirm_del':  {it: 'Eliminare {n} richieste? Le completate vengono saltate.', en: 'Delete {n} requests? Completed ones are skipped.', fr: 'Supprimer {n} demandes ? Les terminées sont ignorées.', de: '{n} Anfragen löschen? Abgeschlossene werden übersprungen.', es: '¿Eliminar {n} solicitudes? Las completadas se omiten.'},
  'kdm.bulk.done':         {it: 'Eliminate {d}, saltate {s}', en: 'Deleted {d}, skipped {s}', fr: 'Supprimées {d}, ignorées {s}', de: '{d} gelöscht, {s} übersprungen', es: 'Eliminadas {d}, omitidas {s}'},
  'kdm.link.name':         {it: 'Nome link',                 en: 'Link name',                fr: 'Nom du lien',             de: 'Link-Name',                 es: 'Nombre del enlace'},
  'kdm.link.name_ph':      {it: 'es. Arcadia Roma',          en: 'e.g. Arcadia Roma',        fr: 'ex. Arcadia Roma',        de: 'z. B. Arcadia Roma',        es: 'ej. Arcadia Roma'},
  'kdm.link.project':      {it: 'Progetto',                  en: 'Project',                  fr: 'Projet',                  de: 'Projekt',                   es: 'Proyecto'},
  'kdm.link.no_project':   {it: '— nessuno —',               en: '— none —',                 fr: '— aucun —',               de: '— keins —',                 es: '— ninguno —'},
  'kdm.link.duration':     {it: 'Durata',                    en: 'Duration',                 fr: 'Durée',                   de: 'Dauer',                     es: 'Duración'},
  'kdm.link.no_expiry':    {it: 'Senza scadenza',            en: 'No expiry',                fr: 'Sans expiration',         de: 'Ohne Ablauf',               es: 'Sin caducidad'},
  'kdm.link.prefill_title':{it: 'Titolo pre-compilato',      en: 'Prefilled title',          fr: 'Titre pré-rempli',        de: 'Vorausgefüllter Titel',     es: 'Título precargado'},
  'kdm.link.none':         {it: 'Nessun link attivo.',       en: 'No active links.',         fr: 'Aucun lien actif.',       de: 'Keine aktiven Links.',      es: 'Sin enlaces activos.'},
  'kdm.link.unnamed':      {it: '(senza nome)',              en: '(unnamed)',                fr: '(sans nom)',              de: '(ohne Namen)',              es: '(sin nombre)'},
  'kdm.link.expired':      {it: '(scaduto)',                 en: '(expired)',                fr: '(expiré)',                de: '(abgelaufen)',              es: '(caducado)'},
  'kdm.link.copy':         {it: 'Copia',                     en: 'Copy',                     fr: 'Copier',                  de: 'Kopieren',                  es: 'Copiar'},
  'kdm.link.revoke':       {it: 'Revoca',                    en: 'Revoke',                   fr: 'Révoquer',                de: 'Widerrufen',                es: 'Revocar'},
  'kdm.link.revoke_selected':{it: 'Revoca selezionati',      en: 'Revoke selected',          fr: 'Révoquer la sélection',   de: 'Auswahl widerrufen',        es: 'Revocar seleccionados'},
  'kdm.link.none_selected':{it: 'Nessun link selezionato',   en: 'No link selected',         fr: 'Aucun lien sélectionné',  de: 'Kein Link ausgewählt',      es: 'Ningún enlace seleccionado'},
  'kdm.link.confirm_revoke':{it: 'Revocare {n} link?',       en: 'Revoke {n} links?',        fr: 'Révoquer {n} liens ?',    de: '{n} Links widerrufen?',     es: '¿Revocar {n} enlaces?'},
  'kdm.link.revoked_n':    {it: 'Revocati {n} link',         en: '{n} links revoked',        fr: '{n} liens révoqués',      de: '{n} Links widerrufen',      es: '{n} enlaces revocados'},
  'kdm.cpl.search_ph':     {it: 'titolo o UUID…',            en: 'title or UUID…',           fr: 'titre ou UUID…',          de: 'Titel oder UUID…',          es: 'título o UUID…'},
  'kdm.cpl.linked_requests':{it: 'Richieste collegate',      en: 'Linked requests',          fr: 'Demandes liées',          de: 'Verknüpfte Anfragen',       es: 'Solicitudes vinculadas'},
  'kdm.cpl.no_requests':   {it: 'Nessuna richiesta collegata.', en: 'No linked requests.',   fr: 'Aucune demande liée.',    de: 'Keine verknüpften Anfragen.', es: 'Sin solicitudes vinculadas.'},
  'dt.reparse':              {it: 'Ri-analizza',               en: 'Re-analyze',               fr: 'Ré-analyser',             de: 'Neu analysieren',           es: 'Re-analizar'},
  'dt.parse_warning.title':  {it: '⚠️ Risultato potenzialmente inaffidabile', en: '⚠️ Result may be unreliable', fr: '⚠️ Résultat peu fiable', de: '⚠️ Ergebnis evtl. unzuverlässig', es: '⚠️ Resultado poco fiable'},
  'dt.parse_warning.weak_model_large_doc': {it: 'Modello AI debole per un documento grande. Configura/attiva Claude Sonnet in Impostazioni → AI e ri-analizza.', en: 'Weak AI model for a large document. Configure/activate Claude Sonnet in Settings → AI and re-analyze.', fr: 'Modèle IA faible pour un grand document. Configurez/activez Claude Sonnet dans Paramètres → IA puis ré-analysez.', de: 'Schwaches KI-Modell für ein großes Dokument. Claude Sonnet in Einstellungen → KI aktivieren und neu analysieren.', es: 'Modelo de IA débil para un documento grande. Configura/activa Claude Sonnet en Ajustes → IA y vuelve a analizar.'},
  'dt.parse_warning.low_confidence': {it: 'Confidenza AI bassa: verifica i campi estratti.', en: 'Low AI confidence: verify the extracted fields.', fr: 'Faible confiance IA : vérifiez les champs extraits.', de: 'Geringe KI-Konfidenz: extrahierte Felder prüfen.', es: 'Confianza de IA baja: verifica los campos extraídos.'},
  'dt.parse_warning.truncated': {it: 'Documento troppo lungo: parte finale non analizzata.', en: 'Document too long: final part not analyzed.', fr: 'Document trop long : partie finale non analysée.', de: 'Dokument zu lang: letzter Teil nicht analysiert.', es: 'Documento demasiado largo: la parte final no se analizó.'},
  'dt.parse_engine':           {it: 'Motore di parsing', en: 'Parsing engine', fr: 'Moteur d’analyse', de: 'Parsing-Engine', es: 'Motor de análisis'},
  'dt.parse_engine_hint':      {it: 'Modello AI che analizza il capitolato. "Automatico" usa il più potente configurato.', en: 'AI model that analyzes the spec. "Automatic" uses the strongest configured.', fr: 'Modèle IA qui analyse le cahier des charges. « Automatique » utilise le plus puissant configuré.', de: 'KI-Modell zur Analyse des Lastenhefts. „Automatisch“ nutzt das stärkste konfigurierte.', es: 'Modelo de IA que analiza el pliego. "Automático" usa el más potente configurado.'},
  'dt.parse_engine_auto':      {it: 'Automatico (più potente)', en: 'Automatic (strongest)', fr: 'Automatique (le plus puissant)', de: 'Automatisch (stärkstes)', es: 'Automático (más potente)'},
  'dt.parse_engine_none':      {it: 'Nessun provider configurato', en: 'No provider configured', fr: 'Aucun fournisseur configuré', de: 'Kein Anbieter konfiguriert', es: 'Ningún proveedor configurado'},
  'dt.parsed_with':            {it: 'Analizzato con', en: 'Analyzed with', fr: 'Analysé avec', de: 'Analysiert mit', es: 'Analizado con'},
  'dt.tier_strong':            {it: 'forte', en: 'strong', fr: 'fort', de: 'stark', es: 'fuerte'},
  'dt.tier_medium':            {it: 'medio', en: 'medium', fr: 'moyen', de: 'mittel', es: 'medio'},
  'dt.tier_weak':              {it: 'debole', en: 'weak', fr: 'faible', de: 'schwach', es: 'débil'},
  'dt.extract_items_ai':       {it: 'Estrai items via AI', en: 'Extract items via AI', fr: 'Extraire les éléments via IA', de: 'Elemente per KI extrahieren', es: 'Extraer ítems con IA'},
  'dt.add_item':               {it: 'Aggiungi item', en: 'Add item', fr: 'Ajouter un élément', de: 'Element hinzufügen', es: 'Añadir ítem'},
  'dt.select_item':            {it: 'Seleziona item', en: 'Select item', fr: 'Sélectionner l’élément', de: 'Element auswählen', es: 'Seleccionar ítem'},
  'dt.delete_item':            {it: 'Elimina item', en: 'Delete item', fr: 'Supprimer l’élément', de: 'Element löschen', es: 'Eliminar ítem'},
  'dt.delete_selected':        {it: 'Elimina selezionati', en: 'Delete selected', fr: 'Supprimer la sélection', de: 'Ausgewählte löschen', es: 'Eliminar seleccionados'},
  'dt.clear_selection':        {it: 'Deseleziona', en: 'Clear selection', fr: 'Désélectionner', de: 'Auswahl aufheben', es: 'Quitar selección'},
  'dt.n_selected':             {it: '{n} selezionati', en: '{n} selected', fr: '{n} sélectionnés', de: '{n} ausgewählt', es: '{n} seleccionados'},
  'dt.confirm_delete_item':    {it: 'Eliminare l’item "{name}" e tutte le sue tracce audio?', en: 'Delete item "{name}" and all its audio tracks?', fr: 'Supprimer l’élément « {name} » et toutes ses pistes audio ?', de: 'Element „{name}“ und alle Audiospuren löschen?', es: '¿Eliminar el ítem "{name}" y todas sus pistas de audio?'},
  'dt.confirm_delete_selected':{it: 'Eliminare {n} item selezionati?', en: 'Delete {n} selected items?', fr: 'Supprimer {n} éléments sélectionnés ?', de: '{n} ausgewählte Elemente löschen?', es: '¿Eliminar {n} ítems seleccionados?'},
  'dt.item_deleted':           {it: 'Item eliminato', en: 'Item deleted', fr: 'Élément supprimé', de: 'Element gelöscht', es: 'Ítem eliminado'},
  'dt.n_items_deleted':        {it: '{n} item eliminati', en: '{n} items deleted', fr: '{n} éléments supprimés', de: '{n} Elemente gelöscht', es: '{n} ítems eliminados'},
  'dt.confirm_extract':        {it: 'Avviare l’estrazione items dal capitolato "{name}"?\n\nGira in background (1-2 min). Gli item con nome già esistente sono saltati.', en: 'Start extracting items from spec "{name}"?\n\nRuns in background (1-2 min). Items with existing names are skipped.', fr: 'Lancer l’extraction des éléments du cahier « {name} » ?\n\nS’exécute en arrière-plan (1-2 min). Les éléments déjà existants sont ignorés.', de: 'Extraktion der Elemente aus Lastenheft „{name}“ starten?\n\nLäuft im Hintergrund (1-2 Min.). Bereits vorhandene Elemente werden übersprungen.', es: '¿Iniciar la extracción de ítems del pliego "{name}"?\n\nSe ejecuta en segundo plano (1-2 min). Los ítems con nombre existente se omiten.'},
  'dt.extract_running':        {it: 'Estrazione items in corso in background…', en: 'Item extraction running in background…', fr: 'Extraction des éléments en arrière-plan…', de: 'Element-Extraktion läuft im Hintergrund…', es: 'Extracción de ítems en segundo plano…'},
  'dt.extract_running_short':  {it: 'In corso…', en: 'Running…', fr: 'En cours…', de: 'Läuft…', es: 'En curso…'},
  'dt.extract_done':           {it: 'Estrazione completata', en: 'Extraction complete', fr: 'Extraction terminée', de: 'Extraktion abgeschlossen', es: 'Extracción completada'},
  'dt.extract_failed':         {it: 'Estrazione fallita', en: 'Extraction failed', fr: 'Échec de l’extraction', de: 'Extraktion fehlgeschlagen', es: 'Extracción fallida'},
  'dt.extract_started_bg':     {it: '🔄 Estrazione items avviata in background — la troverai negli Items del template', en: '🔄 Item extraction started in background — find it in the template Items', fr: '🔄 Extraction des éléments lancée en arrière-plan — voir dans les Éléments du modèle', de: '🔄 Element-Extraktion im Hintergrund gestartet — siehe Elemente der Vorlage', es: '🔄 Extracción de ítems iniciada en segundo plano — la verás en los Ítems de la plantilla'},
  'dt.template_saved':         {it: 'Template salvato', en: 'Template saved', fr: 'Modèle enregistré', de: 'Vorlage gespeichert', es: 'Plantilla guardada'},
  'dt.extracting_items':       {it: 'Estrazione item in corso… (può richiedere 1-2 min)', en: 'Extracting items… (may take 1-2 min)', fr: 'Extraction des éléments… (1-2 min)', de: 'Elemente werden extrahiert… (1-2 Min.)', es: 'Extrayendo ítems… (1-2 min)'},
  'dt.items_extracted':        {it: '{n} item estratti', en: '{n} items extracted', fr: '{n} éléments extraits', de: '{n} Elemente extrahiert', es: '{n} ítems extraídos'},
  'dt.items_extract_failed':   {it: 'Template salvato, ma estrazione item fallita: usa "Ri-analizza".', en: 'Template saved, but item extraction failed: use "Re-analyze".', fr: 'Modèle enregistré, mais extraction échouée : utilisez « Ré-analyser ».', de: 'Vorlage gespeichert, aber Extraktion fehlgeschlagen: „Neu analysieren“ verwenden.', es: 'Plantilla guardada, pero la extracción falló: usa "Re-analizar".'},
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
  // v3.5.0-alpha.172.107 — pass 2: auto-swap DOM scan brutale per coprire le
  // 61 stringhe italiane comuni (Annulla, Salva, Cliente, Stato, ecc.) anche
  // dove i template NON hanno ancora data-i18n. Chiamato sempre (anche it,
  // per ripristinare il testo originale dopo round-trip cambio lingua).
  applyAutoSwap(root, lang);
}
window.applyI18n = applyI18n;

// v3.5.0-alpha.172.107 — auto-swap dictionary (61 stringhe comuni)
// Coprono ~60% delle stringhe italiane piu' usate (audit i18n_audit.py).
// Le restanti 139 stringhe (TODO_TRANSLATE) richiedono traduzione manuale
// o batch AI: vedi tools/i18n_patch_suggestions.md.
window.MF_I18N_AUTO_SWAP = {
  'common.annulla': { it: 'Annulla', en: 'Cancel', fr: 'Annuler', de: 'Abbrechen', es: 'Cancelar', },
  'common.caricamento': { it: 'Caricamento…', en: 'Loading…', fr: 'Chargement…', de: 'Laden…', es: 'Cargando…', },
  'common.stato': { it: 'Stato', en: 'Status', fr: 'Statut', de: 'Status', es: 'Estado', },
  'common.salva': { it: 'Salva', en: 'Save', fr: 'Enregistrer', de: 'Speichern', es: 'Guardar', },
  'common.elimina': { it: 'Elimina', en: 'Delete', fr: 'Supprimer', de: 'Löschen', es: 'Eliminar', },
  'common.progetto': { it: 'Progetto', en: 'Project', fr: 'Projet', de: 'Projekt', es: 'Proyecto', },
  'common.cliente': { it: 'Cliente', en: 'Client', fr: 'Client', de: 'Kunde', es: 'Cliente', },
  'common.risorsa': { it: 'Risorsa', en: 'Resource', fr: 'Ressource', de: 'Ressource', es: 'Recurso', },
  'common.data': { it: 'Data', en: 'Date', fr: 'Date', de: 'Datum', es: 'Fecha', },
  'common.lavorazione': { it: 'Lavorazione', en: 'Operation', fr: 'Opération', de: 'Arbeitsschritt', es: 'Operación', },
  'common.voce': { it: 'Voce', en: 'Item', fr: 'Article', de: 'Posten', es: 'Concepto', },
  'common.attivo': { it: 'Attivo', en: 'Active', fr: 'Actif', de: 'Aktiv', es: 'Activo', },
  'common.risorse': { it: 'Risorse', en: 'Resources', fr: 'Ressources', de: 'Ressourcen', es: 'Recursos', },
  'common.ricerca': { it: 'Ricerca', en: 'Search', fr: 'Recherche', de: 'Suche', es: 'Búsqueda', },
  'common.bozza': { it: 'Bozza', en: 'Draft', fr: 'Brouillon', de: 'Entwurf', es: 'Borrador', },
  'common.caricamento_2': { it: 'Caricamento...', en: 'Loading...', fr: 'Chargement...', de: 'Laden...', es: 'Cargando...', },
  'common.quando': { it: 'Quando', en: 'When', fr: 'Quand', de: 'Wann', es: 'Cuándo', },
  'common.quotazione': { it: 'Quotazione', en: 'Quote', fr: 'Devis', de: 'Angebot', es: 'Cotización', },
  'common.quotazioni': { it: 'Quotazioni', en: 'Quotes', fr: 'Devis', de: 'Angebote', es: 'Cotizaciones', },
  'common.confermato': { it: 'Confermato', en: 'Confirmed', fr: 'Confirmé', de: 'Bestätigt', es: 'Confirmado', },
  'common.crea': { it: 'Crea', en: 'Create', fr: 'Créer', de: 'Erstellen', es: 'Crear', },
  'common.clienti': { it: 'Clienti', en: 'Clients', fr: 'Clients', de: 'Kunden', es: 'Clientes', },
  'common.ore': { it: 'Ore', en: 'Hours', fr: 'Heures', de: 'Stunden', es: 'Horas', },
  'common.inviata': { it: 'Inviata', en: 'Sent', fr: 'Envoyée', de: 'Gesendet', es: 'Enviada', },
  'common.dal': { it: 'Dal', en: 'From', fr: 'Du', de: 'Von', es: 'Desde', },
  'common.opzionale': { it: '(opzionale)', en: '(optional)', fr: '(facultatif)', de: '(optional)', es: '(opcional)', },
  'common.progetti': { it: 'Progetti', en: 'Projects', fr: 'Projets', de: 'Projekte', es: 'Proyectos', },
  'common.totale': { it: 'Totale', en: 'Total', fr: 'Total', de: 'Gesamt', es: 'Total', },
  'common.approvata': { it: 'Approvata', en: 'Approved', fr: 'Approuvée', de: 'Genehmigt', es: 'Aprobada', },
  'auto.invia': { it: 'Invia', en: 'Send', fr: 'Envoyer', de: 'Senden', es: 'Enviar', },
  'auto.approvato': { it: 'Approvato', en: 'Approved', fr: 'Approuvé', de: 'Genehmigt', es: 'Aprobado', },
  'auto.annullato': { it: 'Annullato', en: 'Cancelled', fr: 'Annulé', de: 'Storniert', es: 'Anulado', },
  'auto.caricamento': { it: 'caricamento…', en: 'Loading…', fr: 'Chargement…', de: 'Laden…', es: 'Cargando…', },
  'auto.settimana': { it: 'Settimana', en: 'Week', fr: 'Semaine', de: 'Woche', es: 'Semana', },
  'auto.mese': { it: 'Mese', en: 'Month', fr: 'Mois', de: 'Monat', es: 'Mes', },
  'auto.errore': { it: 'Errore', en: 'Error', fr: 'Erreur', de: 'Fehler', es: 'Error', },
  'auto.fatto': { it: 'Fatto', en: 'Done', fr: 'Fait', de: 'Erledigt', es: 'Hecho', },
  'auto.descrizione_opzionale': { it: 'Descrizione (opzionale)', en: 'Description (optional)', fr: 'Description (facultative)', de: 'Beschreibung (optional)', es: 'Descripción (opcional)', },
  'auto.ora': { it: 'Ora', en: 'Hour', fr: 'Heure', de: 'Stunde', es: 'Hora', },
  'auto.scaduta': { it: 'Scaduta', en: 'Expired', fr: 'Expirée', de: 'Abgelaufen', es: 'Vencida', },
  'auto.errore_2': { it: 'Errore:', en: 'Error', fr: 'Erreur', de: 'Fehler', es: 'Error', },
  'auto.fornitore': { it: 'Fornitore', en: 'Supplier', fr: 'Fournisseur', de: 'Lieferant', es: 'Proveedor', },
  'auto.importo': { it: 'Importo', en: 'Amount', fr: 'Montant', de: 'Betrag', es: 'Importe', },
  'auto.nuova': { it: '(nuova)', en: '(new)', fr: '(nouvelle)', de: '(neu)', es: '(nueva)', },
  'auto.builtin': { it: 'Built-in', en: 'Built-in', fr: 'Intégré', de: 'Integriert', es: 'Integrado', },
  'auto.modalità_ritiroconsegna': { it: 'Modalità ritiro/consegna', en: 'Pickup/Delivery mode', fr: 'Mode retrait/livraison', de: 'Abholung/Lieferung', es: 'Modo recogida/entrega', },
  'auto.hint_ai_opzionale': { it: 'Hint AI (opzionale)', en: 'AI hint (optional)', fr: 'Indice IA (facultatif)', de: 'KI-Hinweis (optional)', es: 'Pista IA (opcional)', },
  'auto.costo_reale_fatture': { it: 'Costo reale (fatture)', en: 'Actual cost (invoices)', fr: 'Coût réel (factures)', de: 'Realer Aufwand (Rechnungen)', es: 'Coste real (facturas)', },
  'auto.note_per_il_commerciale_opzion': { it: 'Note per il commerciale (opzionale)', en: 'Notes for sales (optional)', fr: 'Notes pour le commercial (facultatif)', de: 'Notizen für Vertrieb (optional)', es: 'Notas para comercial (opcional)', },
  'auto.creaestendi_quote': { it: 'Crea/estendi quote', en: 'Create/extend quote', fr: 'Créer/étendre devis', de: 'Angebot erstellen/erweitern', es: 'Crear/ampliar cotización', },
  'auto.carica': { it: 'Carica', en: 'Upload', fr: 'Charger', de: 'Hochladen', es: 'Cargar', },
  'auto.stato': { it: 'Stato:', en: 'Status', fr: 'Statut', de: 'Status', es: 'Estado', },
  'auto.cliente': { it: 'Cliente:', en: 'Client', fr: 'Client', de: 'Kunde', es: 'Cliente', },
  'auto.progetto': { it: 'Progetto:', en: 'Project', fr: 'Projet', de: 'Projekt', es: 'Proyecto', },
  'auto.nota_opzionale': { it: 'Nota (opzionale)', en: 'Note (optional)', fr: 'Note (facultative)', de: 'Notiz (optional)', es: 'Nota (opcional)', },
  'auto.job_lavorazione': { it: 'Job (lavorazione)', en: 'Job (operation)', fr: 'Job (opération)', de: 'Job (Arbeitsschritt)', es: 'Trabajo (operación)', },
  'auto.note_messaggio_opzionale': { it: 'Note / messaggio (opzionale)', en: 'Notes / message (optional)', fr: 'Notes / message (facultatif)', de: 'Notizen / Nachricht (optional)', es: 'Notas / mensaje (opcional)', },
  'auto.motivo_opzionale': { it: 'Motivo (opzionale)', en: 'Reason (optional)', fr: 'Motif (facultatif)', de: 'Grund (optional)', es: 'Motivo (opcional)', },
  'auto.fattura': { it: 'Fattura', en: 'Invoice', fr: 'Facture', de: 'Rechnung', es: 'Factura', },
  'auto.importa': { it: 'Importa', en: 'Import', fr: 'Importer', de: 'Importieren', es: 'Importar', },
  'auto.mese_2': { it: 'Mese:', en: 'Month', fr: 'Mois', de: 'Monat', es: 'Mes', },
  'auto.rifiuta': { it: 'Rifiuta', en: 'Reject', fr: 'Rejeter', de: 'Ablehnen', es: 'Rechazar', },
  'auto.lavorazioni': { it: 'Lavorazioni', en: 'Operations', fr: 'Opérations', de: 'Arbeitsschritte', es: 'Operaciones', },
  'auto.consegne': { it: 'Consegne', en: 'Deliveries', fr: 'Livraisons', de: 'Lieferungen', es: 'Entregas', },
  'auto.aggiungi': { it: 'Aggiungi', en: 'Add', fr: 'Ajouter', de: 'Hinzufügen', es: 'Añadir', },
  'auto.spedizioni': { it: 'Spedizioni', en: 'Shipments', fr: 'Expéditions', de: 'Versand', es: 'Envíos', },
  'auto.progetti': { it: 'Progetti:', en: 'Projects', fr: 'Projets', de: 'Projekte', es: 'Proyectos', },
  'auto.clienti': { it: 'Clienti:', en: 'Clients', fr: 'Clients', de: 'Kunden', es: 'Clientes', },
  'auto.nuovo': { it: 'Nuovo', en: 'New', fr: 'Nouveau', de: 'Neu', es: 'Nuevo', },
  'auto.filtri': { it: 'Filtri', en: 'Filters', fr: 'Filtres', de: 'Filter', es: 'Filtros', },
  'auto.giorno': { it: 'Giorno', en: 'Day', fr: 'Jour', de: 'Tag', es: 'Día', },
  'auto.voci': { it: 'Voci', en: 'Items', fr: 'Articles', de: 'Posten', es: 'Conceptos', },
  'auto.rifiutata': { it: 'Rifiutata', en: 'Rejected', fr: 'Rejetée', de: 'Abgelehnt', es: 'Rechazada', },
  'auto.opzionale': { it: 'Opzionale', en: 'Optional', fr: 'Facultatif', de: 'Optional', es: 'Opcional', },
  'auto.subtotale': { it: 'Subtotale', en: 'Subtotal', fr: 'Sous-total', de: 'Zwischensumme', es: 'Subtotal', },
  'auto.totale': { it: 'TOTALE', en: 'Total', fr: 'Total', de: 'Gesamt', es: 'Total', },
  'auto.attiva': { it: 'Attiva', en: 'Active', fr: 'Active', de: 'Aktiv', es: 'Activa', },
  'auto.scaduto': { it: 'Scaduto', en: 'Expired', fr: 'Expiré', de: 'Abgelaufen', es: 'Vencido', },
  'auto.consegna': { it: 'Consegna', en: 'Delivery', fr: 'Livraison', de: 'Lieferung', es: 'Entrega', },
  'auto.conferma': { it: 'Conferma', en: 'Confirm', fr: 'Confirmer', de: 'Bestätigen', es: 'Confirmar', },
};

let _MF_ITALIAN_LOOKUP = null;
function _buildItalianLookup() {
  const m = new Map();
  for (const [key, entry] of Object.entries(window.MF_I18N_AUTO_SWAP)) {
    if (entry && entry.it) {
      m.set(entry.it.trim(), key);
    }
  }
  return m;
}

/**
 * v3.5.0-alpha.172.107 — Auto-swap brutale dei testi italiani hardcoded.
 * Scansiona text nodes + attributi (title/placeholder/alt/aria-label) e
 * sostituisce stringhe match-esatto trim con la traduzione della lingua corrente.
 *
 * Limitazioni note:
 * - Match SOLO esatto trim (no substring) per evitare di rompere testi
 *   contenenti nomi propri (es. "Cliente Italia SpA").
 * - Skip INPUT/TEXTAREA/SCRIPT/STYLE.
 * - Skip elementi con data-i18n already set (gestiti da pass 1).
 * - SHOW_TEXT walker → ignora HTML markup nei tag.
 */
// Storage per round-trip cambio lingua: ogni text node che abbiamo tradotto
// salva l'IT originale in `_mfOrigIt` (WeakMap per evitare leak DOM).
const _MF_ORIG_TEXT = new WeakMap();
function applyAutoSwap(root, lang) {
  root = root || document;
  lang = lang || mfCurrentLang();
  if (!_MF_ITALIAN_LOOKUP) _MF_ITALIAN_LOOKUP = _buildItalianLookup();
  // Text nodes
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => {
      const p = n.parentElement;
      if (!p) return NodeFilter.FILTER_REJECT;
      if (['SCRIPT', 'STYLE', 'INPUT', 'TEXTAREA'].includes(p.tagName)) {
        return NodeFilter.FILTER_REJECT;
      }
      if (p.hasAttribute('data-i18n')) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  let n;
  const toUpdate = [];
  while ((n = walker.nextNode())) {
    // Source-of-truth IT: prefer cached original, else current value
    const origIt = (_MF_ORIG_TEXT.get(n) || n.nodeValue).trim();
    if (!origIt) continue;
    const key = _MF_ITALIAN_LOOKUP.get(origIt);
    if (!key) continue;
    const translated = window.MF_I18N_AUTO_SWAP[key][lang];
    if (!translated) continue;
    toUpdate.push({ node: n, translated, origIt });
  }
  for (const u of toUpdate) {
    // Cache original IT prima del primo swap
    if (!_MF_ORIG_TEXT.has(u.node)) {
      _MF_ORIG_TEXT.set(u.node, u.node.nodeValue);
    }
    // Sostituisci preservando whitespace circostante
    const orig = _MF_ORIG_TEXT.get(u.node);
    u.node.nodeValue = orig.replace(u.origIt, u.translated);
  }
  // Attributes (title/placeholder/alt/aria-label)
  const ATTRS = ['title', 'placeholder', 'alt', 'aria-label'];
  for (const attr of ATTRS) {
    root.querySelectorAll(`[${attr}]`).forEach(el => {
      const cacheKey = `_mfOrigAttr_${attr}`;
      const origIt = (el.dataset[cacheKey] || el.getAttribute(attr) || '').trim();
      if (!origIt) return;
      const key = _MF_ITALIAN_LOOKUP.get(origIt);
      if (!key) return;
      const translated = window.MF_I18N_AUTO_SWAP[key][lang];
      if (!translated) return;
      if (!el.dataset[cacheKey]) el.dataset[cacheKey] = el.getAttribute(attr);
      el.setAttribute(attr, translated);
    });
  }
}
window.applyAutoSwap = applyAutoSwap;

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
