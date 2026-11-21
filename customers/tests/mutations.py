"""Deliberate bugs for tools/break_check.py: (title, file, original, broken)."""

M = "customers/models.py"
V = "customers/views.py"
CV = "core/validators.py"

MUTATIONS = [
    ("Postal code of any length", CV,
     r'_POSTAL_CODE_RE = re.compile(r"^\d{5}$")', r'_POSTAL_CODE_RE = re.compile(r"^\d+$")'),
    ("Building number may contain letters", CV,
     r'_BUILDING_NUMBER_RE = re.compile(r"^\d{4}$")', r'_BUILDING_NUMBER_RE = re.compile(r"^\w{4}$")'),
    ("Mobile not validated", M,
     'max_length=10, validators=[validate_saudi_mobile])', "max_length=10)"),
    ("Individual may have a VAT number", M,
     "        if self.vat_number and self.kind == self.Kind.INDIVIDUAL:", "        if False:"),
    ("VAT business without address allowed", M,
     "        if self.vat_number and self.kind == self.Kind.BUSINESS:", "        if False:"),
    ("Postal code not required for B2B", M,
     'B2B_ADDRESS_FIELDS = ("street", "building_number", "city", "postal_code")',
     'B2B_ADDRESS_FIELDS = ("street", "building_number", "city")'),
    ("Duplicate VAT numbers allowed", M,
     '                fields=["vat_number"],\n                condition=~Q(vat_number=""),',
     '                fields=["vat_number", "name"],\n                condition=~Q(vat_number=""),'),
    ("Address line drops postal code", M,
     "city = \" \".join(p for p in (self.city, self.postal_code) if p)",
     "city = self.city"),
    ("Search ignores mobile", M,
     "                | Q(mobile__icontains=term)\n", ""),
    ("Inactive customers listed by default", V,
     "qs = Customer.objects.all() if show_all else Customer.objects.active()",
     "qs = Customer.objects.all()"),
    ("Create needs only view permission", V,
     '@permission_required("customers.add_customer", raise_exception=True)',
     '@permission_required("customers.view_customer", raise_exception=True)'),
    ("Customer page hides jobs", V,
     'jobs = customer.jobs.order_by("-created_at")[:50] if request.user.has_perm("jobs.view_job") else []',
     "jobs = []"),
]
