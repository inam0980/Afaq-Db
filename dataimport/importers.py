"""What can be imported, and how each row becomes a validated model instance.

A file is imported all-or-nothing: `validate()` builds every object and
collects every problem (row + column + message); `save()` refuses unless the
whole file is clean and then saves everything in one transaction. Existing
records are never updated — a row that matches one is an error."""

from dataclasses import dataclass, field

from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import transaction
from django.utils import translation
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from customers.models import Customer
from hr.constants import NATIONALITY_CHOICES
from hr.models import Department, Employee
from hr.validators import build_saudi_iban, normalize_iban
from payroll.models import ZERO, SalaryStructure

from dataimport.reading import as_date, as_decimal, as_text

FIRST_DATA_ROW = 2          # row 1 holds the column names


@dataclass
class Report:
    columns: list
    rows: list = field(default_factory=list)       # cleaned values, JSON-friendly
    errors: list = field(default_factory=list)
    error_rows: set = field(default_factory=set)
    objects: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.objects) and not self.errors

    @property
    def table(self):
        """(row number, values in column order, has errors) for the preview."""
        return [
            (number, [row[c] for c in self.columns], number in self.error_rows)
            for number, row in enumerate(self.rows, start=FIRST_DATA_ROW)
        ]


class RowProblems:
    def __init__(self, report, number):
        self.report, self.number, self.columns = report, number, set()

    def add(self, column, message):
        self.columns.add(column)
        self.report.error_rows.add(self.number)
        if column == NON_FIELD_ERRORS:
            text = _("Row %(row)s: %(message)s") % {"row": self.number, "message": message}
        else:
            text = _("Row %(row)s: %(column)s — %(message)s") % {
                "row": self.number, "column": column, "message": message,
            }
        self.report.errors.append(text)


def resolve_choice(value, choices, default=""):
    """Match a code or a label (English or Arabic) to the stored code."""
    text = as_text(value)
    if not text:
        return default
    wanted = text.casefold()
    for code, label in choices:
        names = {str(code).casefold(), str(label).casefold()}
        for language in ("en", "ar"):
            with translation.override(language):
                names.add(str(label).casefold())
        if wanted in names:
            return code
    raise ValueError(text)


class Importer:
    kind = ""
    title = ""
    permission = ""
    success_url = "dataimport:index"
    columns: tuple = ()
    required: tuple = ()
    example: dict = {}
    model = None
    exclude: tuple = ()          # model fields full_clean must skip
    unique_in_file: tuple = ()   # tuples of columns that must not repeat inside one file

    # -- helpers used by build() ----------------------------------------------------
    def _value(self, row, out, problems, column, convert, message):
        try:
            value = convert(row.get(column))
        except ValueError:
            problems.add(column, message)
            out[column] = as_text(row.get(column))
            return None
        out[column] = "" if value is None else str(value)      # dates -> YYYY-MM-DD
        return value

    def text(self, row, out, problems, column, **kwargs):
        return self._value(row, out, problems, column, lambda v: as_text(v, **kwargs), "")

    def date(self, row, out, problems, column):
        return self._value(row, out, problems, column, as_date,
                           _("Not a date. Use YYYY-MM-DD or DD/MM/YYYY."))

    def number(self, row, out, problems, column):
        return self._value(row, out, problems, column, as_decimal, _("Not a number."))

    def choice(self, row, out, problems, column, choices, default=""):
        return self._value(row, out, problems, column,
                           lambda v: resolve_choice(v, choices, default),
                           _("Unknown value “%(value)s”.") % {"value": as_text(row.get(column))})

    # -- subclass hooks ---------------------------------------------------------------
    def build(self, row, out, problems):                     # pragma: no cover - abstract
        raise NotImplementedError

    def extra_checks(self, obj, problems):
        """Checks the model itself does not enforce (e.g. duplicate customers)."""

    # -- public API ---------------------------------------------------------------------
    def validate(self, rows) -> Report:
        report = Report(columns=list(self.columns))
        if not rows:
            report.errors.append(_("The file has no data rows."))
            return report
        missing = [c for c in self.required if c not in rows[0]]
        if missing:
            report.errors.append(_("Missing column(s): %(columns)s") % {"columns": ", ".join(missing)})
            return report

        seen = {}
        for index, row in enumerate(rows):
            number = index + FIRST_DATA_ROW
            problems = RowProblems(report, number)
            out = {}
            obj = self.build(row, out, problems)
            report.rows.append({c: out.get(c, as_text(row.get(c))) for c in self.columns})
            if obj is None:
                continue
            try:
                obj.full_clean(exclude=[*self.exclude, *problems.columns])
            except ValidationError as exc:
                for name, messages in exc.message_dict.items():
                    for message in messages:
                        problems.add(name, message)
            self.extra_checks(obj, problems)
            for key_columns in self.unique_in_file:
                key = (key_columns, tuple(out.get(c, "") for c in key_columns))
                if not all(key[1]):
                    continue
                if key in seen:
                    problems.add(key_columns[0], _("Same as row %(row)s in this file.") % {"row": seen[key]})
                else:
                    seen[key] = number
            report.objects.append(obj)
        return report

    def save(self, report) -> int:
        if not report.ok:
            raise ValueError("Refusing to import a file with errors.")
        with transaction.atomic():
            for obj in report.objects:
                obj.save()
        return len(report.objects)


