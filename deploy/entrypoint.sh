#!/bin/sh
# Runs on every start of the web container: bring the database schema up to
# date, collect static files for Nginx, then start the given command (Gunicorn).
set -e

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@"
