"""Deliberate bugs for tools/break_check.py: (title, file, original, broken)."""

H = "zatca/hashing.py"
Q = "zatca/qr.py"
X = "zatca/xml_builder.py"
SG = "zatca/signing.py"
SV = "zatca/services.py"
M = "zatca/models.py"
V = "zatca/views.py"
TT = "zatca/templatetags/zatca_tags.py"
C = "zatca/constants.py"
IV = "invoicing/views.py"

MUTATIONS = [
    # --- hash ---
    ("UBLExtensions hashed", H, '        doc.xpath("ext:UBLExtensions", namespaces=NS)\n        + ', "        "),
    ("Signature block hashed", H, '        + doc.xpath("cac:Signature", namespaces=NS)\n', ""),
    ("QR hashed", H, '''        + doc.xpath("cac:AdditionalDocumentReference[cbc:ID='QR']", namespaces=NS)\n''', ""),
    ("All references removed", H, "cac:AdditionalDocumentReference[cbc:ID='QR']\", namespaces=NS)",
     "cac:AdditionalDocumentReference\", namespaces=NS)"),
    ("Hash edits the original", H, "    doc = copy.deepcopy(root)", "    doc = root"),
    ("Whitespace after removed block lost", H, "    if tail:\n", "    if False:\n"),
    ("Hex instead of base64", H, '    return base64.b64encode(hash_bytes(root)).decode("ascii")',
     "    return hash_bytes(root).hex()"),
    ("Wrong first PIH", C, 'FIRST_PIH = "NWZlY2Vi', 'FIRST_PIH = "XWZlY2Vi'),
    # --- QR ---
    ("TLV length counts characters", Q, '    data = value.encode("utf-8") if isinstance(value, str) else bytes(value)',
     '    data = value.encode("latin-1", "replace") if isinstance(value, str) else bytes(value)'),
    ("No TLV size check", Q, "    if len(data) > 255:", "    if False:"),
    ("Hash as text in tag 6", Q, "        tlv(6, base64.b64decode(invoice_hash)),", "        tlv(6, invoice_hash),"),
    ("Tag 9 never added", Q, "    if certificate_signature is not None:", "    if False:"),
    ("Tags 7/8 swapped", Q, "        tlv(7, signature),\n        tlv(8, public_key),", "        tlv(7, public_key),\n        tlv(8, signature),"),
    # --- XML ---
    ("Empty elements kept", X, '    if text is not None and str(text).strip() == "":\n        return None',
     '    if False:\n        return None'),
    ("Credit note typed as invoice", X,
     "TYPE_CODE_CREDIT_NOTE if invoice.is_credit_note else TYPE_CODE_INVOICE", "TYPE_CODE_INVOICE"),
    ("Simplified flagged as standard", X, "name=TRANSACTION_SIMPLIFIED if simplified else TRANSACTION_STANDARD",
     "name=TRANSACTION_STANDARD"),
    ("No billing reference on credit note", X,
     "    if invoice.is_credit_note:\n        sub(sub(sub(root,", "    if False:\n        sub(sub(sub(root,"),
    ("No credit note reason", X, "        sub(means, \"cbc:InstructionNote\", invoice.reason)", "        pass"),
    ("Buyer VAT always omitted", X, "    if invoice.buyer_vat_number:\n        tax = sub(party", "    if False:\n        tax = sub(party"),
    ("Seller CRN scheme wrong", X, 'schemeID="CRN"', 'schemeID="TIN"'),
    ("No accounting-currency tax total", X,
     '    amount(sub(root, "cac:TaxTotal"), "cbc:TaxAmount", invoice.vat_amount)\n', ""),
    ("Zero rate has no reason", X, "        if rate == 0:\n            code", "        if False:\n            code"),
    ("Zero rate counted as standard", X, '    sub(category, "cbc:ID", "S" if rate > 0 else "Z")',
     '    sub(category, "cbc:ID", "S")'),
    ("Totals exclude VAT", X, '    amount(totals, "cbc:TaxInclusiveAmount", invoice.total)',
     '    amount(totals, "cbc:TaxInclusiveAmount", invoice.subtotal)'),
    ("Line rounding amount excludes VAT", X, '    amount(tax, "cbc:RoundingAmount", line.total)',
     '    amount(tax, "cbc:RoundingAmount", line.subtotal)'),
    ("Issue time in UTC", X, '    sub(root, "cbc:IssueTime", timezone.localtime(invoice.issued_at).strftime("%H:%M:%S"))',
     '    sub(root, "cbc:IssueTime", invoice.issued_at.strftime("%H:%M:%S"))'),
    ("Drafts built", X, "    if invoice.is_draft:\n        raise ValueError", "    if False:\n        raise ValueError"),
    # --- signing ---
    ("Curve ignored", SG, "    key = ec.generate_private_key(CURVES[curve]())", "    key = ec.generate_private_key(ec.SECP256R1())"),
    ("Unknown curve accepted", SG, "    if curve not in CURVES:\n        raise", "    if False:\n        raise"),
    ("Demo cert not marked", SG, '"DEMO - NOT ISSUED BY ZATCA"', '"AFAQ"'),
    ("Signed properties digest before insertion", SG,
     '    props_digest.text = _b64(hashlib.sha256(etree.tostring(props, method="c14n")).digest())',
     '    props_digest.text = _b64(hashlib.sha256(etree.tostring(props)).digest())'),
    ("Wrong certificate digest", SG,
     '    _el(digest, "ds:DigestValue", _b64(hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).digest()))',
     '    _el(digest, "ds:DigestValue", _b64(hashlib.sha256(cert.public_bytes(serialization.Encoding.PEM)).digest()))'),
    ("Simplified QR without tag 9", SG, "        certificate_signature=cert.signature if simplified else None,",
     "        certificate_signature=None,"),
    ("QR after signature", SG, "    pih.addnext(reference)", "    pih.getparent().append(reference)"),
    ("Extensions not first", SG, "    root.insert(0, extensions)\n", ""),
    ("Verify ignores hash", SG, "    if not signed or signed[0].text != actual:", "    if False:"),
    ("Verify ignores signature", SG, "    except (InvalidSignature, ValueError):\n        problems.append",
     "    except ZeroDivisionError:\n        problems.append"),
    ("Verify ignores QR", SG, "    if not qr or decode_tlv(qr[0].text).get(6) != base64.b64decode(actual):", "    if False:"),
    # --- chain / storage ---
    ("Counter not incremented", SV, "    icv, pih = egs.last_icv + 1, egs.last_hash or FIRST_PIH",
     "    icv, pih = 1, egs.last_hash or FIRST_PIH"),
    ("Chain not linked", SV, "    icv, pih = egs.last_icv + 1, egs.last_hash or FIRST_PIH",
     "    icv, pih = egs.last_icv + 1, FIRST_PIH"),
    ("Chain state not saved", SV, '    egs.save(update_fields=["last_icv", "last_hash"])', "    pass"),
    ("Draft generated", SV, "    if inv.is_draft:\n        raise ValidationError", "    if False:\n        raise ValidationError"),
    ("Generated twice", SV, "    if ZatcaDocument.objects.filter(invoice=inv).exists():", "    if False:"),
    ("Demo unit created again", SV, "    if existing:\n        return existing", "    if False:\n        return existing"),
    ("Private key stored in clear", M, "        self.private_key = encrypt(pem)", "        self.private_key = pem"),
    ("Key not bound to SECRET_KEY", M, '    digest = hashlib.sha256(f"zatca-egs-key:{settings.SECRET_KEY}".encode()).digest()',
     '    digest = hashlib.sha256(b"zatca-egs-key").digest()'),
    ("File name keeps symbols", M, '        number = re.sub(r"[^A-Za-z0-9]", "-", inv.number)', "        number = inv.number"),
    # --- views ---
    ("Viewer can generate", V,
     '@login_required\n@require_POST\n@permission_required("invoicing.issue_invoice", raise_exception=True)\ndef generate',
     "@login_required\n@require_POST\ndef generate"),
    ("Generate by GET", V,
     '@login_required\n@require_POST\n@permission_required("invoicing.issue_invoice", raise_exception=True)\ndef generate',
     '@login_required\n@permission_required("invoicing.issue_invoice", raise_exception=True)\ndef generate'),
    ("Generate errors crash", V, "    except ValidationError as exc:", "    except KeyError as exc:"),
    ("Download open to all", V,
     '@login_required\n@permission_required("invoicing.view_invoice", raise_exception=True)\ndef download',
     "@login_required\ndef download"),
    ("Button for everyone", TT, '        "can_generate": context["perms"]["invoicing"]["issue_invoice"],',
     '        "can_generate": True,'),
    ("No local check shown", TT, '        "problems": local_check(doc) if doc else None,', '        "problems": ["x"] if doc else None,'),
    ("Printed QR stays Phase 1", IV, "    payload = zatca_doc.qr if zatca_doc else services.qr_for(invoice)",
     "    payload = services.qr_for(invoice)"),
]
