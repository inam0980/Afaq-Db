"""Deliberate bugs for tools/break_check.py: (title, file, original, broken)."""

MUTATIONS = [
    (
        "health: DB error handling removed",
        "core/health.py",
        "    try:\n        with connection.cursor() as cursor:\n            cursor.execute(\"SELECT 1\")\n            row = cursor.fetchone()\n    except DatabaseError:\n        return False\n",
        "    with connection.cursor() as cursor:\n        cursor.execute(\"SELECT 1\")\n        row = cursor.fetchone()\n",
    ),
    (
        "health: result not checked (always True)",
        "core/health.py",
        "    return row == (1,)",
        "    return True",
    ),
    (
        "health view: POST allowed",
        "core/views.py",
        "@require_GET\n",
        "",
    ),
    (
        "settings: timezone changed to UTC",
        "config/settings.py",
        'TIME_ZONE = "Asia/Riyadh"',
        'TIME_ZONE = "UTC"',
    ),
    (
        "settings: SQLite instead of PostgreSQL",
        "config/settings.py",
        '"ENGINE": "django.db.backends.postgresql",\n        "NAME": env("DB_NAME"),',
        '"ENGINE": "django.db.backends.sqlite3",\n        "NAME": BASE_DIR / "db.sqlite3",',
    ),
]

UI = "core/templatetags/ui.py"
NAV = "core/context_processors.py"
DASH_VIEW = "core/views.py"
DASH_TPL = "core/templates/core/dashboard.html"
BASE = "templates/base.html"

MUTATIONS += [
    # --- UI helpers ---
    ("initials: first letter only", UI,
     'letters = words[0][0] + (words[-1][0] if len(words) > 1 else "")', "letters = words[0][0]"),
    ("initials: not uppercased", UI, "    return letters.upper()", "    return letters"),
    ("initials: empty name gives blank avatar", UI, '        return "?"', '        return ""'),
    ("icon: unknown name silently ignored", UI,
     '        raise ValueError(f"Unknown icon {name!r}") from None', '        return ""'),
    ("icon: not hidden from screen readers", UI, 'aria-hidden="true"', 'role="img"'),
    ("days_left: sign inverted", UI,
     "return (date - timezone.localdate()).days", "return (timezone.localdate() - date).days"),
    ("expiry_tone: today counted as expired", UI, "    if left < 0:", "    if left <= 0:"),
    ("expiry_tone: 30th day not 'soon'", UI, "    if left <= SOON_DAYS:", "    if left < SOON_DAYS:"),
    ("absolute: keeps the sign", UI, "    return abs(value)", "    return value"),
    # --- navigation ---
    ("nav: expiring page highlights Employees", NAV, '    ("hr", "expiring_documents"): "expiring",\n', ""),
    ("nav: salary page highlights Payroll", NAV, '    ("payroll", "employee_salary"): "employees",\n', ""),
    ("sidebar: Employees shown without permission", BASE, "{% if perms.hr.view_employee %}", "{% if True %}"),
    ("sidebar: Admin shown to non-staff", BASE, "{% if user.is_staff %}", "{% if True %}"),
    ("sidebar: Employees always active", BASE,
     '{% if nav_section == "employees" %}aria-current="page"{% endif %}', 'aria-current="page"'),
    ("login page uses the app shell", "templates/registration/login.html",
     '{% extends "auth_base.html" %}', '{% extends "base.html" %}'),
    ("font file path broken", "static/css/app.css",
     'url("../vendor/fonts/inter-var.woff2")', 'url("../vendor/fonts/inter.woff2")'),
    # --- dashboard ---
    ("dashboard: employee KPIs without permission", DASH_VIEW,
     '"show_employees": user.has_perm("hr.view_employee"),', '"show_employees": True,'),
    ("dashboard: payroll card without permission", DASH_VIEW,
     '"show_payroll": user.has_perm("payroll.view_payrollrun"),', '"show_payroll": True,'),
    ("dashboard: terminated counted as active", DASH_VIEW,
     "active_employees=Employee.objects.active().count(),", "active_employees=Employee.objects.count(),"),
    ("dashboard: expiring preview not capped", DASH_VIEW,
     "expiring=list(expiring[:EXPIRING_PREVIEW]),", "expiring=list(expiring),"),
    ("dashboard: payroll card shows any month's run", DASH_VIEW,
     "PayrollRun.objects.filter(year=today.year, month=today.month).first()",
     "PayrollRun.objects.first()"),
    ("dashboard: Add employee action without permission", DASH_TPL,
     "{% if perms.hr.add_employee %}", "{% if True %}"),
    ("dashboard: expired flag never shown", DASH_TPL,
     '{% if emp.next_expiry < today %}badge-expired{% else %}', '{% if False %}badge-expired{% else %}'),
    # --- cache-busted assets ---
    ("asset: no version in URL", UI,
     '    return f"{url}?v={_file_version(full_path, os.path.getmtime(full_path))}"', "    return url"),
    ("asset: version cached forever (ignores file changes)", UI,
     "_file_version(full_path, os.path.getmtime(full_path))", "_file_version(full_path, 0)"),
    ("asset: crashes when file is missing", UI,
     "    if not full_path:\n        return url\n", ""),
    ("app shell: stylesheet not cache-busted", BASE,
     "{% asset 'css/app.css' %}", "{% static 'css/app.css' %}"),
    ("login: stylesheet not cache-busted", "templates/auth_base.html",
     "{% asset 'css/app.css' %}", "{% static 'css/app.css' %}"),
]

