from django.db import migrations

from invoicing.models import CREDIT_NOTE_NO_SEQUENCE


class Migration(migrations.Migration):
    """Credit notes have their own consecutive numbers (CN-00001, ...), taken at issue."""

    dependencies = [
        ("invoicing", "0003_historicalinvoice_kind_historicalinvoice_original_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql=f"CREATE SEQUENCE IF NOT EXISTS {CREDIT_NOTE_NO_SEQUENCE} START 1;",
            reverse_sql=f"DROP SEQUENCE IF EXISTS {CREDIT_NOTE_NO_SEQUENCE};",
        ),
    ]
