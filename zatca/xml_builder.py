"""UBL 2.1 XML for an issued invoice or credit note (XML Implementation Standard v1.2).

Element order follows the UBL 2.1 Invoice schema. Optional values that are
blank are left out entirely (BR-KSA-F-03: no empty elements). The output has
no indentation, so whitespace never affects the invoice hash.
"""

from collections import defaultdict
from decimal import Decimal

from django.conf import settings
from django.utils import timezone
from lxml import etree

from zatca.constants import (
    CURRENCY, NS, PROFILE_ID, SIGNATURE_ID, SIGNATURE_METHOD, TRANSACTION_SIMPLIFIED, TRANSACTION_STANDARD,
    TYPE_CODE_CREDIT_NOTE, TYPE_CODE_INVOICE, ZERO_RATE_REASONS,
)

NSMAP = {None: NS["inv"], "cac": NS["cac"], "cbc": NS["cbc"], "ext": NS["ext"]}


def _q(name: str) -> str:
    prefix, local = name.split(":")
    return f"{{{NS[prefix]}}}{local}"


def sub(parent, tag, text=None, **attrs):
    """Append an element; returns None (and adds nothing) for a blank leaf value."""
    if text is not None and str(text).strip() == "":
        return None
    element = etree.SubElement(parent, _q(tag), attrs)
    if text is not None:
        element.text = str(text)
    return element


def amount(parent, name, value):
    return sub(parent, name, f"{Decimal(value):.2f}", currencyID=CURRENCY)


def _address(party, street, building, district, city, postal_code):
    address = sub(party, "cac:PostalAddress")
    sub(address, "cbc:StreetName", street)
    sub(address, "cbc:BuildingNumber", building)
    sub(address, "cbc:CitySubdivisionName", district)
    sub(address, "cbc:CityName", city)
    sub(address, "cbc:PostalZone", postal_code)
    sub(sub(address, "cac:Country"), "cbc:IdentificationCode", "SA")


def _tax_scheme(parent):
    sub(sub(parent, "cac:TaxScheme"), "cbc:ID", "VAT")


def _category(parent, name, rate):
    category = sub(parent, name)
    sub(category, "cbc:ID", "S" if rate > 0 else "Z")
    sub(category, "cbc:Percent", f"{Decimal(rate):.2f}")
    return category


def _seller(root):
    party = sub(sub(root, "cac:AccountingSupplierParty"), "cac:Party")
    identification = sub(party, "cac:PartyIdentification")
    sub(identification, "cbc:ID", settings.COMPANY_CR_NUMBER, schemeID="CRN")
    if not len(identification):
        party.remove(identification)
    _address(party, settings.COMPANY_STREET, settings.COMPANY_BUILDING_NO, settings.COMPANY_DISTRICT,
             settings.COMPANY_CITY, settings.COMPANY_POSTAL_CODE)
    tax = sub(party, "cac:PartyTaxScheme")
    sub(tax, "cbc:CompanyID", settings.COMPANY_VAT_NUMBER)
    _tax_scheme(tax)
    sub(sub(party, "cac:PartyLegalEntity"), "cbc:RegistrationName", settings.COMPANY_NAME)


def _buyer(root, invoice):
    customer = invoice.customer
    party = sub(sub(root, "cac:AccountingCustomerParty"), "cac:Party")
    _address(party, customer.street, customer.building_number, customer.district, customer.city,
             customer.postal_code)
    if invoice.buyer_vat_number:
        tax = sub(party, "cac:PartyTaxScheme")
        sub(tax, "cbc:CompanyID", invoice.buyer_vat_number)
        _tax_scheme(tax)
    sub(sub(party, "cac:PartyLegalEntity"), "cbc:RegistrationName", invoice.buyer_name)


def _document_reference(root, ref_id, *, uuid=None, attachment=None):
    ref = sub(root, "cac:AdditionalDocumentReference")
    sub(ref, "cbc:ID", ref_id)
    if uuid is not None:
        sub(ref, "cbc:UUID", uuid)
    if attachment is not None:
        sub(sub(ref, "cac:Attachment"), "cbc:EmbeddedDocumentBinaryObject", attachment, mimeCode="text/plain")
    return ref


