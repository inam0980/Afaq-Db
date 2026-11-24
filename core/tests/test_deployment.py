"""Guard rails for the production setup (Docker + Nginx + Gunicorn).

Docker itself is not run here; these tests pin the settings that would
silently break production: Django's deploy checks, upload limits, uploaded
files never being public, matching PostgreSQL versions for backups."""

import os
import re
import subprocess
import sys
from pathlib import Path

from django.conf import settings

from expenses.validators import MAX_RECEIPT_BYTES

ROOT = Path(settings.BASE_DIR)


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_django_deploy_checks_pass_with_production_settings():
    env = dict(
        os.environ,
        DEBUG="False",
        HTTPS="True",
        SECRET_KEY="k7#Qp2!vX9zL$mR4wT8&yB1nC6@hJ3fD5sG0aE*uI-oP+lK=Zr8Vt",
        ALLOWED_HOSTS="erp.example.com",
        ADMIN_URL="manage-7f3k/",
        EMAIL_HOST="smtp.example.com",     # production must send real mail (password resets)
    )
    result = subprocess.run(
        [sys.executable, "manage.py", "check", "--deploy", "--fail-level", "WARNING"],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert result.returncode == 0, result.stdout + result.stderr


# --- nginx ------------------------------------------------------------------------

def nginx():
    """Active nginx configuration: commented-out lines (the HTTPS template) do not count."""
    lines = read("deploy/nginx.conf").splitlines()
    return "\n".join(line for line in lines if not line.lstrip().startswith("#"))


def test_nginx_allows_the_largest_upload():
    match = re.search(r"client_max_body_size\s+(\d+)m;", nginx())
    assert match and int(match[1]) * 1024 * 1024 > MAX_RECEIPT_BYTES


def test_nginx_passes_what_django_needs():
    conf = nginx()
    for header in ("proxy_set_header Host $host;", "proxy_set_header X-Forwarded-Proto $scheme;",
                   "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;"):
        assert header in conf
    assert "proxy_pass http://web:8000;" in conf


def test_nginx_serves_static_but_never_uploaded_files():
    conf = nginx()
    assert "location /static/" in conf
    assert "/media" not in conf          # receipts / IDs only through permission-checked views


# --- docker -----------------------------------------------------------------------

def test_backup_client_matches_database_server_version():
    """pg_dump must be at least the server's major version or backups fail."""
    server = re.search(r"image:\s*postgres:(\d+)", read("docker-compose.yml"))
    client = re.search(r"postgresql-client-(\d+)", read("Dockerfile"))
    assert server and client and client[1] == server[1]


def test_web_runs_gunicorn_and_keeps_data_in_volumes():
    compose = read("docker-compose.yml")
    assert "gunicorn config.wsgi:application" in compose
    for volume in ("media:/app/media", "backups:/app/backups_data", "pgdata:/var/lib/postgresql"):
        assert volume in compose
    assert "DB_HOST: db" in compose


def test_secrets_and_local_data_stay_out_of_the_image():
    ignored = read(".dockerignore").split()
    for entry in (".env", "venv", "media", "backups_data", ".git"):
        assert entry in ignored


def test_gunicorn_is_a_pinned_requirement():
    assert re.search(r"^gunicorn==\d", read("requirements.txt"), re.MULTILINE)


def test_entrypoint_migrates_and_collects_static():
    script = read("deploy/entrypoint.sh")
    assert "manage.py migrate --noinput" in script
    assert "manage.py collectstatic --noinput" in script
    assert script.startswith("#!/bin/sh") and "set -e" in script
