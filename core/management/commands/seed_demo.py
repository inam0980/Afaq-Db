"""Fill the database with realistic demo data for trying the system out.

    python manage.py seed_demo

Safe to run repeatedly (nothing is duplicated). Refuses to run when
DEBUG=False so demo data can never land in the client's real database by
accident; pass --force only if you really mean it.
"""

import datetime as dt
from decimal import Decimal as D

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from customers.models import Customer
from expenses import services as expense_services
from expenses.models import Expense, ExpenseCategory
from hr.models import Department, Employee
from hr.validators import build_saudi_iban
from invoicing import services as invoicing_services
from invoicing.models import Invoice, InvoiceLine
from jobs.costing import add_labour, add_material
from jobs.models import Job
from jobs.services import change_status
from payroll.models import PayrollRun, SalaryStructure
from payroll.services import approve_run, generate_payslips, mark_paid, update_payslip_inputs

DEMO_PASSWORD = "Demo@12345"

DEPARTMENTS = [
    ("ADMIN", "Administration", "الإدارة"),
    ("OPS", "Operations", "العمليات"),
    ("HVAC", "AC & HVAC", "التكييف والتبريد"),
    ("MEP", "Plumbing & Electrical", "السباكة والكهرباء"),
]

# first, last, arabic, nationality, id_number, dept, job, gender,
# hired (days ago), id expiry (days from today), basic, housing, transport
EMPLOYEES = [
    ("Mohammed", "Al-Qahtani", "محمد القحطاني", "SA", "1012345671", "ADMIN", "General Manager", "M", 3000, 900, 15000, 3750, 1000),
    ("Fahad", "Al-Harbi", "فهد الحربي", "SA", "1023456782", "OPS", "Operations Supervisor", "M", 1500, 20, 8000, 2000, 800),
    ("Noura", "Al-Otaibi", "نورة العتيبي", "SA", "1034567893", "ADMIN", "Accountant", "F", 800, 400, 7000, 1750, 700),
    ("Sara", "Al-Dosari", "سارة الدوسري", "SA", "1123456782", "ADMIN", "HR Officer", "F", 300, 700, 6500, 1625, 650),
    ("Rahul", "Sharma", "راهول شارما", "IN", "2045678904", "HVAC", "AC Technician", "M", 2200, 12, 3000, 750, 300),
    ("Imran", "Khan", "عمران خان", "PK", "2056789015", "HVAC", "AC Technician", "M", 1000, 200, 2800, 700, 300),
    ("Abdul", "Karim", "عبد الكريم", "BD", "2067890126", "MEP", "Plumber", "M", 600, -5, 2500, 625, 300),
    ("Jose", "Santos", "خوسيه سانتوس", "PH", "2078901237", "MEP", "Electrician", "M", 1300, 300, 3200, 800, 300),
    ("Ahmed", "Hassan", "أحمد حسن", "EG", "2089012348", "OPS", "Site Engineer", "M", 2600, 25, 6000, 1500, 600),
    ("Suresh", "Thapa", "سوريش ثابا", "NP", "2090123459", "OPS", "Painter", "M", 400, 500, 2200, 550, 300),
    ("Omar", "Al-Yamani", "عمر اليماني", "YE", "2101234560", "MEP", "Carpenter", "M", 1800, 150, 2700, 675, 300),
    ("Ravi", "Kumar", "رافي كومار", "IN", "2112345671", "HVAC", "Technician Helper", "M", None, 360, 1800, 450, 300),
]
JOINER_ID = "2112345671"               # hired this month -> pro-rata payslip
PASSPORT_EXPIRING_ID = "2078901237"    # passport (not iqama) expires soon

# id_number -> overtime hours, absence days, additions, note
PAYSLIP_INPUTS = {
    "2045678904": (D("12"), D("0"), D("0"), "Weekend AC emergency calls"),
    "2056789015": (D("6"), D("1"), D("0"), ""),
    "2078901237": (D("0"), D("0"), D("200"), "Remote site allowance"),
}