def _tax_totals(root, invoice, lines):
    groups = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for line in lines:
        groups[Decimal(line.vat_rate)][0] += line.subtotal
        groups[Decimal(line.vat_rate)][1] += line.vat
    total = sub(root, "cac:TaxTotal")
    amount(total, "cbc:TaxAmount", invoice.vat_amount)
    for rate in sorted(groups, reverse=True):
        taxable, vat = groups[rate]
        subtotal = sub(total, "cac:TaxSubtotal")
        amount(subtotal, "cbc:TaxableAmount", taxable)
        amount(subtotal, "cbc:TaxAmount", vat)
        category = _category(subtotal, "cac:TaxCategory", rate)
        if rate == 0:
            code = settings.ZATCA_ZERO_RATE_REASON
            sub(category, "cbc:TaxExemptionReasonCode", code)
            sub(category, "cbc:TaxExemptionReason", ZERO_RATE_REASONS[code])
        _tax_scheme(category)
    # BR-KSA-EN16931-09: a second total, without breakdown, in the accounting currency (SAR).
    amount(sub(root, "cac:TaxTotal"), "cbc:TaxAmount", invoice.vat_amount)


def _line(root, number, line):
    element = sub(root, "cac:InvoiceLine")
    sub(element, "cbc:ID", number)
    sub(element, "cbc:InvoicedQuantity", f"{line.quantity:.2f}", unitCode="PCE")
    amount(element, "cbc:LineExtensionAmount", line.subtotal)
    tax = sub(element, "cac:TaxTotal")
    amount(tax, "cbc:TaxAmount", line.vat)                       # KSA-11
    amount(tax, "cbc:RoundingAmount", line.total)                # KSA-12
    item = sub(element, "cac:Item")
    sub(item, "cbc:Name", line.description)
    _tax_scheme(_category(item, "cac:ClassifiedTaxCategory", line.vat_rate))
    amount(sub(element, "cac:Price"), "cbc:PriceAmount", line.unit_price)


def build_invoice(invoice, *, uuid: str, icv: int, pih: str):
    """The unsigned invoice; signing.sign_invoice adds the signature and the QR."""
    if invoice.is_draft:
        raise ValueError("Only issued invoices can be sent to ZATCA.")
    lines = list(invoice.lines.all())
    simplified = invoice.invoice_type == invoice.Type.SIMPLIFIED

    root = etree.Element(_q("inv:Invoice"), nsmap=NSMAP)
    sub(root, "cbc:ProfileID", PROFILE_ID)
    sub(root, "cbc:ID", invoice.number)
    sub(root, "cbc:UUID", uuid)
    sub(root, "cbc:IssueDate", invoice.issue_date.isoformat())
    sub(root, "cbc:IssueTime", timezone.localtime(invoice.issued_at).strftime("%H:%M:%S"))
    sub(root, "cbc:InvoiceTypeCode", TYPE_CODE_CREDIT_NOTE if invoice.is_credit_note else TYPE_CODE_INVOICE,
        name=TRANSACTION_SIMPLIFIED if simplified else TRANSACTION_STANDARD)
    sub(root, "cbc:DocumentCurrencyCode", CURRENCY)
    sub(root, "cbc:TaxCurrencyCode", CURRENCY)
    if invoice.is_credit_note:
        sub(sub(sub(root, "cac:BillingReference"), "cac:InvoiceDocumentReference"), "cbc:ID",
            invoice.original.number)
    _document_reference(root, "ICV", uuid=icv)
    _document_reference(root, "PIH", attachment=pih)
    signature = sub(root, "cac:Signature")
    sub(signature, "cbc:ID", SIGNATURE_ID)
    sub(signature, "cbc:SignatureMethod", SIGNATURE_METHOD)
    _seller(root)
    _buyer(root, invoice)
    sub(sub(root, "cac:Delivery"), "cbc:ActualDeliveryDate", invoice.issue_date.isoformat())   # KSA-5
    means = sub(root, "cac:PaymentMeans")
    sub(means, "cbc:PaymentMeansCode", "30")                     # credit transfer (UNTDID 4461)
    if invoice.is_credit_note:
        sub(means, "cbc:InstructionNote", invoice.reason)        # KSA-10, BR-KSA-17
    _tax_totals(root, invoice, lines)
    totals = sub(root, "cac:LegalMonetaryTotal")
    amount(totals, "cbc:LineExtensionAmount", invoice.subtotal)
    amount(totals, "cbc:TaxExclusiveAmount", invoice.subtotal)
    amount(totals, "cbc:TaxInclusiveAmount", invoice.total)
    amount(totals, "cbc:PayableAmount", invoice.total)
    for number, line in enumerate(lines, start=1):
        _line(root, number, line)
    return root