SEED = "core/management/commands/seed_demo.py"

MUTATIONS += [
    ("money: half-even rounding", "core/money.py",
     "quantize(CENT, rounding=ROUND_HALF_UP)", "quantize(CENT, rounding='ROUND_HALF_EVEN')"),
    ("seed_demo: runs in production", SEED,
     "        if not settings.DEBUG and not force:", "        if False:"),
    ("seed_demo: duplicates expenses on rerun", SEED,
     "            existing = Expense.objects.filter(invoice_number=inv).first()",
     "            existing = None"),
    ("seed_demo: older expenses not linked to jobs on rerun", SEED,
     "                if existing.job_id != (job.pk if job else None):", "                if False:"),
    ("seed_demo: creator approves own expense", SEED,
     "                expense_services.approve(expense, manager)", "                expense_services.approve(expense, accountant)"),
    ("seed_demo: crashes when this month's payroll is locked", SEED,
     "        if current.is_locked:\n            return\n", ""),
    ("seed_demo: no overtime inputs", SEED,
     "            if inputs:", "            if False:"),
    ("seed_demo: HR role can see expenses", SEED,
     '    "view_salarystructure", "add_salarystructure", "change_salarystructure",\n]',
     '    "view_salarystructure", "add_salarystructure", "change_salarystructure", "view_expense",\n]'),
]

MUTATIONS += [
    ("seed_demo: coordinator can see expenses", SEED,
     '    "view_customer", "add_customer", "change_customer",\n    "view_employee",\n]',
     '    "view_customer", "add_customer", "change_customer",\n    "view_employee", "view_expense",\n]'),
    ("seed_demo: completed jobs left in progress", SEED,
     "                    change_status(job, S.COMPLETED)\n", "                    pass\n"),
    ("seed_demo: duplicates jobs on rerun", SEED,
     "            existing = Job.objects.filter(customer=customer, title=title).first()",
     "            existing = None"),
    ("seed_demo: costs added again on every rerun", SEED,
     "existing.materials.exists() or existing.labour.exists()", "False"),
    ("seed_demo: technicians not assigned", SEED,
     '            job.technicians.set(Employee.objects.filter(id_number__in=tech_ids))\n', ""),
]

MUTATIONS += [
    ("seed_demo: manager cannot see job costs", SEED,
     '    + ["approve_payrollrun", "approve_expense", "view_job_costing"]',
     '    + ["approve_payrollrun", "approve_expense"]'),
    ("seed_demo: no job costs", SEED, "            self._job_costs(job, coordinator)\n", ""),
    ("seed_demo: expenses not linked to jobs", SEED,
     "                job=Job.objects.filter(title=job_title).first() if job_title else None,\n", ""),
]