# invoice, category, description, vendor, vendor VAT no., total, VAT %, paid by, days ago, final status
EXPENSES = [
    ("DEMO-0001", "RENT", "Workshop rent - Al Sulay", "Al Sulay Real Estate", "300123456700003", "25000", 15, "bank", 3, "approved"),
    ("DEMO-0002", "VEHICLE", "Diesel for service vans", "Aldrees Petroleum", "300987654300003", "920", 15, "card", 1, "approved"),
    ("DEMO-0003", "MATERIALS", "Copper pipes & fittings", "Saco Hardware", "310112233400003", "3450", 15, "card", 5, "approved"),
    ("DEMO-0004", "GOVT", "Iqama renewal - 2 employees", "Jawazat", "", "1300", 0, "bank", 6, "approved"),
    ("DEMO-0005", "TOOLS", "Refrigerant gauge set", "Ace Hardware", "300555666700003", "780", 15, "card", 2, "submitted"),
    ("DEMO-0006", "UTILITIES", "Electricity bill - workshop", "Saudi Electricity Co.", "300000111100003", "1840", 15, "bank", 4, "submitted"),
    ("DEMO-0007", "SUBCON", "Scaffolding rental", "Al-Bina Contracting", "301234567800003", "4600", 15, "bank", 8, "rejected"),
    ("DEMO-0008", "OFFICE", "Printer toner & paper", "Jarir Bookstore", "300222333400003", "410", 15, "cash", 0, "draft"),
    ("DEMO-0009", "OTHER", "Team lunch - project handover", "Al Baik", "", "265", 0, "cash", 0, "draft"),
    ("DEMO-0010", "VEHICLE", "Van service & oil change", "Petromin Express", "300777888900003", "650", 15, "card", 35, "approved"),
]

# job title -> materials [(description, qty, unit cost)], labour [(technician id, hours)]
JOB_COSTS = {
    "Central AC not cooling - floor 3": (
        [("R410A refrigerant (kg)", "4", "85"), ("Compressor capacitor", "2", "45")],
        [("2045678904", "6"), ("2056789015", "6")],
    ),
    "Classroom lighting rewiring": (
        [("LED panel 60x60", "24", "62"), ("Cable 2.5mm (m)", "150", "3.2")],
        [("2078901237", "16")],
    ),
    "Leaking pipe in clinic washroom": (
        [("PPR pipe & fittings", "1", "140")],
        [("2067890126", "3")],
    ),
    "Kitchen cabinets repair": (
        [("Hinges (pair)", "6", "18"), ("MDF board", "2", "95")],
        [("2101234560", "5")],
    ),
}
# expense invoice -> job title it was spent on
EXPENSE_JOBS = {
    "DEMO-0002": "Classroom lighting rewiring",           # approved -> counts in job cost
    "DEMO-0005": "Central AC not cooling - floor 3",      # only submitted -> not counted yet
}

# Standalone demo invoices: marker (stored in notes), customer index, description,
# amount excl. VAT, issued N days ago, payment terms (days), payments [(amount, N days ago)],
# credit note (amount excl. VAT, reason) or None
DEMO_INVOICES = [
    ("DEMO-INV-CONTRACT", 1, "Annual AC maintenance contract - Q3", "5000", 60, 30, [], ("500", "Discount for a delayed visit")),
    ("DEMO-INV-VILLA", 3, "Villa AC servicing - 4 split units", "800", 95, 30, [("920", 70)], None),
    ("DEMO-INV-RECENT", 0, "Generator room ventilation fan replacement", "1200", 5, 30, [], None),
]
# job title -> payments [(amount incl. VAT, days ago)]
JOB_INVOICE_PAYMENTS = {
    "Leaking pipe in clinic washroom": [("747.50", 0)],      # paid in full
    "Classroom lighting rewiring": [("2000", 0)],            # partly paid
}

HR_PERMS = [
    "view_employee", "add_employee", "change_employee",
    "view_department", "add_department", "change_department",
    "view_salarystructure", "add_salarystructure", "change_salarystructure",
]
ACCOUNTANT_PERMS = [
    "view_employee", "view_salarystructure",
    "view_payrollrun", "add_payrollrun", "change_payrollrun", "view_payslip", "change_payslip",
    "view_expense", "add_expense", "change_expense", "view_expensecategory",
    "view_invoice", "add_invoice", "change_invoice", "view_customer", "view_job",
    "add_payment", "view_payment", "view_vat_return",
]
COORDINATOR_PERMS = [
    "view_job", "add_job", "change_job",
    "view_customer", "add_customer", "change_customer",
    "view_employee",
]
MANAGER_PERMS = sorted(set(
    HR_PERMS + ACCOUNTANT_PERMS + COORDINATOR_PERMS
    + ["approve_payrollrun", "approve_expense", "view_job_costing", "issue_invoice"]
))

ROLES = [
    # username, first, last, group, perms
    ("hr_demo", "Sara", "Al-Dosari", "HR", HR_PERMS),
    ("accountant_demo", "Noura", "Al-Otaibi", "Accountant", ACCOUNTANT_PERMS),
    ("coordinator_demo", "Fahad", "Al-Harbi", "Coordinator", COORDINATOR_PERMS),
    ("manager_demo", "Mohammed", "Al-Qahtani", "Manager", MANAGER_PERMS),
]

