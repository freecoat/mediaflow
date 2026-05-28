"""
v3.5.0-alpha.172.107 — i18n generation step 1: pattern dictionary.

Riusa scan di tools/i18n_audit.py per estrarre stringhe italiane uniche,
contare frequenza, e mappare le TOP-N piu' comuni a entry MF_I18N
pre-tradotte (it/en/fr/de/es) usando un dictionary statico.

Le stringhe NON in dictionary vengono emesse con marker `TODO_TRANSLATE`
per traduzione manuale o batch AI successivo.

Output:
- `tools/i18n_generated_entries.js`: blocco JS pronto da mergere in
  `app/static/js/i18n.js` (sezione common.* + per-page sections).
- `tools/i18n_patch_suggestions.md`: lista stringa-by-stringa di chiave
  proposta + file/line dove annotare data-i18n.
"""
from __future__ import annotations

import sys
import re
from pathlib import Path
from collections import Counter, defaultdict

# Riusa scan helpers da audit
sys.path.insert(0, str(Path(__file__).parent))
from i18n_audit import scan_html, scan_js  # noqa: E402

# ── Dictionary statico EN/FR/DE/ES ────────────────────────────────────────
# Solo stringhe comuni UI. Tutte normalizzate lowercase per match.
# Output preserva casing originale via .capitalize() / .title() heuristico.
DICT: dict[str, dict[str, str]] = {
    # Common UI verbs/actions
    "salva": {"en": "Save", "fr": "Enregistrer", "de": "Speichern", "es": "Guardar"},
    "annulla": {"en": "Cancel", "fr": "Annuler", "de": "Abbrechen", "es": "Cancelar"},
    "elimina": {"en": "Delete", "fr": "Supprimer", "de": "Löschen", "es": "Eliminar"},
    "modifica": {"en": "Edit", "fr": "Modifier", "de": "Bearbeiten", "es": "Editar"},
    "crea": {"en": "Create", "fr": "Créer", "de": "Erstellen", "es": "Crear"},
    "carica": {"en": "Upload", "fr": "Charger", "de": "Hochladen", "es": "Cargar"},
    "scarica": {"en": "Download", "fr": "Télécharger", "de": "Herunterladen", "es": "Descargar"},
    "aggiungi": {"en": "Add", "fr": "Ajouter", "de": "Hinzufügen", "es": "Añadir"},
    "rimuovi": {"en": "Remove", "fr": "Retirer", "de": "Entfernen", "es": "Quitar"},
    "conferma": {"en": "Confirm", "fr": "Confirmer", "de": "Bestätigen", "es": "Confirmar"},
    "invia": {"en": "Send", "fr": "Envoyer", "de": "Senden", "es": "Enviar"},
    "approva": {"en": "Approve", "fr": "Approuver", "de": "Genehmigen", "es": "Aprobar"},
    "rifiuta": {"en": "Reject", "fr": "Rejeter", "de": "Ablehnen", "es": "Rechazar"},
    "esporta": {"en": "Export", "fr": "Exporter", "de": "Exportieren", "es": "Exportar"},
    "importa": {"en": "Import", "fr": "Importer", "de": "Importieren", "es": "Importar"},
    "cerca": {"en": "Search", "fr": "Rechercher", "de": "Suchen", "es": "Buscar"},
    "filtra": {"en": "Filter", "fr": "Filtrer", "de": "Filtern", "es": "Filtrar"},
    "ricerca": {"en": "Search", "fr": "Recherche", "de": "Suche", "es": "Búsqueda"},
    "filtro": {"en": "Filter", "fr": "Filtre", "de": "Filter", "es": "Filtro"},
    "filtri": {"en": "Filters", "fr": "Filtres", "de": "Filter", "es": "Filtros"},
    "caricamento": {"en": "Loading", "fr": "Chargement", "de": "Laden", "es": "Cargando"},
    "caricamento…": {"en": "Loading…", "fr": "Chargement…", "de": "Laden…", "es": "Cargando…"},
    "caricamento...": {"en": "Loading...", "fr": "Chargement...", "de": "Laden...", "es": "Cargando..."},
    "salvataggio": {"en": "Saving", "fr": "Enregistrement", "de": "Speichern", "es": "Guardando"},
    "elaborazione": {"en": "Processing", "fr": "Traitement", "de": "Verarbeitung", "es": "Procesando"},
    # Common UI nouns
    "cliente": {"en": "Client", "fr": "Client", "de": "Kunde", "es": "Cliente"},
    "clienti": {"en": "Clients", "fr": "Clients", "de": "Kunden", "es": "Clientes"},
    "progetto": {"en": "Project", "fr": "Projet", "de": "Projekt", "es": "Proyecto"},
    "progetti": {"en": "Projects", "fr": "Projets", "de": "Projekte", "es": "Proyectos"},
    "quotazione": {"en": "Quote", "fr": "Devis", "de": "Angebot", "es": "Cotización"},
    "quotazioni": {"en": "Quotes", "fr": "Devis", "de": "Angebote", "es": "Cotizaciones"},
    "fattura": {"en": "Invoice", "fr": "Facture", "de": "Rechnung", "es": "Factura"},
    "fatture": {"en": "Invoices", "fr": "Factures", "de": "Rechnungen", "es": "Facturas"},
    "voce": {"en": "Item", "fr": "Article", "de": "Posten", "es": "Concepto"},
    "voci": {"en": "Items", "fr": "Articles", "de": "Posten", "es": "Conceptos"},
    "riga": {"en": "Row", "fr": "Ligne", "de": "Zeile", "es": "Fila"},
    "righe": {"en": "Rows", "fr": "Lignes", "de": "Zeilen", "es": "Filas"},
    "totale": {"en": "Total", "fr": "Total", "de": "Gesamt", "es": "Total"},
    "subtotale": {"en": "Subtotal", "fr": "Sous-total", "de": "Zwischensumme", "es": "Subtotal"},
    "data": {"en": "Date", "fr": "Date", "de": "Datum", "es": "Fecha"},
    "ora": {"en": "Hour", "fr": "Heure", "de": "Stunde", "es": "Hora"},
    "ore": {"en": "Hours", "fr": "Heures", "de": "Stunden", "es": "Horas"},
    "giorno": {"en": "Day", "fr": "Jour", "de": "Tag", "es": "Día"},
    "giorni": {"en": "Days", "fr": "Jours", "de": "Tage", "es": "Días"},
    "settimana": {"en": "Week", "fr": "Semaine", "de": "Woche", "es": "Semana"},
    "mese": {"en": "Month", "fr": "Mois", "de": "Monat", "es": "Mes"},
    "mesi": {"en": "Months", "fr": "Mois", "de": "Monate", "es": "Meses"},
    "anno": {"en": "Year", "fr": "Année", "de": "Jahr", "es": "Año"},
    "stato": {"en": "Status", "fr": "Statut", "de": "Status", "es": "Estado"},
    "stati": {"en": "Statuses", "fr": "Statuts", "de": "Status", "es": "Estados"},
    "nuovo": {"en": "New", "fr": "Nouveau", "de": "Neu", "es": "Nuevo"},
    "nuova": {"en": "New", "fr": "Nouvelle", "de": "Neu", "es": "Nueva"},
    "consegna": {"en": "Delivery", "fr": "Livraison", "de": "Lieferung", "es": "Entrega"},
    "consegne": {"en": "Deliveries", "fr": "Livraisons", "de": "Lieferungen", "es": "Entregas"},
    "spedizione": {"en": "Shipment", "fr": "Expédition", "de": "Versand", "es": "Envío"},
    "spedizioni": {"en": "Shipments", "fr": "Expéditions", "de": "Versand", "es": "Envíos"},
    "fornitore": {"en": "Supplier", "fr": "Fournisseur", "de": "Lieferant", "es": "Proveedor"},
    "fornitori": {"en": "Suppliers", "fr": "Fournisseurs", "de": "Lieferanten", "es": "Proveedores"},
    "risorsa": {"en": "Resource", "fr": "Ressource", "de": "Ressource", "es": "Recurso"},
    "risorse": {"en": "Resources", "fr": "Ressources", "de": "Ressourcen", "es": "Recursos"},
    "lavorazione": {"en": "Operation", "fr": "Opération", "de": "Arbeitsschritt", "es": "Operación"},
    "lavorazioni": {"en": "Operations", "fr": "Opérations", "de": "Arbeitsschritte", "es": "Operaciones"},
    "errore": {"en": "Error", "fr": "Erreur", "de": "Fehler", "es": "Error"},
    "errori": {"en": "Errors", "fr": "Erreurs", "de": "Fehler", "es": "Errores"},
    "avviso": {"en": "Warning", "fr": "Avertissement", "de": "Warnung", "es": "Aviso"},
    "successo": {"en": "Success", "fr": "Succès", "de": "Erfolg", "es": "Éxito"},
    "messaggio": {"en": "Message", "fr": "Message", "de": "Nachricht", "es": "Mensaje"},
    "campo": {"en": "Field", "fr": "Champ", "de": "Feld", "es": "Campo"},
    "campi": {"en": "Fields", "fr": "Champs", "de": "Felder", "es": "Campos"},
    "obbligatorio": {"en": "Required", "fr": "Obligatoire", "de": "Pflichtfeld", "es": "Obligatorio"},
    "opzionale": {"en": "Optional", "fr": "Facultatif", "de": "Optional", "es": "Opcional"},
    "(opzionale)": {"en": "(optional)", "fr": "(facultatif)", "de": "(optional)", "es": "(opcional)"},
    # Status labels
    "bozza": {"en": "Draft", "fr": "Brouillon", "de": "Entwurf", "es": "Borrador"},
    "inviata": {"en": "Sent", "fr": "Envoyée", "de": "Gesendet", "es": "Enviada"},
    "approvata": {"en": "Approved", "fr": "Approuvée", "de": "Genehmigt", "es": "Aprobada"},
    "scaduta": {"en": "Expired", "fr": "Expirée", "de": "Abgelaufen", "es": "Vencida"},
    "scaduto": {"en": "Expired", "fr": "Expiré", "de": "Abgelaufen", "es": "Vencido"},
    "rifiutata": {"en": "Rejected", "fr": "Rejetée", "de": "Abgelehnt", "es": "Rechazada"},
    "superata": {"en": "Superseded", "fr": "Remplacée", "de": "Abgelöst", "es": "Reemplazada"},
    "annullata": {"en": "Cancelled", "fr": "Annulée", "de": "Storniert", "es": "Anulada"},
    "pagata": {"en": "Paid", "fr": "Payée", "de": "Bezahlt", "es": "Pagada"},
    "non pagata": {"en": "Unpaid", "fr": "Impayée", "de": "Unbezahlt", "es": "Sin pagar"},
    "parziale": {"en": "Partial", "fr": "Partielle", "de": "Teilweise", "es": "Parcial"},
    "attiva": {"en": "Active", "fr": "Active", "de": "Aktiv", "es": "Activa"},
    "attivo": {"en": "Active", "fr": "Actif", "de": "Aktiv", "es": "Activo"},
    "inattiva": {"en": "Inactive", "fr": "Inactive", "de": "Inaktiv", "es": "Inactiva"},
    "inattivo": {"en": "Inactive", "fr": "Inactif", "de": "Inaktiv", "es": "Inactivo"},
    "pianificato": {"en": "Planned", "fr": "Planifié", "de": "Geplant", "es": "Planificado"},
    "pianificata": {"en": "Planned", "fr": "Planifiée", "de": "Geplant", "es": "Planificada"},
    "consegnato": {"en": "Delivered", "fr": "Livré", "de": "Geliefert", "es": "Entregado"},
    "consegnata": {"en": "Delivered", "fr": "Livrée", "de": "Geliefert", "es": "Entregada"},
    "chiuso": {"en": "Closed", "fr": "Fermé", "de": "Geschlossen", "es": "Cerrado"},
    "chiusa": {"en": "Closed", "fr": "Fermée", "de": "Geschlossen", "es": "Cerrada"},
    # Round 2 — extracted from TODO_TRANSLATE top frequency
    "quando": {"en": "When", "fr": "Quand", "de": "Wann", "es": "Cuándo"},
    "confermato": {"en": "Confirmed", "fr": "Confirmé", "de": "Bestätigt", "es": "Confirmado"},
    "confermata": {"en": "Confirmed", "fr": "Confirmée", "de": "Bestätigt", "es": "Confirmada"},
    "dal": {"en": "From", "fr": "Du", "de": "Von", "es": "Desde"},
    "al": {"en": "To", "fr": "Au", "de": "Bis", "es": "Hasta"},
    "approvato": {"en": "Approved", "fr": "Approuvé", "de": "Genehmigt", "es": "Aprobado"},
    "annullato": {"en": "Cancelled", "fr": "Annulé", "de": "Storniert", "es": "Anulado"},
    "fatto": {"en": "Done", "fr": "Fait", "de": "Erledigt", "es": "Hecho"},
    "descrizione": {"en": "Description", "fr": "Description", "de": "Beschreibung", "es": "Descripción"},
    "descrizione (opzionale)": {"en": "Description (optional)", "fr": "Description (facultative)", "de": "Beschreibung (optional)", "es": "Descripción (opcional)"},
    "importo": {"en": "Amount", "fr": "Montant", "de": "Betrag", "es": "Importe"},
    "importi": {"en": "Amounts", "fr": "Montants", "de": "Beträge", "es": "Importes"},
    "(nuova)": {"en": "(new)", "fr": "(nouvelle)", "de": "(neu)", "es": "(nueva)"},
    "(nuovo)": {"en": "(new)", "fr": "(nouveau)", "de": "(neu)", "es": "(nuevo)"},
    "built-in": {"en": "Built-in", "fr": "Intégré", "de": "Integriert", "es": "Integrado"},
    "modalità ritiro/consegna": {"en": "Pickup/Delivery mode", "fr": "Mode retrait/livraison", "de": "Abholung/Lieferung", "es": "Modo recogida/entrega"},
    "hint ai (opzionale)": {"en": "AI hint (optional)", "fr": "Indice IA (facultatif)", "de": "KI-Hinweis (optional)", "es": "Pista IA (opcional)"},
    "costo reale (fatture)": {"en": "Actual cost (invoices)", "fr": "Coût réel (factures)", "de": "Realer Aufwand (Rechnungen)", "es": "Coste real (facturas)"},
    "note per il commerciale (opzionale)": {"en": "Notes for sales (optional)", "fr": "Notes pour le commercial (facultatif)", "de": "Notizen für Vertrieb (optional)", "es": "Notas para comercial (opcional)"},
    "crea/estendi quote": {"en": "Create/extend quote", "fr": "Créer/étendre devis", "de": "Angebot erstellen/erweitern", "es": "Crear/ampliar cotización"},
    "nota (opzionale)": {"en": "Note (optional)", "fr": "Note (facultative)", "de": "Notiz (optional)", "es": "Nota (opcional)"},
    "job (lavorazione)": {"en": "Job (operation)", "fr": "Job (opération)", "de": "Job (Arbeitsschritt)", "es": "Trabajo (operación)"},
    "note / messaggio (opzionale)": {"en": "Notes / message (optional)", "fr": "Notes / message (facultatif)", "de": "Notizen / Nachricht (optional)", "es": "Notas / mensaje (opcional)"},
    "motivo (opzionale)": {"en": "Reason (optional)", "fr": "Motif (facultatif)", "de": "Grund (optional)", "es": "Motivo (opcional)"},
    "nome": {"en": "Name", "fr": "Nom", "de": "Name", "es": "Nombre"},
    "cognome": {"en": "Surname", "fr": "Nom de famille", "de": "Nachname", "es": "Apellido"},
    "email": {"en": "Email", "fr": "E-mail", "de": "E-Mail", "es": "Correo electrónico"},
    "telefono": {"en": "Phone", "fr": "Téléphone", "de": "Telefon", "es": "Teléfono"},
    "indirizzo": {"en": "Address", "fr": "Adresse", "de": "Adresse", "es": "Dirección"},
    "città": {"en": "City", "fr": "Ville", "de": "Stadt", "es": "Ciudad"},
    "provincia": {"en": "Province", "fr": "Province", "de": "Provinz", "es": "Provincia"},
    "paese": {"en": "Country", "fr": "Pays", "de": "Land", "es": "País"},
    "cap": {"en": "ZIP", "fr": "Code postal", "de": "PLZ", "es": "Código postal"},
    "p.iva": {"en": "VAT no.", "fr": "N° TVA", "de": "USt-ID", "es": "NIF/CIF"},
    "codice fiscale": {"en": "Tax code", "fr": "Code fiscal", "de": "Steuernummer", "es": "Código fiscal"},
    "iban": {"en": "IBAN", "fr": "IBAN", "de": "IBAN", "es": "IBAN"},
    "sì": {"en": "Yes", "fr": "Oui", "de": "Ja", "es": "Sí"},
    "no": {"en": "No", "fr": "Non", "de": "Nein", "es": "No"},
    "ok": {"en": "OK", "fr": "OK", "de": "OK", "es": "OK"},
    "scegli": {"en": "Choose", "fr": "Choisir", "de": "Wählen", "es": "Elegir"},
    "seleziona": {"en": "Select", "fr": "Sélectionner", "de": "Auswählen", "es": "Seleccionar"},
    "applica": {"en": "Apply", "fr": "Appliquer", "de": "Anwenden", "es": "Aplicar"},
    "azzera": {"en": "Reset", "fr": "Réinitialiser", "de": "Zurücksetzen", "es": "Restablecer"},
    "indietro": {"en": "Back", "fr": "Retour", "de": "Zurück", "es": "Atrás"},
    "avanti": {"en": "Next", "fr": "Suivant", "de": "Weiter", "es": "Siguiente"},
    "dettagli": {"en": "Details", "fr": "Détails", "de": "Details", "es": "Detalles"},
    "azioni": {"en": "Actions", "fr": "Actions", "de": "Aktionen", "es": "Acciones"},
    "note": {"en": "Notes", "fr": "Notes", "de": "Notizen", "es": "Notas"},
    "tutti": {"en": "All", "fr": "Tous", "de": "Alle", "es": "Todos"},
    "nessuno": {"en": "None", "fr": "Aucun", "de": "Keine", "es": "Ninguno"},
    "nessuna": {"en": "None", "fr": "Aucune", "de": "Keine", "es": "Ninguna"},
}


