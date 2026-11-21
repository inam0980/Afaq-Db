from django.db import migrations

from expenses.models import EXPENSE_NO_SEQUENCE

DEFAULT_CATEGORIES = [
    ("RENT", "Rent", "إيجار"),
    ("VEHICLE", "Vehicles & fuel", "مركبات ووقود"),
    ("MATERIALS", "Materials & spare parts", "مواد وقطع غيار"),
    ("TOOLS", "Tools & equipment", "أدوات ومعدات"),
    ("UTILITIES", "Utilities (electricity, water, internet)", "خدمات (كهرباء، ماء، إنترنت)"),
    ("GOVT", "Government fees (iqama, visas)", "رسوم حكومية (إقامة، تأشيرات)"),
    ("OFFICE", "Office & supplies", "مكتب ومستلزمات"),
    ("SUBCON", "Subcontractors", "مقاولون من الباطن"),
    ("OTHER", "Other", "أخرى"),
]


def seed(apps, schema_editor):
    Category = apps.get_model("expenses", "ExpenseCategory")
    for code, en, ar in DEFAULT_CATEGORIES:
        Category.objects.get_or_create(code=code, defaults={"name_en": en, "name_ar": ar})


def unseed(apps, schema_editor):
    Category = apps.get_model("expenses", "ExpenseCategory")
    Category.objects.filter(code__in=[c for c, _, _ in DEFAULT_CATEGORIES], expenses__isnull=True).delete()


class Migration(migrations.Migration):
    """Concurrency-safe expense numbers (EXP-00001) and default categories."""

    dependencies = [
        ("expenses", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql=f"CREATE SEQUENCE IF NOT EXISTS {EXPENSE_NO_SEQUENCE} START 1;",
            reverse_sql=f"DROP SEQUENCE IF EXISTS {EXPENSE_NO_SEQUENCE};",
        ),
        migrations.RunPython(seed, unseed),
    ]
