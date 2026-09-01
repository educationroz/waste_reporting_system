"""
Usage: python manage.py run_scheduled_backup
Wire this into cron (e.g. nightly at 2am) or Celery beat so backups
happen without anyone needing to click the button.
"""
from django.core.management.base import BaseCommand

from api_app.backup_utils import BackupError, cleanup_old_backups, create_backup


class Command(BaseCommand):
    help = 'Creates a scheduled database backup and prunes old ones.'

    def handle(self, *args, **options):
        try:
            result = create_backup()
            self.stdout.write(self.style.SUCCESS(f"Backup created: {result['file_name']} ({result['size_bytes']} bytes)"))
        except BackupError as exc:
            self.stderr.write(self.style.ERROR(f"Backup failed: {exc}"))
            return

        deleted = cleanup_old_backups()
        if deleted:
            self.stdout.write(f"Pruned {len(deleted)} old backup(s).")