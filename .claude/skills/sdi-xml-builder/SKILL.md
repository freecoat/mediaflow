---
name: sdi-xml-builder
description: Use when generating FatturaPA XML / SDI invoice from a MediaFlow Invoice ORM record, OR when implementing endpoint /finance/api/invoices/{id}/sdi-xml. Bridges MediaFlow schema → FatturaPA v1.6.1 XML via mcp-fattura-elettronica-it MCP server (21 tools). Trigger on "emit SDI", "generate FatturaPA XML", "send to SDI", "scarica XML fattura".
---

# SDI XML builder — MediaFlow → FatturaPA

Pipeline emissione XML conforme FatturaPA v1.6.1 partendo da un `Invoice` MediaFlow. Sfrutta MCP server `fattura-elettronica-it` (21 tool locali, no API esterna) configurato in `.mcp.json`.

## Prerequisiti

1. MCP server attivo: verifica `.mcp.json` contiene `fattura-elettronica-it` e `.claude/settings.json` ha `"enabledMcpjsonServers": ["fattura-elettronica-it"]`.
2. Invoice DB con campi snapshot popolati (vedi skill `italian-tax-compliance` checklist).
3. Tenant con `vat_number`, `address`, `fiscal_regime` (es. `RF01`) impostati.
4. Cliente con `vat_number` o `tax_code` + `sdi_code` o `pec` valorizzati.

## Pipeline (5 step)

### Step 1 — Validazione pre-build

Per ogni campo critico chiama MCP tool:

```python
# Validazione P.IVA tenant + cliente
mcp.call("validate_partita_iva", {"piva": invoice.tenant_vat_snap})
mcp.call("validate_partita_iva", {"piva": invoice.client_vat_snap})  # se presente

# Validazione blocchi anagrafici
mcp.call("validate_cedente_prestatore", {
  "denominazione": invoice.tenant_legal_name_snap,
  "partita_iva": invoice.tenant_vat_snap,
  "codice_fiscale": invoice.tenant_tax_code_snap,
  "regime_fiscale": invoice.tenant_fiscal_regime_snap,  # RF01-RF19
  "indirizzo": invoice.tenant_address_snap,
  ...
})
mcp.call("validate_cessionario", {
  "denominazione": invoice.client_legal_name_snap,
  "partita_iva": invoice.client_vat_snap,
  "codice_fiscale": invoice.client_tax_code_snap,
  ...
})
```

Se validazione fallisce → solleva eccezione + ritorna 400 con dettaglio campi.

### Step 2 — Header (DatiTrasmissione + Cedente + Cessionario)

```python
header = mcp.call("build_transmission_header", {
  "id_paese": "IT",
  "id_codice": invoice.tenant_vat_snap,
  "progressivo_invio": mcp.call("generate_progressivo_invio", {})["progressivo"],
  "formato_trasmissione": "FPR12",  # B2B privati; FPA12 per PA
  "codice_destinatario": invoice.client_sdi_snap or "0000000",
  "pec_destinatario": invoice.client_pec_snap if invoice.client_sdi_snap in (None, "0000000") else None,
})
```

`FormatoTrasmissione`:
- `FPR12` = B2B privati (caso MediaFlow standard)
- `FPA12` = B2G Pubblica Amministrazione
- `FPR12` opera con codice destinatario o PEC fallback

### Step 3 — DatiGenerali (TipoDocumento + numero + data + totale)

```python
dati_generali = mcp.call("build_dati_generali", {
  "tipo_documento": invoice.doc_type or "TD01",
  "divisa": "EUR",
  "data": str(invoice.issue_date),
  "numero": invoice.number,
  "importo_totale_documento": invoice.total,
  "causale": invoice.notes or "Servizi di post-produzione audiovisiva",
})
```

### Step 4 — DettaglioLinee (per ogni InvoiceLine)

```python
for line in invoice.lines:
    mcp.call("add_linea_dettaglio", {
      "numero_linea": line.id,
      "descrizione": line.description,
      "quantita": line.quantity,
      "prezzo_unitario": line.unit_price,
      "prezzo_totale": line.total,
      "aliquota_iva": line.vat_rate,
      "natura": _natura_for_line(line),  # N1-N7 se aliquota_iva=0, else None
    })
```