# name, arabic, kind, mobile, VAT no., building, street, district, city, postal code
CUSTOMERS = [
    ("Riyadh Towers Co.", "شركة أبراج الرياض", "business", "0551000001", "300111222300003",
     "2451", "King Fahd Road", "Al Olaya", "Riyadh", "12211"),
    ("Al Noor Schools", "مدارس النور", "business", "0551000002", "300444555600003",
     "7720", "Prince Turki St", "Al Malqa", "Riyadh", "13521"),
    ("Hilal Medical Clinic", "عيادة الهلال الطبية", "business", "0551000003", "",
     "", "", "Al Sulaimaniyah", "Riyadh", ""),
    ("Khalid Al-Shehri", "خالد الشهري", "individual", "0551000004", "",
     "3301", "Al Takhassusi St", "Hittin", "Riyadh", "13512"),
    ("Abdullah Al-Mutairi", "عبدالله المطيري", "individual", "0551000005", "",
     "", "", "Al Yasmin", "Riyadh", ""),
    ("Reem Al-Ghamdi", "ريم الغامدي", "individual", "0551000006", "",
     "", "", "Al Narjis", "Riyadh", ""),
]

# title, customer (index), service, priority, final status, technician ids, quoted, scheduled in N days
JOBS = [
    ("Central AC not cooling - floor 3", 0, "ac", "urgent", "in_progress", ["2045678904", "2056789015"], "1800", 0),
    ("Quarterly AC maintenance - 40 units", 0, "ac", "normal", "scheduled", ["2045678904"], "6500", 5),
    ("Classroom lighting rewiring", 1, "electrical", "normal", "completed", ["2078901237"], "4200", -6),
    ("Repaint school corridors", 1, "painting", "normal", "new", [], "9800", None),
    ("Leaking pipe in clinic washroom", 2, "plumbing", "urgent", "completed", ["2067890126"], "650", -2),
    ("Kitchen cabinets repair", 3, "carpentry", "normal", "in_progress", ["2101234560"], "1200", 0),
    ("Villa deep cleaning before move-in", 4, "cleaning", "normal", "new", [], "900", None),
    ("Split AC installation - 2 rooms", 5, "ac", "normal", "cancelled", [], "2400", None),
]


