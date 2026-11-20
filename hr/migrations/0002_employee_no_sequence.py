from django.db import migrations

from hr.models import EMPLOYEE_NO_SEQUENCE


class Migration(migrations.Migration):
    """PostgreSQL sequence backing Employee.employee_no (EMP-00001, EMP-00002, ...).

    A sequence is concurrency-safe: two users creating employees at the same
    moment can never receive the same number.
    """

    dependencies = [
        ("hr", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql=f"CREATE SEQUENCE IF NOT EXISTS {EMPLOYEE_NO_SEQUENCE} START 1;",
            reverse_sql=f"DROP SEQUENCE IF EXISTS {EMPLOYEE_NO_SEQUENCE};",
        ),
    ]
