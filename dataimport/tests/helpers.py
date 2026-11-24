import csv
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook


def xlsx_file(rows, name="data.xlsx"):
    """rows: list of lists, first row = headers."""
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return SimpleUploadedFile(name, buffer.getvalue(),
                              content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def csv_file(rows, name="data.csv"):
    buffer = io.StringIO()
    csv.writer(buffer).writerows(rows)
    return SimpleUploadedFile(name, buffer.getvalue().encode("utf-8-sig"), content_type="text/csv")


EMPLOYEE_HEADERS = [
    "first_name", "last_name", "name_ar", "nationality", "id_number", "id_expiry", "passport_no",
    "passport_expiry", "date_of_birth", "gender", "department", "job_title", "hire_date", "mobile",
    "email", "bank_name", "iban",
]


def employee_row(**overrides):
    from hr.validators import build_saudi_iban

    row = {
        "first_name": "Ahmed", "last_name": "Khan", "name_ar": "أحمد خان", "nationality": "IN",
        "id_number": "2123456789", "id_expiry": "2027-05-01", "passport_no": "P1234567",
        "passport_expiry": "2028-05-01", "date_of_birth": "1990-03-15", "gender": "M",
        "department": "OPS", "job_title": "AC Technician", "hire_date": "2022-02-01",
        "mobile": "0512345678", "email": "ahmed@example.com", "bank_name": "Al Rajhi Bank",
        "iban": build_saudi_iban("80", "000000000000000001"),
    }
    row.update(overrides)
    return [row[h] for h in EMPLOYEE_HEADERS]