class Command(BaseCommand):
    help = "Create realistic demo data (departments, employees, payroll, expenses, demo users)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force", action="store_true", help="Run even when DEBUG is False (not recommended)."
        )

    def handle(self, *args, force=False, **options):
        if not settings.DEBUG and not force:
            raise CommandError(
                "Refusing to load demo data with DEBUG=False (this looks like production). "
                "Use --force only if you are sure."
            )
        self.today = timezone.localdate()
        with transaction.atomic():
            users = self._users()
            departments = self._departments()
            employees = self._employees(departments)
            self._salaries(employees)
            self._payroll(users)
            customers = self._customers()
            self._jobs(users, customers)
            self._expenses(users)
            self._invoices(users, customers)

        if options.get("verbosity", 1) >= 1:
            self._summary()

    # --- users & roles -------------------------------------------------------------

    def _users(self):
        User = get_user_model()
        users = {}
        for username, first, last, group_name, codenames in ROLES:
            perms = Permission.objects.filter(codename__in=codenames)
            if perms.count() != len(set(codenames)):
                raise CommandError(f"Unknown permission in {group_name} role.")
            group, _ = Group.objects.get_or_create(name=group_name)
            group.permissions.set(perms)
            user, _ = User.objects.get_or_create(
                username=username, defaults={"first_name": first, "last_name": last}
            )
            user.set_password(DEMO_PASSWORD)
            user.save()
            user.groups.set([group])
            users[group_name] = user
        return users

    # --- HR ------------------------------------------------------------------------

    def _departments(self):
        result = {}
        for code, en, ar in DEPARTMENTS:
            dept, _ = Department.objects.get_or_create(code=code, defaults={"name_en": en, "name_ar": ar})
            result[code] = dept
        return result

    def _joiner_hire_date(self):
        first = self.today.replace(day=1)
        return min(first + dt.timedelta(days=9), self.today)

    def _employees(self, departments):
        employees = []
        for i, (first, last, ar, nat, id_no, dept, job, gender, hired_ago, id_exp, *_pay) in enumerate(EMPLOYEES):
            hire = self._joiner_hire_date() if hired_ago is None else self.today - dt.timedelta(days=hired_ago)
            is_saudi = nat == "SA"
            passport_days = 18 if id_no == PASSPORT_EXPIRING_ID else 600 + i * 15
            emp, _ = Employee.objects.get_or_create(
                id_number=id_no,
                defaults={
                    "first_name": first,
                    "last_name": last,
                    "name_ar": ar,
                    "nationality": nat,
                    "date_of_birth": dt.date(1978 + i, i % 12 + 1, 10),
                    "gender": gender,
                    "id_expiry": self.today + dt.timedelta(days=id_exp),
                    "passport_no": "" if is_saudi else f"P{id_no[-7:]}",
                    "passport_expiry": None if is_saudi else self.today + dt.timedelta(days=passport_days),
                    "department": departments[dept],
                    "job_title": job,
                    "hire_date": hire,
                    "mobile": "05" + id_no[-8:],
                    "email": f"{first.lower()}.{last.lower().replace('-', '')}@example.com",
                    "bank_name": "Al Rajhi Bank" if i % 2 else "Saudi National Bank",
                    "iban": build_saudi_iban("80" if i % 2 else "10", id_no.rjust(18, "0")),
                },
            )
            employees.append(emp)
        return employees

    def _salaries(self, employees):
        pay = {row[4]: row[10:13] for row in EMPLOYEES}
        for emp in employees:
            basic, housing, transport = (D(v) for v in pay[emp.id_number])
            SalaryStructure.objects.get_or_create(
                employee=emp,
                effective_from=emp.hire_date,
                defaults={"basic": basic, "housing": housing, "transport": transport, "other": D("0")},
            )

    # --- payroll -------------------------------------------------------------------

    def _payroll(self, users):
        accountant, manager = users["Accountant"], users["Manager"]
        last_day_prev = self.today.replace(day=1) - dt.timedelta(days=1)

        prev, _ = PayrollRun.objects.get_or_create(
            year=last_day_prev.year, month=last_day_prev.month, defaults={"created_by": accountant}
        )
        if not prev.is_locked:
            generate_payslips(prev)
            approve_run(prev, manager)
        prev.refresh_from_db()
        if prev.status == PayrollRun.Status.APPROVED:
            mark_paid(prev, manager)

        current, _ = PayrollRun.objects.get_or_create(
            year=self.today.year, month=self.today.month, defaults={"created_by": accountant}
        )
        if current.is_locked:
            return
        generate_payslips(current)
        for slip in current.payslips.select_related("employee", "run"):
            inputs = PAYSLIP_INPUTS.get(slip.employee.id_number)
            if inputs:
                overtime, absence, additions, note = inputs
                update_payslip_inputs(
                    slip, overtime_hours=overtime, absence_days=absence, additions=additions, note=note
                )

    # --- expenses ------------------------------------------------------------------

    def _expenses(self, users):
        accountant, manager = users["Accountant"], users["Manager"]
        for inv, cat, desc, vendor, vat_no, total, rate, paid_by, days_ago, final in EXPENSES:
            job_title = EXPENSE_JOBS.get(inv)
            existing = Expense.objects.filter(invoice_number=inv).first()
            if existing:
                # Keep older demo databases in line with EXPENSE_JOBS. Some demo expenses
                # are approved (locked for save()), so the link is set via update().
                job = Job.objects.filter(title=job_title).first() if job_title else None
                if existing.job_id != (job.pk if job else None):
                    Expense.objects.filter(pk=existing.pk).update(job=job)
                continue
            expense = Expense(
                job=Job.objects.filter(title=job_title).first() if job_title else None,
                date=self.today - dt.timedelta(days=days_ago),
                category=ExpenseCategory.objects.get(code=cat),
                description=desc,
                vendor_name=vendor,
                vendor_vat_number=vat_no,
                invoice_number=inv,
                total=D(total),
                vat_rate=D(rate),
                payment_method=paid_by,
                created_by=accountant,
            )
            expense.receipt.save(f"{inv}.pdf", ContentFile(b"%PDF-1.4 demo receipt"), save=False)
            expense.full_clean()
            expense.save()
            if final == "draft":
                continue
            expense_services.submit(expense, accountant)
            if final == "approved":
                expense_services.approve(expense, manager)
            elif final == "rejected":
                expense_services.reject(expense, manager, reason="Quotation from a second supplier needed.")

    # --- customers & jobs -------------------------------------------------------

    def _customers(self):
        result = []
        for name, ar, kind, mobile, vat, building, street, district, city, postal in CUSTOMERS:
            customer, _ = Customer.objects.get_or_create(
                mobile=mobile,
                defaults={
                    "name": name, "name_ar": ar, "kind": kind, "vat_number": vat,
                    "building_number": building, "street": street, "district": district,
                    "city": city, "postal_code": postal,
                },
            )
            result.append(customer)
        return result

    def _jobs(self, users, customers):
        coordinator = users["Coordinator"]
        S = Job.Status
        for title, cust, service, priority, final, tech_ids, quoted, sched_days in JOBS:
            customer = customers[cust]
            existing = Job.objects.filter(customer=customer, title=title).first()
            if existing:
                # Backfill costs on demo jobs created before job costing existed.
                if existing.status != S.CANCELLED and not (
                    existing.materials.exists() or existing.labour.exists()
                ):
                    self._job_costs(existing, coordinator)
                continue
            job = Job.objects.create(
                customer=customer, service_type=service, title=title, priority=priority,
                quoted_amount=D(quoted), created_by=coordinator,
                scheduled_date=None if sched_days is None else self.today + dt.timedelta(days=sched_days),
            )
            job.technicians.set(Employee.objects.filter(id_number__in=tech_ids))
            if final == S.SCHEDULED:
                change_status(job, S.SCHEDULED)
            elif final in (S.IN_PROGRESS, S.COMPLETED):
                change_status(job, S.IN_PROGRESS)
                if final == S.COMPLETED:
                    change_status(job, S.COMPLETED)
            elif final == S.CANCELLED:
                change_status(job, S.CANCELLED, reason="Customer postponed to next season.")
            self._job_costs(job, coordinator)

    def _job_costs(self, job, user):
        materials, labour = JOB_COSTS.get(job.title, ([], []))
        for description, qty, unit in materials:
            add_material(job, user, description=description, quantity=D(qty), unit_cost=D(unit))
        for id_number, hours in labour:
            add_labour(
                job, user, employee=Employee.objects.get(id_number=id_number),
                date=self.today, hours=D(hours), note="",
            )

    # --- invoices & payments ----------------------------------------------------

    def _invoices(self, users, customers):
        accountant, manager = users["Accountant"], users["Manager"]

        for job in Job.objects.filter(status=Job.Status.COMPLETED, title__in=JOB_INVOICE_PAYMENTS):
            if job.invoices.exists():
                continue
            invoice = invoicing_services.create_from_job(job, accountant)
            invoicing_services.issue(invoice, manager)
            for amount, days_ago in JOB_INVOICE_PAYMENTS[job.title]:
                self._pay(invoice, accountant, amount, days_ago)

        for marker, cust, description, amount, issued_ago, terms, payments, credit in DEMO_INVOICES:
            if Invoice.objects.filter(notes=marker).exists():
                continue
            issued_on = self.today - dt.timedelta(days=issued_ago)
            invoice = Invoice.objects.create(
                customer=customers[cust], issue_date=issued_on,
                due_date=issued_on + dt.timedelta(days=terms), notes=marker, created_by=accountant,
            )
            InvoiceLine.objects.create(invoice=invoice, description=description, unit_price=D(amount))
            invoicing_services.recalculate(invoice)
            invoicing_services.issue(invoice, manager)
            for paid, days_ago in payments:
                self._pay(invoice, accountant, paid, days_ago)
            if credit:
                credit_amount, reason = credit
                note = invoicing_services.create_credit_note(invoice, accountant, reason=reason)
                line = note.lines.get()
                line.unit_price = D(credit_amount)
                line.save()
                invoicing_services.recalculate(note)
                invoicing_services.issue(note, manager)

    def _pay(self, invoice, user, amount, days_ago):
        invoicing_services.record_payment(
            invoice, user, amount=D(amount), date=self.today - dt.timedelta(days=days_ago),
            method="bank", reference=f"TRX-{invoice.pk:04d}",
        )

    # --- output --------------------------------------------------------------------

    def _summary(self):
        w = self.stdout.write
        w(self.style.SUCCESS("Demo data ready."))
        w(f"  Employees: {Employee.objects.count()}   Payroll runs: {PayrollRun.objects.count()}   "
          f"Expenses: {Expense.objects.count()}   Customers: {Customer.objects.count()}   "
          f"Jobs: {Job.objects.count()}   Invoices: {Invoice.objects.count()}")
        w("  Demo logins (password: %s):" % DEMO_PASSWORD)
        for username, _f, _l, group, _p in ROLES:
            w(f"    {username:<17} {group}")
