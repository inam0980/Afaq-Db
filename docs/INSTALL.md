# Afaq ERP — installation and operations guide

For whoever sets up and looks after the office server. Everything runs in
Docker on one machine: PostgreSQL 18, the Django application (Gunicorn) and
Nginx in front.

## 1. Server

- Ubuntu Server 24.04 LTS (recommended) or Windows 10/11 with Docker Desktop.
- 4 GB RAM, 2 CPU cores, 50 GB disk is plenty for this company size.
- A fixed IP address on the office network (e.g. `192.168.1.20`).
- A second place for backups: USB disk, NAS or cloud folder.

Install Docker Engine + the Compose plugin: <https://docs.docker.com/engine/install/ubuntu/>

## 2. First installation

```sh
git clone <repository-url> afaq-erp
cd afaq-erp
cp .env.example .env
nano .env
```

Fill in `.env`:

| Setting | What to put |
|---|---|
| `SECRET_KEY` | A long random value: `python3 -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `DEBUG` | `False` |
| `ALLOWED_HOSTS` | The server's IP and/or name, e.g. `192.168.1.20,erp.afaq.local` |
| `ADMIN_URL` | Something hard to guess, e.g. `manage-7f3k/` |
| `DB_PASSWORD` | A strong password (used by the database container) |
| `EMAIL_*` | The company mail server (needed for password-reset mails) |
| `COMPANY_*` | Real VAT number, CR number, Arabic name and address — printed on tax invoices and in the ZATCA QR code |
| `BACKUP_DIR`, `PG_BIN_DIR` | Leave empty — docker-compose sets them |

Start everything:

```sh
docker compose up -d --build
docker compose exec web python manage.py createsuperuser
```

Open `http://<server-ip>/` and sign in. Database tables are created and
updated automatically every time the web container starts.

## 3. HTTPS (recommended)

1. Get a certificate for the server name (company IT / Let's Encrypt / internal CA).
2. Copy `fullchain.pem` and `privkey.pem` into `deploy/certs/`.
3. In `deploy/nginx.conf` uncomment the `443` server block and the `return 301` line.
4. Set `HTTPS=True` in `.env`.
5. `docker compose up -d` (restarts with the new settings).

## 4. Backups — set this up on day one

`manage.py backup` saves the database **and** uploaded files (receipts,
iqama scans, leave documents) into the `backups` volume, checks that the dump
is readable, and keeps the newest 14 (`BACKUP_KEEP`). Administrators see a red
warning on the dashboard if no backup has run for 36 hours.

**Nightly at 02:00** (Ubuntu, `crontab -e` as the user that runs Docker):

```cron
0 2 * * * cd /home/afaq/afaq-erp && docker compose exec -T web python manage.py backup >> /var/log/afaq-backup.log 2>&1
30 2 * * * docker run --rm -v afaq-erp_backups:/from -v /mnt/usb/afaq:/to alpine sh -c "cp -u /from/* /to/"
```

The second line copies the backups to a USB disk / NAS mounted at
`/mnt/usb/afaq`. **A backup that only exists on the same server does not
survive a disk failure, theft or ransomware.**

Windows server without Docker: Task Scheduler → Create Basic Task → daily
02:00 → program `C:\afaq\venv\Scripts\python.exe`, arguments
`manage.py backup`, start in `C:\afaq`. Set `PG_BIN_DIR=C:/Program Files/PostgreSQL/18/bin`
and `BACKUP_DIR=D:/afaq-backups` in `.env`.

Useful commands:

```sh
docker compose exec web python manage.py backup --list      # what backups exist
docker compose exec web python manage.py backup             # make one now
```

## 5. Restoring a backup

Restoring **replaces all current data**. A safety backup of the current data
is taken first automatically.

```sh
docker compose stop nginx                                        # keep users out
docker compose exec web python manage.py backup --list
docker compose exec web python manage.py restore 20261125-020000 --yes
docker compose start nginx
```

Test a restore once a quarter on a spare machine — an untested backup is a hope, not a backup.

## 6. Updating to a new version

```sh
docker compose exec web python manage.py backup
git pull
docker compose up -d --build
```

## 7. Loading existing data

Sidebar → **Data import**: download the Excel template for employees,
customers or salary structures, fill it in, upload, check the preview and
confirm. A file with any error is not imported at all, so fix and re-upload.
Import employees first, then salary structures (they refer to employees by
ID / iqama number).

## 8. Troubleshooting

| Symptom | Check |
|---|---|
| "Bad Request (400)" | The address you typed is not in `ALLOWED_HOSTS`. |
| Page has no styling | `docker compose logs web` — `collectstatic` runs at start-up. |
| Backup fails: "server version mismatch" | `pg_dump` must be PostgreSQL 18 like the server (the image installs it). |
| Locked out after wrong passwords | Wait 15 minutes; the lock lifts by itself. Sign-in attempts are listed in Admin → Login events. |
| Health check | `curl http://<server-ip>/health/` → `{"status": "ok", "database": "ok"}` |

Logs: `docker compose logs -f web` (application), `docker compose logs -f nginx` (requests).
