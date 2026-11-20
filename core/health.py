from django.db import DatabaseError, connection


def check_database() -> bool:
    """Return True if the database answers a trivial query, else False."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            row = cursor.fetchone()
    except DatabaseError:
        return False
    return row == (1,)
