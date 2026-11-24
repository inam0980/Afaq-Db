"""Nightly backup: `python manage.py backup` (schedule it with Windows Task
Scheduler or cron). `--list` shows existing backups."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from backups.services import BackupError, backup_dir, create_backup, list_backups, prune


def _size(num_bytes: int) -> str:
    return f"{num_bytes / (1024 * 1024):.1f} MB"


class Command(BaseCommand):
    help = "Back up the database and uploaded files, then delete old backups."

    def add_arguments(self, parser):
        parser.add_argument("--keep", type=int, default=settings.BACKUP_KEEP,
                            help="How many backups to keep (default: BACKUP_KEEP).")
        parser.add_argument("--no-media", action="store_true", help="Skip uploaded files.")
        parser.add_argument("--list", action="store_true", help="List backups and exit.")

    def handle(self, *args, keep, no_media, list, **options):
        if list:
            backups = list_backups()
            if not backups:
                self.stdout.write("No backups yet.")
            for b in backups:
                media = " + media" if b.media else ""
                self.stdout.write(f"{b.stamp}  {_size(b.size):>10}  {b.dump.name}{media}")
            return
        try:
            backup = create_backup(include_media=not no_media)
            removed = prune(keep)
        except BackupError as exc:
            self._log(f"FAILED {exc}")
            raise CommandError(str(exc)) from exc
        self._log(f"OK {backup.dump.name} {_size(backup.size)}")
        self.stdout.write(self.style.SUCCESS(f"Backup saved: {backup.dump} ({_size(backup.size)})"))
        if backup.media:
            self.stdout.write(f"Uploaded files: {backup.media}")
        if removed:
            self.stdout.write(f"Removed {len(removed)} old backup(s).")

    def _log(self, line):
        folder = backup_dir()
        folder.mkdir(parents=True, exist_ok=True)
        with open(folder / "backup.log", "a", encoding="utf-8") as log:
            log.write(f"{timezone.localtime().isoformat(timespec='seconds')} {line}\n")
