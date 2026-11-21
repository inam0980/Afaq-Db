import datetime as dt
from decimal import Decimal

from django.db import migrations

# Baseline GOSI rates. Saudi: employee 9% annuities + 0.75% SANED;
# employer 9% + 0.75% SANED + 2% occupational hazards. Non-Saudi: employer 2%
# occupational hazards only. Contribution base capped at SAR 45,000.
# Newer rates (e.g. the 2024 Social Insurance Law steps for new entrants)
# are added in admin with their own effective date.
DEFAULT_RATES = [
    ("saudi", Decimal("9.75"), Decimal("11.75")),
    ("non_saudi", Decimal("0.00"), Decimal("2.00")),
]
BASELINE_DATE = dt.date(2000, 1, 1)
SALARY_CAP = Decimal("45000.00")


def seed(apps, schema_editor):
    GosiRate = apps.get_model("payroll", "GosiRate")
    for category, employee_rate, employer_rate in DEFAULT_RATES:
        GosiRate.objects.get_or_create(
            category=category,
            effective_from=BASELINE_DATE,
            defaults={
                "employee_rate": employee_rate,
                "employer_rate": employer_rate,
                "salary_cap": SALARY_CAP,
            },
        )


def unseed(apps, schema_editor):
    GosiRate = apps.get_model("payroll", "GosiRate")
    GosiRate.objects.filter(effective_from=BASELINE_DATE).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
