from django.db import migrations

# code, English, Arabic, paid, deducts salary, uses annual balance, calendar days, max days, needs document
LEAVE_TYPES = [
    ("ANNUAL", "Annual leave", "إجازة سنوية", True, False, True, False, None, False),          # Art. 109
    ("SICK", "Sick leave", "إجازة مرضية", True, False, False, True, None, True),              # Art. 117
    ("UNPAID", "Unpaid leave", "إجازة بدون راتب", False, True, False, True, None, False),
    ("MARRIAGE", "Marriage leave", "إجازة زواج", True, False, False, False, 5, False),        # Art. 113
    ("BEREAVEMENT", "Bereavement leave", "إجازة وفاة", True, False, False, False, 5, False),  # Art. 113
    ("PATERNITY", "Paternity leave", "إجازة مولود", True, False, False, False, 3, False),     # Art. 113
    ("MATERNITY", "Maternity leave", "إجازة وضع", True, False, False, True, 84, False),       # Art. 151 (12 weeks)
    ("HAJJ", "Hajj leave", "إجازة الحج", True, False, False, True, 15, False),                # Art. 114
]


def seed(apps, schema_editor):
    LeaveType = apps.get_model("leave", "LeaveType")
    for code, en, ar, paid, deducts, annual, calendar, max_days, document in LEAVE_TYPES:
        LeaveType.objects.get_or_create(code=code, defaults={
            "name_en": en, "name_ar": ar, "is_paid": paid, "deducts_salary": deducts,
            "uses_annual_balance": annual, "counts_calendar_days": calendar,
            "max_days": max_days, "requires_attachment": document,
        })


def unseed(apps, schema_editor):
    apps.get_model("leave", "LeaveType").objects.filter(
        code__in=[t[0] for t in LEAVE_TYPES], requests__isnull=True
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("leave", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
