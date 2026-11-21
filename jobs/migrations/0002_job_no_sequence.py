from django.db import migrations

from jobs.models import JOB_NO_SEQUENCE


class Migration(migrations.Migration):
    """Concurrency-safe job numbers (JOB-00001, JOB-00002, ...)."""

    dependencies = [
        ("jobs", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql=f"CREATE SEQUENCE IF NOT EXISTS {JOB_NO_SEQUENCE} START 1;",
            reverse_sql=f"DROP SEQUENCE IF EXISTS {JOB_NO_SEQUENCE};",
        ),
    ]
