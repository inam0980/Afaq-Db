# Afaq ERP web application image (Gunicorn). See docs/INSTALL.md.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# pg_dump / pg_restore for `manage.py backup` must match the PostgreSQL server's
# major version (docker-compose.yml: postgres:18), so take them from the
# official PostgreSQL apt repository rather than Debian's older default.
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-common ca-certificates \
    && /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y \
    && apt-get install -y --no-install-recommends postgresql-client-18 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN chmod +x deploy/entrypoint.sh \
    && useradd --system --uid 1000 afaq \
    && mkdir -p /app/media /app/backups_data /app/staticfiles \
    && chown -R afaq /app/media /app/backups_data /app/staticfiles
USER afaq

EXPOSE 8000
ENTRYPOINT ["deploy/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120"]
