"""Restore a backup: `python manage.py restore 20261125-020000 --yes`.

This REPLACES all current data. A safety backup of the current data is made
first (unless --no-safety-backup), so a wrong restore can itself be undone."""

from django.core.management.base import BaseCommand, CommandError

from backups.services import BackupError, create_backup, find_backup, restore_backup


class Command(BaseCommand):
    help = "Replace the current database (and uploaded files) with a backup."

    def add_arguments(self, parser):
        parser.add_argument("backup", help="Backup stamp (see `manage.py backup --list`), file name or path.")
        parser.add_argument("--yes", action="store_true", help="Confirm: current data will be replaced.")
        parser.add_argument("--no-media", action="store_true", help="Restore the database only.")
        parser.add_argument("--no-safety-backup", action="store_true",
                            help="Do not back up the current data first.")

    def handle(self, *args, backup, yes, no_media, no_safety_backup, **options):
        try:
            chosen = find_backup(backup)
            if not yes:
                raise CommandError(
                    f"This replaces ALL current data with the backup from {chosen.stamp}. "
                    "Stop the web server, then run again with --yes."
                )
            if not no_safety_backup:
                safety = create_backup()
                self.stdout.write(f"Safety backup of the current data: {safety.dump}")
            restore_backup(chosen, include_media=not no_media)
        except BackupError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Restored backup {chosen.stamp}."))
