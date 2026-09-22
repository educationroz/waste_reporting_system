"""
api_app/management/commands/migrate_to_cloudinary.py

One-off migration for data written while MEDIA_BACKEND=local.

Reads every media file still reachable through the OLD local FileSystemStorage
(MEDIA_ROOT) and re-uploads it into the DEFAULT storage (which must be
Cloudinary) under the same relative path, then updates each model row to the
new cloudinary file name so existing reports/complaints/profiles keep their
photos after switching backends.

Safe to run more than once:
- rows whose file already has a Cloudinary URL are skipped,
- rows whose local file is missing are logged and skipped (they were probably
  already migrated, or the ephemeral container lost them).

Run AFTER switching MEDIA_BACKEND=cloudinary, from an environment that still
has a copy of the old media folder:
    python manage.py migrate_to_cloudinary [--dry-run]
"""

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.storage.filesystem import FileSystemStorage
from django.core.management.base import BaseCommand

# Every model field that stores an uploaded file, as (app_label.ModelName,
# field_name). Mirrors api_app/models.py + auth_app/models.py.
MODEL_FIELDS = [
    ('api_app.Driver', 'license_document'),
    ('api_app.WasteRequest', 'photo'),
    ('api_app.WasteRequestPhoto', 'photo'),
    ('api_app.Complaint', 'photo'),
    ('auth_app.User', 'profile_picture'),
]


class Command(BaseCommand):
    help = 'Copy media files from local disk into the active (Cloudinary) storage.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would be migrated without uploading anything.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        if settings.MEDIA_BACKEND != 'cloudinary':
            self.stdout.write(
                self.style.WARNING(
                    'MEDIA_BACKEND is not "cloudinary"; nothing to migrate.'
                )
            )
            return

        # The OLD storage: files written while MEDIA_BACKEND=local.
        local = FileSystemStorage(location=settings.MEDIA_ROOT)

        total = uploaded = skipped = missing = 0

        for model_path, field_name in MODEL_FIELDS:
            app_label, model_name = model_path.split('.')
            model = self._get_model(app_label, model_name)
            if model is None:
                continue

            for instance in model.objects.all().iterator():
                field = getattr(instance, field_name)
                old_name = field.name
                if not old_name:
                    continue
                total += 1

                # Already on Cloudinary? Only migrate files that still resolve
                # against the local disk.
                if not local.exists(old_name):
                    missing += 1
                    self.stdout.write(
                        f'- {model_path}.{instance.pk} [{field_name}] '
                        f'"{old_name}": local file missing, skipped.'
                    )
                    continue

                if dry_run:
                    self.stdout.write(
                        f'  {model_path}.{instance.pk} [{field_name}] '
                        f'"{old_name}" -> would upload to Cloudinary.'
                    )
                    uploaded += 1
                    continue

                try:
                    with local.open(old_name, 'rb') as src:
                        data = src.read()
                    new_name = default_storage.save(old_name, ContentFile(data))
                except Exception as exc:  # noqa: BLE001 - keep migrating the rest
                    self.stdout.write(
                        self.style.ERROR(
                            f'! {model_path}.{instance.pk} [{field_name}] '
                            f'"{old_name}" FAILED: {exc}'
                        )
                    )
                    continue

                save_kwargs = {'update_fields': [field_name]}
                field.name = new_name
                instance.save(**save_kwargs)
                uploaded += 1
                self.stdout.write(
                    f'+ {model_path}.{instance.pk} [{field_name}] '
                    f'"{old_name}" -> "{new_name}".'
                )

        verb = 'would be uploaded' if dry_run else 'uploaded'
        self.stdout.write(
            self.style.SUCCESS(
                f'Done: {total} file(s) seen, {uploaded} {verb}, '
                f'{missing} already/not-on-local skipped.'
            )
        )

    @staticmethod
    def _get_model(app_label, model_name):
        try:
            from django.apps import apps
            return apps.get_model(app_label, model_name)
        except LookupError:
            return None