`_natura_for_line()` logic:
- IVA 22% normale → no `Natura`
- IVA 10% (es. spettacoli alcune categorie) → no `Natura`
- IVA 0% + export theatrical → `N3.1`
- IVA 0% + cliente EU B2B → `N6.x` reverse charge
- IVA 0% + esente Art.10 → `N4`

### Step 5 — Compute totali + payment + finalize

```python
totali = mcp.call("compute_totali", {})  # aggrega da linee
pagamento = mcp.call("build_dati_pagamento", {
  "condizioni": "TP02",  # pagamento completo
  "metodo_pagamento": "MP05",  # bonifico bancario
  "data_scadenza": str(invoice.due_date),
  "importo": invoice.total,
  "iban": invoice.iban_snapshot or invoice.tenant_iban_snap,
})
xml_str = mcp.call("generate_fattura_xml", {})  # ritorna XML completo
mcp.call("validate_fattura_xsd", {"xml": xml_str})  # XSD compliance

# Nome file SDI
filename = mcp.call("get_sdi_filename", {
  "id_paese": "IT",
  "id_codice": invoice.tenant_vat_snap,
  "progressivo": header["progressivo_invio"],
})["filename"]  # es. "IT12345678901_00001.xml"
```

## Endpoint MediaFlow proposto

`GET /finance/api/invoices/{invoice_id}/sdi-xml`:
- RBAC: `RequireEditInvoices`
- Risposta: `Response(xml_str, media_type="application/xml", headers={"Content-Disposition": f"attachment; filename={filename}"})`
- Log: emit `Notification` kind="invoice_sdi_generated" a `view_finance`

## Codici pagamento più usati (MP01-MP23)

| Codice | Descrizione | MediaFlow use |
|---|---|---|
| MP01 | Contanti | rare |
| MP02 | Assegno | rare |
| MP05 | Bonifico | **default** |
| MP08 | Carta di pagamento | retail |
| MP09 | RIBA | terms 60+gg |
| MP12 | RID | abbonamenti |
| MP23 | PagoPA | PA only |

## Condizioni pagamento (TP01-TP03)

| Codice | Descrizione |
|---|---|
| TP01 | Pagamento a rate |
| TP02 | Pagamento completo (default) |
| TP03 | Anticipo |

## Hardcoded MediaFlow defaults

```python
SDI_DEFAULTS = {
    "formato_trasmissione": "FPR12",
    "divisa": "EUR",
    "causale": "Servizi di post-produzione audiovisiva",
    "metodo_pagamento": "MP05",
    "condizioni_pagamento": "TP02",
    "tipo_documento": "TD01",
    "regime_fiscale": "RF01",
}
```

## Roadmap integrazione

**S7.x (immediato)**:
- Endpoint `/finance/api/invoices/{id}/sdi-xml` download
- Button "Genera XML SDI" in `/finance` tab Fatture
- Salva XML in `uploads/sdi/` per archive

**S8.x (futuro)**:
- Trasmissione automatica SDI via Aruba/Sole24Ore connettore (richiede firma digitale + accreditamento)
- Ricezione notifiche SDI (consegna/scarto/decorrenza termini) via PEC parsing
- Conservazione sostitutiva 10 anni (norma fiscale)

**S9.x (lontano)**:
- Ricezione fatture passive via SDI (B2B) → auto-create `SupplierInvoice`
- Riconciliazione automatica con bonifici (Plaid/Open Banking)

## Anti-pattern

- **NO ricreare XML manualmente con string concat** — usa MCP tools, garantiscono XSD compliance.
- **NO trasmettere a SDI senza firma digitale + conservazione** — richiesto legalmente (D.Lgs. 127/2015).
- **NO bypassare snapshot client/tenant** — Invoice cristallizza al momento emissione, non leggere live (immutabilità documento fiscale).

## Riferimenti

- MCP fattura-elettronica-it: 21 tool listed in skill `mediaflow-finance-feature-dev`
- Skill correlata: `italian-tax-compliance` per validazioni
- Spec: developers.italia.it/en/fatturapa/v1.6.1
