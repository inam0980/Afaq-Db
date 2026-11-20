"""Deliberate bugs for tools/break_check.py: (title, file, original, broken)."""

MUTATIONS = [
    # --- validators ---
    (
        "IBAN checksum check removed",
        "hr/validators.py",
        "if not _SAUDI_IBAN_RE.match(iban) or not _iban_checksum_ok(iban):",
        "if not _SAUDI_IBAN_RE.match(iban):",
    ),
    (
        "Mobile accepts any 0XXXXXXXXX (not only 05)",
        "hr/validators.py",
        r'_SAUDI_MOBILE_RE = re.compile(r"^05\d{8}$")',
        r'_SAUDI_MOBILE_RE = re.compile(r"^0\d{9}$")',
    ),
    (
        "ID number accepts any first digit",
        "hr/validators.py",
        r'_ID_NUMBER_RE = re.compile(r"^[12]\d{9}$")',
        r'_ID_NUMBER_RE = re.compile(r"^\d{10}$")',
    ),
    # --- model rules ---
    (
        "Nationality/ID prefix rule ignores nationality",
        "hr/models.py",
        'expected = "1" if self.is_saudi else "2"',
        'expected = self.id_number[0]',
    ),
    (
        "Birth date may equal hire date (>= became >)",
        "hr/models.py",
        "self.date_of_birth >= self.hire_date",
        "self.date_of_birth > self.hire_date",
    ),
    (
        "Terminated without termination date allowed",
        "hr/models.py",
        "elif self.status == self.Status.TERMINATED and not self.termination_date:",
        "elif False:",
    ),
    (
        "Termination date allowed while Active",
        "hr/models.py",
        "if self.termination_date and self.status != self.Status.TERMINATED:",
        "if False:",
    ),
    (
        "IBAN not normalized on save",
        "hr/models.py",
        "        self.iban = normalize_iban(self.iban)\n",
        "",
    ),
    (
        "Employee no. without zero padding",
        "hr/models.py",
        'return f"EMP-{value:05d}"',
        'return f"EMP-{value}"',
    ),
    (
        "Department delete cascades to employees",
        "hr/models.py",
        "        on_delete=models.PROTECT,\n        related_name=\"employees\",",
        "        on_delete=models.SET_NULL,\n        related_name=\"employees\",",
    ),
    # --- querysets ---
    (
        "Search ignores last name",
        "hr/models.py",
        "                | Q(last_name__icontains=term)\n",
        "",
    ),
    (
        "Expiring docs include terminated employees",
        "hr/models.py",
        "            self.active()\n            .filter(Q(id_expiry__lte=cutoff)",
        "            self\n            .filter(Q(id_expiry__lte=cutoff)",
    ),
    (
        "Expiring docs ignore passport expiry",
        "hr/models.py",
        ".filter(Q(id_expiry__lte=cutoff) | Q(passport_expiry__lte=cutoff))",
        ".filter(Q(id_expiry__lte=cutoff))",
    ),
    (
        "Expiring docs sorted by iqama only",
        "hr/models.py",
        '.order_by("next_expiry", "employee_no")',
        '.order_by("id_expiry", "employee_no")',
    ),
    # --- views / access control ---
    (
        "Create view only needs view permission",
        "hr/views.py",
        '@permission_required("hr.add_employee", raise_exception=True)',
        '@permission_required("hr.view_employee", raise_exception=True)',
    ),
    (
        "Edit view only needs view permission",
        "hr/views.py",
        '@permission_required("hr.change_employee", raise_exception=True)',
        '@permission_required("hr.view_employee", raise_exception=True)',
    ),
    (
        "HTMX search returns the full page",
        "hr/views.py",
        "    if _is_htmx(request):\n        return render(request, \"hr/partials/employee_table.html\", context)\n",
        "",
    ),
    (
        "days param has no upper limit",
        "hr/views.py",
        "if not 1 <= days <= MAX_EXPIRY_WINDOW:",
        "if days < 1:",
    ),
    (
        "Detail page history not passed",
        "hr/views.py",
        '{"employee": employee, "history": list(history)}',
        '{"employee": employee, "history": []}',
    ),
    # --- admin / forms / templates ---
    (
        "Admin allows deleting employees",
        "hr/admin.py",
        "        return False",
        "        return True",
    ),
    (
        "Date inputs lose ISO format",
        "hr/forms.py",
        'super().__init__(format="%Y-%m-%d", **kwargs)',
        "super().__init__(**kwargs)",
    ),
    (
        "HTMX loaded from CDN",
        "templates/base.html",
        "{% static 'vendor/htmx-2.0.4.min.js' %}",
        "https://unpkg.com/htmx.org@2.0.4",
    ),
    (
        "RTL direction not set for Arabic",
        "templates/base.html",
        '{% if BIDI %}rtl{% else %}ltr{% endif %}',
        "ltr",
    ),
]
