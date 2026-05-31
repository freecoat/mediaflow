"""Task 10 — SDI XML invariant: Divisa=EUR, importi in valuta base.

Verifica che il builder FatturaPA:
- emetta sempre <Divisa>EUR</Divisa> indipendentemente dalla valuta del display
- usi gli importi base (NON divisi per fx_rate_to_base)
"""
from __future__ import annotations
import types
from datetime import date

import app.services.sdi_xml as sx


def _make_invoice(currency: str = "USD", rate: float = 0.92) -> object:
    """Minimal Invoice-like namespace per build_fattura_xml.

    Gli importi sono BASE (EUR). currency e fx_rate_to_base sono attributi
    di display — il builder NON deve usarli per i calcoli XML.
    """
    line = types.SimpleNamespace(
        id=1,
        description="Servizio post-produzione",
        quantity=1.0,
        unit_price=1000.0,
        total=1000.0,
        vat_rate=22.0,
        discount_pct=0.0,
    )
    return types.SimpleNamespace(
        id=42,
        number="F-2026-001",
        issue_date=date(2026, 5, 31),
        due_date=date(2026, 6, 30),
        doc_type="TD01",
        vat_rate=22.0,
        subtotal=1000.0,
        total=1220.0,
        notes=None,
        payment_method="Bonifico bancario",
        iban_snapshot=None,
        lines=[line],
        # Valuta display (non deve influenzare l'XML)
        currency=currency,
        fx_rate_to_base=rate,
        # Snapshot fiscali tenant
        tenant_vat_snap="IT01234567890",
        tenant_tax_code_snap=None,
        tenant_legal_name_snap="Claqo Srl",
        tenant_address_snap="Via Esempio 1",
        tenant_fiscal_regime_snap="RF01",
        # Snapshot fiscali cliente
        client_sdi_snap="ABCDEFG",
        client_pec_snap=None,
        client_vat_snap="IT09876543210",
        client_tax_code_snap=None,
        client_legal_name_snap="Cliente Test Srl",
        client_address_snap="Via Cliente 1",
        client_zip_snap="20121",
        client_city_snap="Milano",
        client_province_snap="MI",
        client_country_snap="IT",
        client_admin_email_snap=None,
    )


def _make_tenant() -> object:
    return types.SimpleNamespace(
        id=1,
        name="Claqo",
        legal_name="Claqo Srl",
        vat_number="IT01234567890",
        tax_code="01234567890",
        address="Via Esempio 1",
        street_address="Via Esempio 1",
        zip_code="00100",
        city="Roma",
        province="RM",
        country="IT",
        email="info@claqo.it",
        phone=None,
        fiscal_regime="RF01",
        rea_number=None,
        rea_office=None,
        rea_capital_eur=None,
        socio_unico=None,
        stato_liquidazione="LN",
    )


def test_sdi_divisa_is_eur_for_foreign_invoice():
    """Indipendentemente dalla currency del display, Divisa deve essere EUR."""
    inv = _make_invoice(currency="USD", rate=0.92)
    tenant = _make_tenant()

    xml_str, filename = sx.build_fattura_xml(inv, tenant)

    assert "<Divisa>EUR</Divisa>" in xml_str, (
        f"Divisa non EUR nell'XML SDI: cercato '<Divisa>EUR</Divisa>' in:\n{xml_str[:500]}"
    )


def test_sdi_imponibile_is_base_amount():
    """ImponibileImporto deve corrispondere all'importo BASE (1000.00), non convertito."""
    inv = _make_invoice(currency="USD", rate=0.92)
    tenant = _make_tenant()

    xml_str, _ = sx.build_fattura_xml(inv, tenant)

    # Importo base: 1000.00 EUR. Convertito in USD sarebbe 1000/0.92 ≈ 1086.96
    # Il builder NON deve convertire → deve emettere 1000.00
    assert "<ImponibileImporto>1000.00</ImponibileImporto>" in xml_str, (
        "ImponibileImporto dovrebbe essere 1000.00 (base EUR), "
        f"non il valore convertito in USD.\nXML snippet: "
        f"{xml_str[xml_str.find('ImponibileImporto')-5:xml_str.find('ImponibileImporto')+60]}"
    )


def test_sdi_total_is_base_amount():
    """ImportoTotaleDocumento deve essere il totale BASE (1220.00 EUR)."""
    inv = _make_invoice(currency="USD", rate=0.92)
    tenant = _make_tenant()

    xml_str, _ = sx.build_fattura_xml(inv, tenant)

    assert "<ImportoTotaleDocumento>1220.00</ImportoTotaleDocumento>" in xml_str, (
        "ImportoTotaleDocumento dovrebbe essere 1220.00 (base EUR).\n"
        f"XML snippet: {xml_str[xml_str.find('ImportoTotaleDocumento')-5:xml_str.find('ImportoTotaleDocumento')+70]}"
    )


def test_sdi_filename_format():
    """Filename segue convenzione SDI IT{piva}_{progressivo}.xml."""
    inv = _make_invoice()
    tenant = _make_tenant()

    _, filename = sx.build_fattura_xml(inv, tenant)

    assert filename.startswith("IT"), f"Filename deve iniziare con IT: {filename}"
    assert filename.endswith(".xml"), f"Filename deve terminare con .xml: {filename}"
