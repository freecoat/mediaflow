---
name: italian-tax-compliance
description: Use when validating Italian tax compliance fields in MediaFlow — P.IVA, codice fiscale, codici fiscali RF01-RF19, tipo documento TD01-TD28, natura IVA N1-N7, codice SDI, IBAN. Trigger on tasks involving fattura/invoice/SDI/quote emit, tenant fiscal config, supplier creation, client fiscal data.
---

# Italian tax compliance validation

Reference per campi fiscali italiani in MediaFlow. Usa quando crei/modifichi:
- `Invoice` (cessionario snapshot + cedente snapshot)
- `Client` (vat_number, tax_code, sdi_code, pec)
- `Supplier` (vat_number, tax_code, iban)
- `Tenant` (legal_name, vat_number, tax_code, sdi_code, rea_number, fiscal_regime, iban)
- AI capability che propone clienti/fatture (`propose_client`, `propose_quote_emit`)

## P.IVA (Partita IVA)

**Formato:** 11 cifre per società italiane. Format: `IT` + 11 digits opzionalmente.

**Validazione modulo-10 checksum:**

```python
def validate_partita_iva(p_iva: str) -> bool:
    """Valida P.IVA italiana (11 cifre + Luhn-like checksum)."""
    s = p_iva.strip().upper().lstrip("IT")
    if len(s) != 11 or not s.isdigit():
        return False
    total = 0
    for i, c in enumerate(s[:10]):
        n = int(c)
        if i % 2 == 1:  # cifre dispari (1-based: 2,4,6,8,10) → ×2
            n *= 2
            if n > 9:
                n -= 9
        total += n
    check = (10 - (total % 10)) % 10
    return check == int(s[10])
```

**Use MCP**: prefer `validate_partita_iva` tool del MCP server `fattura-elettronica-it` quando disponibile.

## Codice fiscale (CF)

**Persone fisiche:** 16 alfanumerici. `[A-Z]{6}[0-9]{2}[A-Z][0-9]{2}[A-Z][0-9]{3}[A-Z]`.

**Persone giuridiche:** 11 cifre (= P.IVA tipicamente).

Validazione checksum CF persona fisica complessa; per MediaFlow basta regex match + lunghezza. Se serve full validation usa `codicefiscale` library.

## Codice Destinatario SDI

**Formato:** 7 alfanumerici (società) o `0000000` (default consumer / PEC). PA: 6 caratteri.

**Valori speciali:**
- `0000000` → invio a PEC del destinatario
- `XXXXXXX` → 7 letters/digits per codice destinatario commerciale (es. `M5UXCR1`, `T04ZHR3`)
- `999999` → 6 chars PA (Pubblica Amministrazione)

## RegimeFiscale (RF01-RF19)

Codici fiscali validi nella sezione `<CedentePrestatore><DatiAnagrafici><RegimeFiscale>`:

| Codice | Descrizione |
|---|---|
| RF01 | Ordinario |
| RF02 | Contribuenti minimi (art. 1, c.96-117, L. 244/07) |
| RF04 | Agricoltura e attività connesse e pesca |
| RF05 | Vendita sali e tabacchi |
| RF06 | Commercio fiammiferi |
| RF07 | Editoria |
| RF08 | Gestione servizi telefonia pubblica |
| RF09 | Rivendita documenti di trasporto pubblico |
| RF10 | Intrattenimenti, giochi e altre attività di cui DPR 640/72 |
| RF11 | Agenzie viaggi e turismo (art. 74-ter, DPR 633/72) |
| RF12 | Agriturismo (L. 413/91) |
| RF13 | Vendite a domicilio |
| RF14 | Rivendita beni usati, oggetti d'arte, antiquariato o da collezione |
| RF15 | Agenzie vendite all'asta di oggetti d'arte, antiquariato o da collezione |
| RF16 | IVA per cassa P.A. (art. 6, c.5, DPR 633/72) |
| RF17 | IVA per cassa (art. 32-bis, DL 83/2012) |
| RF18 | Altro |
| RF19 | Regime forfettario (art.1, c.54-89, L. 190/2014) |

**MediaFlow default**: `RF01` (ordinario). Casa di post-prod tipicamente è S.r.l./S.p.A. ordinaria.

## TipoDocumento (TD01-TD28)

Codici per `<DatiGenerali><DatiGeneraliDocumento><TipoDocumento>`:

