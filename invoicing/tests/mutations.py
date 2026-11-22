"""Deliberate bugs for tools/break_check.py: (title, file, original, broken)."""

Z = "invoicing/zatca.py"
M = "invoicing/models.py"
S = "invoicing/services.py"
V = "invoicing/views.py"
F = "invoicing/forms.py"
A = "invoicing/admin.py"
T = "invoicing/templates/invoicing/invoice_detail.html"
C = "jobs/costing.py"

MUTATIONS = [
    # --- ZATCA QR ---
    ("TLV length counts characters, not bytes", Z,
     "return bytes([tag, len(data)]) + data", "return bytes([tag, len(value)]) + data"),
    ("TLV values over 255 bytes accepted", Z, "    if len(data) > 255:", "    if False:"),
    ("QR timestamp not converted to UTC", Z,
     'stamp = timestamp.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")',
     'stamp = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")'),
    ("QR total not formatted to 2 decimals", Z,
     'tlv(4, f"{money(total):.2f}"),', "tlv(4, str(total)),"),
    ("QR VAT field carries the total", Z,
     'tlv(5, f"{money(vat_total):.2f}"),', 'tlv(5, f"{money(total):.2f}"),'),
    # --- lines & invoice model ---
    ("Line VAT ignores the line's rate", M,
     "self.vat = money(self.subtotal * Decimal(self.vat_rate) / 100)",
     'self.vat = money(self.subtotal * Decimal("0.15"))'),
    ("Line total excludes VAT", M, "self.total = self.subtotal + self.vat", "self.total = self.subtotal"),
    ("Zero quantity allowed", M,
     'validators=[MinValueValidator(Decimal("0.01"))],\n    )\n    unit_price',
     "validators=[],\n    )\n    unit_price"),
    ("Due date before issue date allowed", M,
     "        if self.issue_date and self.due_date and self.due_date < self.issue_date:", "        if False:"),
    ("Issued invoice can be saved", M,
     "    def save(self, *args, **kwargs):\n        self.ensure_draft()\n        super().save",
     "    def save(self, *args, **kwargs):\n        super().save"),
    ("Issued invoice can be deleted", M,
     "    def delete(self, *args, **kwargs):\n        self.ensure_draft()\n",
     "    def delete(self, *args, **kwargs):\n"),
    ("Lines of an issued invoice can be changed", M,
     "        Invoice(pk=self.invoice_id).ensure_draft()\n        self.subtotal", "        self.subtotal"),
    ("Lines of an issued invoice can be deleted", M,
     "        Invoice(pk=self.invoice_id).ensure_draft()\n        return super().delete",
     "        return super().delete"),
    # --- issue ---
    ("Issue uses stale totals", S,
     "    recalculate(inv)\n    if not inv.lines.exists():", "    if not inv.lines.exists():"),
    ("Issue without lines", S, "    if not inv.lines.exists():", "    if False:"),
    ("Zero-total invoice issued", S, "    if inv.total <= 0:", "    if inv.total < 0:"),
    ("Future-dated invoice issued", S, "    if inv.issue_date > timezone.localdate():", "    if False:"),
    ("Invoice issued twice", S, "    if not inv.is_draft:\n        raise", "    if False:\n        raise"),
    ("Customer data not validated at issue", S, "    customer.full_clean()", "    pass"),
    ("B2B/B2C type inverted", S,
     "Invoice.Type.STANDARD if customer.vat_number else Invoice.Type.SIMPLIFIED",
     "Invoice.Type.SIMPLIFIED if customer.vat_number else Invoice.Type.STANDARD"),
    ("Buyer name not frozen", S, "    inv.buyer_name = customer.name\n", ""),
    ("Invoice number without zero padding", S, 'return f"INV-{value:05d}"', 'return f"INV-{value}"'),
    ("Issuer not recorded", S, "    inv.issued_by = user\n", ""),
    # --- from job ---
    ("Unfinished job can be invoiced", S, "    if job.status != Job.Status.COMPLETED:", "    if False:"),
    ("Job without quote invoiced", S, "    if not job.quoted_amount:", "    if False:"),
    ("Job invoiced twice", S, "    if job.invoices.exists():", "    if False:"),
    ("Payment terms ignored", S,
     "        due_date=today + dt.timedelta(days=payment_terms_days()),", "        due_date=today,"),
    ("Job line priced at zero", S, "        unit_price=job.quoted_amount,", '        unit_price=Decimal("0"),'),
    ("QR built for drafts", S, "    if invoice.is_draft:\n        return None\n", ""),
    # --- job revenue ---
    ("Job revenue ignores invoices", C, "    revenue = _invoiced_revenue(job)", "    revenue = None"),
    ("Draft invoices count as revenue", C,
     'issued = job.invoices.filter(status="issued")', "issued = job.invoices.all()"),
    ("Job revenue includes VAT", C, 'return money(_sum(issued, "subtotal"))', 'return money(_sum(issued, "total"))'),
    # --- forms / views ---
    ("Job of another customer accepted", F,
     "        if job and customer and job.customer_id != customer.pk:", "        if False:"),
    ("Clerk can issue", V,
     '@permission_required("invoicing.issue_invoice", raise_exception=True)',
     '@permission_required("invoicing.change_invoice", raise_exception=True)'),
    ("Issue via GET", V,
     "@require_POST\n@login_required\n@permission_required(\"invoicing.issue_invoice\"",
     "@login_required\n@permission_required(\"invoicing.issue_invoice\""),
    ("Issued invoice editable", V,
     "    if not invoice.is_draft:\n        return render", "    if False:\n        return render"),
    ("Totals not recalculated after editing lines", V,
     "            services.recalculate(invoice)\n", ""),
    ("Job invoicing errors not shown", V,
     "        messages.error(request, \" \".join(exc.messages))\n        return redirect(job)",
     "        return redirect(job)"),
    # --- printable invoice ---
    ("QR missing on issued invoice", T, "{% if qr %}<div class=\"zatca-qr\"", "{% if False %}<div class=\"zatca-qr\""),
    ("Simplified invoice titled as tax invoice", T,
     '{% elif invoice.invoice_type == "simplified" %}', "{% elif False %}"),
    ("Issued invoice shows live customer name", T,
     "<strong>{% if invoice.is_draft %}{{ invoice.customer.name }}{% else %}{{ invoice.buyer_name }}{% endif %}</strong>",
     "<strong>{{ invoice.customer.name }}</strong>"),
    # --- admin, job page, sidebar ---
    ("Admin can delete issued invoice", A,
     "    def has_delete_permission(self, request, obj=None):\n        if obj is not None and not obj.is_draft:",
     "    def has_delete_permission(self, request, obj=None):\n        if False:"),
    ("Admin bulk delete enabled", A, '        actions.pop("delete_selected", None)\n', ""),
    ("Admin can edit issued invoice", A,
     "    def has_change_permission(self, request, obj=None):\n        if obj is not None and not obj.is_draft:",
     "    def has_change_permission(self, request, obj=None):\n        if False:"),
    ("Invoice button on unfinished jobs", "jobs/templates/jobs/job_detail.html",
     '{% elif not invoice and job.status == "completed" and perms.invoicing.add_invoice %}',
     "{% elif not invoice and perms.invoicing.add_invoice %}"),
    ("Sidebar invoices link without permission", "templates/base.html",
     "      {% if perms.invoicing.view_invoice %}\n", "      {% if True %}\n"),
]