def _norm(s: str) -> str:
    return s.strip().lower().replace("…", "…")


def slugify(s: str, max_len: int = 30) -> str:
    s = re.sub(r"[^\w\s]", "", s).strip().lower()
    s = re.sub(r"\s+", "_", s)
    return s[:max_len] or "x"


def make_entry(text: str) -> dict:
    """Ritorna dict {it, en, fr, de, es} con TODO_TRANSLATE per gap."""
    norm = _norm(text)
    if norm in DICT:
        d = dict(DICT[norm])
        d["it"] = text
        return d
    # Try senza punteggiatura finale (es. "Cliente:" → "cliente")
    norm_clean = re.sub(r"[\s:.,;!?…]+$", "", norm)
    if norm_clean in DICT:
        d = dict(DICT[norm_clean])
        d["it"] = text
        return d
    return {"it": text, "en": "TODO_TRANSLATE", "fr": "TODO_TRANSLATE",
            "de": "TODO_TRANSLATE", "es": "TODO_TRANSLATE"}


def main():
    root = Path("app")
    # Estrai tutte stringhe
    all_findings: list[dict] = []
    for tpl in sorted(root.glob("templates/**/*.html")):
        for f in scan_html(tpl):
            f["file"] = str(tpl)
            all_findings.append(f)
    for js in sorted(root.glob("static/js/**/*.js")):
        if js.name == "i18n.js":
            continue
        for f in scan_js(js):
            f["file"] = str(js)
            all_findings.append(f)

    # Dedupe per text + count frequency
    text_freq: Counter = Counter(f["text"] for f in all_findings)
    files_by_text: dict = defaultdict(set)
    for f in all_findings:
        files_by_text[f["text"]].add(f["file"])

    # Genera entry per ogni stringa unica
    entries: dict[str, dict] = {}
    translated_count = 0
    todo_count = 0
    for text, freq in text_freq.most_common():
        entry = make_entry(text)
        # Key: common.<slug> se freq >= 3 (usata su >= 3 file), altrimenti specific
        if freq >= 3:
            key = f"common.{slugify(text)}"
        else:
            key = f"auto.{slugify(text)}"
        if key in entries:
            # collision: aggiungi suffix
            i = 2
            while f"{key}_{i}" in entries:
                i += 1
            key = f"{key}_{i}"
        entries[key] = {**entry, "_meta": {"freq": freq, "files": sorted(files_by_text[text])}}
        if "TODO_TRANSLATE" in entry.values():
            todo_count += 1
        else:
            translated_count += 1

    # ── Output 1: blocco JS pronto da mergere in i18n.js
    out_js = Path("tools/i18n_generated_entries.js")
    js_lines = []
    js_lines.append("// v3.5.0-alpha.172.107 — Auto-generated da tools/i18n_generate_entries.py")
    js_lines.append("// Mergere in window.MF_I18N (app/static/js/i18n.js).")
    js_lines.append(f"// Totale entry: {len(entries)} ({translated_count} tradotte da dict, {todo_count} TODO_TRANSLATE)")
    js_lines.append("//")
    js_lines.append("// CONVENZIONE:")
    js_lines.append("//   common.* = stringa usata su >=3 file (probabile UI globale).")
    js_lines.append("//   auto.*   = stringa specifica (1-2 occorrenze). Considera spostarla")
    js_lines.append("//              in namespace dedicato (es. 'planning.*', 'quotes.*').")
    js_lines.append("")
    js_lines.append("window.MF_I18N_GENERATED = {")
    for key, e in entries.items():
        meta = e.get("_meta", {})
        comment = f"// freq={meta.get('freq', 0)} files={len(meta.get('files', []))}"
        js_lines.append(f"  '{key}': {{")
        for lng in ("it", "en", "fr", "de", "es"):
            v = e.get(lng, "").replace("'", "\\'")
            js_lines.append(f"    {lng}: '{v}',")
        js_lines.append(f"  }}, {comment}")
    js_lines.append("};")
    out_js.write_text("\n".join(js_lines), encoding="utf-8")

    # ── Output 2: report markdown patch suggestions
    out_md = Path("tools/i18n_patch_suggestions.md")
    md_lines = []
    md_lines.append("# i18n Patch Suggestions — v3.5.0-alpha.172.107")
    md_lines.append("")
    md_lines.append(f"**Generated entries**: {len(entries)} ({translated_count} tradotte, {todo_count} TODO_TRANSLATE)")
    md_lines.append(f"**Files**: {len({f['file'] for f in all_findings})}")
    md_lines.append("")
    md_lines.append("## Auto-tradotte (top 50 per frequenza)")
    md_lines.append("")
    md_lines.append("| Key | IT | EN | Files |")
    md_lines.append("| --- | --- | --- | ---: |")
    auto_tradotte = [(k, e) for k, e in entries.items() if "TODO_TRANSLATE" not in e.values()]
    auto_tradotte.sort(key=lambda kv: -kv[1].get("_meta", {}).get("freq", 0))
    for key, e in auto_tradotte[:50]:
        meta = e.get("_meta", {})
        files_count = len(meta.get("files", []))
        it = e['it'].replace('|', '\\|')[:40]
        en = e['en'].replace('|', '\\|')[:40]
        md_lines.append(f"| `{key}` | `{it}` | `{en}` | {files_count} |")
    md_lines.append("")
    md_lines.append("## TODO_TRANSLATE (top 30 per frequenza, da tradurre manual o AI)")
    md_lines.append("")
    md_lines.append("| Key | IT | Files |")
    md_lines.append("| --- | --- | ---: |")
    todos = [(k, e) for k, e in entries.items() if "TODO_TRANSLATE" in e.values()]
    todos.sort(key=lambda kv: -kv[1].get("_meta", {}).get("freq", 0))
    for key, e in todos[:30]:
        meta = e.get("_meta", {})
        it = e['it'].replace('|', '\\|')[:80]
        md_lines.append(f"| `{key}` | `{it}` | {len(meta.get('files', []))} |")
    md_lines.append("")
    out_md.write_text("\n".join(md_lines), encoding="utf-8")

    print(f"Total findings: {len(all_findings)}")
    print(f"Unique strings: {len(text_freq)}")
    print(f"Entries generated: {len(entries)}")
    print(f"  Auto-translated:  {translated_count}")
    print(f"  TODO_TRANSLATE:   {todo_count}")
    print(f"Output: {out_js}, {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
