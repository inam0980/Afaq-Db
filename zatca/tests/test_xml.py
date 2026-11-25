"""Unit tests: UBL 2.1 XML built from our invoices (XML Implementation Standard v1.2)."""

import datetime as dt
from decimal import Decimal as D

import pytest
from django.utils import timezone
from lxml import etree

from customers.tests.factories import BusinessCustomerFactory, CustomerFactory
from invoicing.tests.factories import InvoiceLineFactory, invoice_with_lines, issued_invoice
from zatca.constants import FIRST_PIH, NS
from zatca.xml_builder import build_invoice

pytestmark = pytest.mark.django_db

UUID = "3cf5ee18-ee25-44ea-a444-2c37ba7f28be"


def build(invoice, icv=1, pih=FIRST_PIH):
    return build_invoice(invoice, uuid=UUID, icv=icv, pih=pih)


def text(root, path):
    found = root.xpath(path, namespaces=NS)
    assert found, f"missing {path}"
    return found[0].text if hasattr(found[0], "text") else str(found[0])


def b2b():
    return issued_invoice("1000.00", "250.50", customer=BusinessCustomerFactory(name="Riyadh Towers"))


def test_header_fields():
    inv = b2b()
    root = build(inv, icv=7)
    assert root.tag == f"{{{NS['inv']}}}Invoice"
    assert text(root, "cbc:ProfileID") == "reporting:1.0"
    assert text(root, "cbc:ID") == inv.number
    assert text(root, "cbc:UUID") == UUID
    assert text(root, "cbc:IssueDate") == inv.issue_date.isoformat()
    local = timezone.localtime(inv.issued_at)
    assert text(root, "cbc:IssueTime") == local.strftime("%H:%M:%S")
    assert text(root, "cbc:InvoiceTypeCode") == "388"
    assert text(root, "cbc:InvoiceTypeCode/@name") == "0100000"
    assert text(root, "cbc:DocumentCurrencyCode") == "SAR" and text(root, "cbc:TaxCurrencyCode") == "SAR"
    assert text(root, "cac:AdditionalDocumentReference[cbc:ID='ICV']/cbc:UUID") == "7"
    assert text(root, "cac:AdditionalDocumentReference[cbc:ID='PIH']/cac:Attachment/cbc:EmbeddedDocumentBinaryObject") == FIRST_PIH
    assert text(root, "cac:Signature/cbc:SignatureMethod") == "urn:oasis:names:specification:ubl:dsig:enveloped:xades"


def test_seller_party():
    root = build(b2b())
    party = "cac:AccountingSupplierParty/cac:Party/"
    assert text(root, party + "cac:PartyIdentification/cbc:ID") == "1010101010"
    assert text(root, party + "cac:PartyIdentification/cbc:ID/@schemeID") == "CRN"
    addr = party + "cac:PostalAddress/"
    assert [text(root, addr + f) for f in ("cbc:StreetName", "cbc:BuildingNumber", "cbc:CitySubdivisionName",
                                            "cbc:CityName", "cbc:PostalZone", "cac:Country/cbc:IdentificationCode")] == [
        "Prince Sultan Road", "2322", "Al Murabba", "Riyadh", "12345", "SA"]
    assert text(root, party + "cac:PartyTaxScheme/cbc:CompanyID") == "399999999900003"
    assert text(root, party + "cac:PartyTaxScheme/cac:TaxScheme/cbc:ID") == "VAT"
    assert text(root, party + "cac:PartyLegalEntity/cbc:RegistrationName") == "AFAQ ALSIYANAH ALDAWLIYAH EST"


def test_b2b_buyer_and_supply_date():
    inv = b2b()
    root = build(inv)
    party = "cac:AccountingCustomerParty/cac:Party/"
    assert text(root, party + "cac:PartyTaxScheme/cbc:CompanyID") == "300000000000003"
    assert text(root, party + "cac:PartyLegalEntity/cbc:RegistrationName") == "Riyadh Towers"
    assert text(root, party + "cac:PostalAddress/cbc:StreetName") == "King Fahd Road"
    assert text(root, party + "cac:PostalAddress/cbc:BuildingNumber") == "1234"
    assert text(root, "cac:Delivery/cbc:ActualDeliveryDate") == inv.issue_date.isoformat()