| Codice | Descrizione | Use in MediaFlow |
|---|---|---|
| TD01 | Fattura | **default** emissione |
| TD02 | Acconto/anticipo su fattura | acconto progetto |
| TD03 | Acconto/anticipo su parcella | parcella |
| TD04 | Nota di credito | storno totale/parziale |
| TD05 | Nota di debito | recupero extra |
| TD06 | Parcella | professionisti senza P.IVA |
| TD16 | Integrazione fattura reverse charge interno | edge case |
| TD17 | Integrazione/autofattura acquisto servizi UE | acquisto da fornitore EU |
| TD18 | Integrazione acquisto beni intra-UE | acquisto beni EU |
| TD19 | Integrazione/autofattura acquisto beni art.17 c.2 DPR 633/72 | edge |
| TD20 | Autofattura per regolarizzazione/integrazione | denuncia |
| TD21 | Autofattura per splafonamento | esportatore abituale |
| TD22 | Estrazione beni da Deposito IVA | logistica |
| TD23 | Estrazione beni da Deposito IVA con versamento IVA | logistica |
| TD24 | Fattura differita art.21 c.4 DPR 633/72 | post-DDT |
| TD25 | Fattura differita art.21 c.4 lett.b | post-cessione |
| TD26 | Cessione beni ammortizzabili | dismissione |
| TD27 | Fattura per autoconsumo | uso personale |
| TD28 | Acquisti da San Marino con IVA (B2B) | SM operazioni |

## Natura IVA (N1-N7)

Codici per operazioni senza IVA in `<DettaglioLinee><Natura>`:

| Codice | Descrizione |
|---|---|
| N1 | Escluse ex art.15 |
| N2.1 | Non soggette ad IVA art.7-art.7-septies DPR 633/72 |
| N2.2 | Non soggette - altri casi |
| N3.1 | Non imponibili - esportazioni |
| N3.2 | Non imponibili - cessioni intracomunitarie |
| N3.3 | Non imponibili - cessioni verso San Marino |
| N3.4 | Non imponibili - assimilate alle esportazioni |
| N3.5 | Non imponibili - dichiarazione d'intento |
| N3.6 | Non imponibili - altre operazioni |
| N4 | Esenti |
| N5 | Regime del margine / IVA non esposta |
| N6.1-N6.9 | Inversione contabile (reverse charge) varie |
| N7 | IVA assolta in altro stato UE (vendite a distanza) |

**MediaFlow case**: post-prod IT B2B = IVA standard 22%, no `Natura`. Per export theatrical (US/UK distribuzione) → `N3.1`. Per servizi a clienti EU B2B → `N6.x` reverse charge.

## IBAN

**Formato Italia:** `IT` + 2 cifre check + `[A-Z]` CIN + 5 cifre ABI + 5 cifre CAB + 12 alfanumerici conto. Totale 27.

**Validazione mod-97 IBAN check:**

```python
def validate_iban_it(iban: str) -> bool:
    s = iban.replace(" ", "").upper()
    if not s.startswith("IT") or len(s) != 27:
        return False
    # IBAN ISO 13616: mod 97 = 1
    rearranged = s[4:] + s[:4]
    numeric = "".join(str(ord(c) - 55) if c.isalpha() else c for c in rearranged)
    return int(numeric) % 97 == 1
```

## SDI requirements per emissione fattura B2B IT

Campi obbligatori in `Invoice` per essere emessa via SDI:
- `client_legal_name_snap` + `client_vat_snap` o `client_tax_code_snap`
- `client_sdi_snap` (7 char) **oppure** `client_pec_snap` (se sdi=`0000000`)
- `client_address_snap`, `client_city_snap`, `client_province_snap` (2 char), `client_country_snap`
- `tenant_vat_snap`, `tenant_address_snap`, `tenant_fiscal_regime_snap` (RF01-RF19)
- `tenant_iban_snap` (opzionale ma raccomandato per pagamento)

## Pre-commit checks (manuale)

Quando emetti/modifichi fattura nel codice:

1. ✓ `vat_number` o `tax_code` non vuoto su `CessionarioCommittente`
2. ✓ `sdi_code` 7 char OR pec popolato (almeno uno)
3. ✓ `doc_type` ∈ {TD01, TD04, TD06} per casi MediaFlow standard
4. ✓ `vat_rate` numerico 0-22
5. ✓ `Natura` popolato SE `vat_rate=0`
6. ✓ `iban_snapshot` valido IT mod-97 se popolato
7. ✓ Per estero (`country != Italia`): `N3.1` (export) o `N6.x` (reverse) o IVA 22% normale UE

## MCP integration

Quando MCP `fattura-elettronica-it` è disponibile, **DELEGA** validazioni al server:
- `validate_partita_iva` → checksum mod-10
- `validate_cedente_prestatore` → blocco cedente completo
- `validate_cessionario` → blocco cessionario
- `get_regime_fiscale_codes` → lista RF aggiornata
- `get_tipo_documento_codes` → lista TD aggiornata
- `get_natura_codes` → lista N aggiornata
- `validate_fattura_xsd` → XML XSD compliance

Non re-implementare in Python — usa MCP tools.

## Riferimenti

- Spec ufficiale: developers.italia.it/en/fatturapa/
- Codici aggiornati: Agenzia delle Entrate, schema FatturaPA v1.6.1+
- MCP: lobehub.com/mcp/cmendezs-mcp-fattura-elettronica-it