class EmployeeImporter(Importer):
    kind = "employees"
    title = gettext_lazy("Employees")
    permission = "hr.add_employee"
    success_url = "hr:employee_list"
    model = Employee
    exclude = ("employee_no",)
    unique_in_file = (("id_number",),)
    columns = (
        "first_name", "last_name", "name_ar", "nationality", "id_number", "id_expiry", "passport_no",
        "passport_expiry", "date_of_birth", "gender", "department", "job_title", "hire_date", "mobile",
        "email", "bank_name", "iban",
    )
    required = ("first_name", "last_name", "nationality", "id_number", "id_expiry", "date_of_birth",
                "gender", "job_title", "hire_date")
    example = {
        "first_name": "Ahmed", "last_name": "Khan", "name_ar": "أحمد خان", "nationality": "IN",
        "id_number": "2123456789", "id_expiry": "2027-05-01", "passport_no": "P1234567",
        "passport_expiry": "2028-05-01", "date_of_birth": "1990-03-15", "gender": "M",
        "department": "OPS", "job_title": "AC Technician", "hire_date": "2022-02-01",
        "mobile": "0512345678", "email": "ahmed@example.com", "bank_name": "Al Rajhi Bank",
        "iban": build_saudi_iban("80", "000000000000000001"),
    }

    def build(self, row, out, problems):
        values = {}
        for column in ("first_name", "last_name", "name_ar", "passport_no", "job_title", "email",
                       "bank_name", "id_number"):
            values[column] = self.text(row, out, problems, column)
        values["mobile"] = self.text(row, out, problems, "mobile", mobile=True)
        values["iban"] = normalize_iban(self.text(row, out, problems, "iban"))
        out["iban"] = values["iban"]
        for column in ("id_expiry", "passport_expiry", "date_of_birth", "hire_date"):
            values[column] = self.date(row, out, problems, column)
        values["nationality"] = self.choice(row, out, problems, "nationality", NATIONALITY_CHOICES)
        values["gender"] = self.choice(row, out, problems, "gender", Employee.Gender.choices)
        values["department"] = self._department(row, out, problems)
        return Employee(**values)

    def _department(self, row, out, problems):
        text = self.text(row, out, problems, "department")
        if not text:
            return None
        department = (Department.objects.filter(code__iexact=text).first()
                      or Department.objects.filter(name_en__iexact=text).first())
        if department is None:
            problems.add("department", _("No department with code or name “%(value)s”.") % {"value": text})
        return department


class CustomerImporter(Importer):
    kind = "customers"
    title = gettext_lazy("Customers")
    permission = "customers.add_customer"
    success_url = "customers:list"
    model = Customer
    unique_in_file = (("mobile",), ("vat_number",))
    columns = ("name", "name_ar", "kind", "mobile", "email", "vat_number",
               "building_number", "street", "district", "city", "postal_code")
    required = ("name", "mobile")
    example = {
        "name": "Riyadh Towers Co.", "name_ar": "شركة أبراج الرياض", "kind": "business",
        "mobile": "0551000001", "email": "facilities@example.com", "vat_number": "300000000000003",
        "building_number": "1234", "street": "King Fahd Road", "district": "Olaya", "city": "Riyadh",
        "postal_code": "12211",
    }

    def build(self, row, out, problems):
        values = {c: self.text(row, out, problems, c)
                  for c in ("name", "name_ar", "email", "vat_number", "building_number", "street",
                            "district", "city", "postal_code")}
        values["mobile"] = self.text(row, out, problems, "mobile", mobile=True)
        values["kind"] = self.choice(row, out, problems, "kind", Customer.Kind.choices,
                                     default=Customer.Kind.INDIVIDUAL)
        return Customer(**values)

    def extra_checks(self, obj, problems):
        if obj.mobile and Customer.objects.filter(mobile=obj.mobile).exists():
            problems.add("mobile", _("A customer with this mobile already exists."))


class SalaryImporter(Importer):
    kind = "salaries"
    title = gettext_lazy("Salary structures")
    permission = "payroll.add_salarystructure"
    model = SalaryStructure
    unique_in_file = (("id_number", "effective_from"),)
    columns = ("id_number", "effective_from", "basic", "housing", "transport", "other")
    required = ("id_number", "effective_from", "basic")
    example = {"id_number": "2123456789", "effective_from": "2024-01-01", "basic": "4000",
               "housing": "1000", "transport": "400", "other": "0"}

    def build(self, row, out, problems):
        id_number = self.text(row, out, problems, "id_number")
        employee = Employee.objects.filter(id_number=id_number).first()
        if employee is None:
            problems.add("id_number", _("No employee with this ID / iqama number."))
            return None
        values = {"employee": employee,
                  "effective_from": self.date(row, out, problems, "effective_from"),
                  "basic": self.number(row, out, problems, "basic")}
        for column in ("housing", "transport", "other"):
            amount = self.number(row, out, problems, column)
            values[column] = ZERO if amount is None else amount
        return SalaryStructure(**values)


IMPORTERS = {i.kind: i for i in (EmployeeImporter(), CustomerImporter(), SalaryImporter())}