def test_totals_and_tax_breakdown():
    root = build(b2b())                                   # 1000 + 250.50 = 1250.50, VAT 187.58 (lines 150 + 37.58)
    mt = "cac:LegalMonetaryTotal/"
    assert text(root, mt + "cbc:LineExtensionAmount") == "1250.50"
    assert text(root, mt + "cbc:TaxExclusiveAmount") == "1250.50"
    assert text(root, mt + "cbc:TaxInclusiveAmount") == "1438.08"
    assert text(root, mt + "cbc:PayableAmount") == "1438.08"
    assert text(root, mt + "cbc:PayableAmount/@currencyID") == "SAR"
    totals = root.xpath("cac:TaxTotal", namespaces=NS)
    assert len(totals) == 2                               # one with breakdown, one in accounting currency
    assert [t.findtext(f"{{{NS['cbc']}}}TaxAmount") for t in totals] == ["187.58", "187.58"]
    assert len(totals[0].xpath("cac:TaxSubtotal", namespaces=NS)) == 1
    assert not totals[1].xpath("cac:TaxSubtotal", namespaces=NS)
    sub = "cac:TaxTotal/cac:TaxSubtotal/"
    assert text(root, sub + "cbc:TaxableAmount") == "1250.50"
    assert text(root, sub + "cac:TaxCategory/cbc:ID") == "S"
    assert text(root, sub + "cac:TaxCategory/cbc:Percent") == "15.00"


def test_lines():
    root = build(b2b())
    lines = root.xpath("cac:InvoiceLine", namespaces=NS)
    assert len(lines) == 2
    first = lines[0]
    assert first.findtext(f"{{{NS['cbc']}}}ID") == "1"
    assert text(first, "cbc:InvoicedQuantity") == "1.00"
    assert text(first, "cbc:LineExtensionAmount") == "1000.00"
    assert text(first, "cac:TaxTotal/cbc:TaxAmount") == "150.00"
    assert text(first, "cac:TaxTotal/cbc:RoundingAmount") == "1150.00"
    assert text(first, "cac:Item/cbc:Name") == "AC maintenance"
    assert text(first, "cac:Item/cac:ClassifiedTaxCategory/cbc:ID") == "S"
    assert text(first, "cac:Price/cbc:PriceAmount") == "1000.00"


def test_simplified_invoice():
    inv = issued_invoice(customer=CustomerFactory(name="Khalid"))
    root = build(inv)
    assert text(root, "cbc:InvoiceTypeCode/@name") == "0200000"
    assert not root.xpath("cac:AccountingCustomerParty/cac:Party/cac:PartyTaxScheme", namespaces=NS)


def test_zero_rated_line_gets_exemption_reason():
    inv = invoice_with_lines("1000.00", customer=BusinessCustomerFactory())
    InvoiceLineFactory(invoice=inv, unit_price=D("500.00"), vat_rate=D("0"), description="Export service")
    from expenses.tests.factories import UserFactory
    from invoicing.services import issue

    issue(inv, UserFactory())
    inv.refresh_from_db()
    root = build(inv)
    zero = root.xpath("cac:TaxTotal/cac:TaxSubtotal[cac:TaxCategory/cbc:ID='Z']", namespaces=NS)[0]
    assert text(zero, "cbc:TaxableAmount") == "500.00" and text(zero, "cbc:TaxAmount") == "0.00"
    assert text(zero, "cac:TaxCategory/cbc:Percent") == "0.00"
    assert text(zero, "cac:TaxCategory/cbc:TaxExemptionReasonCode") == "VATEX-SA-33"
    assert text(zero, "cac:TaxCategory/cbc:TaxExemptionReason") == "Export of services"


def test_credit_note():
    from expenses.tests.factories import UserFactory
    from invoicing import services

    original = b2b()
    note = services.create_credit_note(original, UserFactory(), reason="Wrong price")
    services.issue(note, UserFactory())
    note.refresh_from_db()
    root = build(note)
    assert text(root, "cbc:InvoiceTypeCode") == "381"
    assert text(root, "cbc:InvoiceTypeCode/@name") == "0100000"
    assert text(root, "cac:BillingReference/cac:InvoiceDocumentReference/cbc:ID") == original.number
    assert text(root, "cac:PaymentMeans/cbc:InstructionNote") == "Wrong price"


def test_no_empty_elements():
    """BR-KSA-F-03: a missing optional value (e.g. no district) must be left out, not empty."""
    inv = issued_invoice(customer=CustomerFactory(name="Khalid", district="", street=""))
    root = build(inv)
    empty = [el.tag for el in root.iter() if len(el) == 0 and not (el.text or "").strip()]
    assert empty == []


def test_draft_cannot_be_built():
    with pytest.raises(ValueError):
        build(invoice_with_lines())


def test_serialises_as_utf8_xml():
    root = build(b2b())
    data = etree.tostring(root, xml_declaration=True, encoding="UTF-8")
    assert data.startswith(b"<?xml version='1.0' encoding='UTF-8'?>")


def test_seller_without_cr_number_has_no_empty_identification(settings):
    settings.COMPANY_CR_NUMBER = ""
    root = build(b2b())
    assert not root.xpath("cac:AccountingSupplierParty/cac:Party/cac:PartyIdentification", namespaces=NS)
