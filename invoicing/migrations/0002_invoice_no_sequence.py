from django.db import migrations

from invoicing.models import INVOICE_NO_SEQUENCE


class Migration(migrations.Migration):
    """Invoice numbers come from a PostgreSQL sequence and are taken only when an
    invoice is issued, so issued numbers are consecutive and drafts never leave gaps."""

    dependencies = [
        ("invoicing", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql=f"CREATE SEQUENCE IF NOT EXISTS {INVOICE_NO_SEQUENCE} START 1;",
            reverse_sql=f"DROP SEQUENCE IF EXISTS {INVOICE_NO_SEQUENCE};",
        ),
    ]
