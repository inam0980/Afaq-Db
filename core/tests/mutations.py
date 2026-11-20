"""Deliberate bugs for tools/break_check.py: (title, file, original, broken)."""

MUTATIONS = [
    (
        "health: DB error handling removed",
        "core/health.py",
        "    try:\n        with connection.cursor() as cursor:\n            cursor.execute(\"SELECT 1\")\n            row = cursor.fetchone()\n    except DatabaseError:\n        return False\n",
        "    with connection.cursor() as cursor:\n        cursor.execute(\"SELECT 1\")\n        row = cursor.fetchone()\n",
    ),
    (
        "health: result not checked (always True)",
        "core/health.py",
        "    return row == (1,)",
        "    return True",
    ),
    (
        "health view: POST allowed",
        "core/views.py",
        "@require_GET\n",
        "",
    ),
    (
        "settings: timezone changed to UTC",
        "config/settings.py",
        'TIME_ZONE = "Asia/Riyadh"',
        'TIME_ZONE = "UTC"',
    ),
    (
        "settings: SQLite instead of PostgreSQL",
        "config/settings.py",
        '"ENGINE": "django.db.backends.postgresql",\n        "NAME": env("DB_NAME"),',
        '"ENGINE": "django.db.backends.sqlite3",\n        "NAME": BASE_DIR / "db.sqlite3",',
    ),
]
