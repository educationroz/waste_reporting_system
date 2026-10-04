"""
api_app/management/commands/audit_media.py

Report uploaded files whose database reference no longer exists in storage
(dangling references). This is the usual cause of "photo shows on my device
but not on another" and broken avatars: the row points at e.g.
profile_pics/3120_uuu5nm but the file is gone — lost from an ephemeral
container disk, deleted by hand, or stranded by a MEDIA_BACKEND switch
(local <-> cloudinary <-> s3).

Read-only by default. Two opt-in repairs:

- --fix-prefix: some rows store names like `media/waste_photos/x.jpg`
  (a `media/` prefix baked in while MEDIA_ROOT pointed elsewhere). When the
  unprefixed path exists in storage, the row is rewritten to it.
- --clear: missing references are nulled on the model row so pages render
  their placeholder instead of a dead image URL:

    python manage.py audit_media
    python manage.py audit_media --fix-prefix
    python manage.py audit_media --clear
"""

from django.apps import apps
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

# Every model field that stores an uploaded file, as
# (app_label.ModelName, field_name). Mirrors api_app/models.py +
# auth_app/models.py (same list as migrate_to_cloudinary.py).
MODEL_FIELDS = [
    ('api_app.Driver', 'license_document'),
    ('api_app.WasteRequest', 'photo'),
    ('api_app.WasteRequestPhoto', 'photo'),
    ('api_app.Complaint', 'photo'),
    ('auth_app.User', 'profile_picture'),
]


class Command(BaseCommand):
    help = 'List uploaded files referenced in the DB but missing from storage.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear', action='store_true',
            help='Null out references whose files are missing.',
        )
        parser.add_argument(
            '--fix-prefix', action='store_true',
            help="Rewrite names like 'media/x' to 'x' when the unprefixed file exists.",
        )

    def handle(self, *args, **options):
        clear = options['clear']
        fix_prefix = options['fix_prefix']
        total_missing = 0
        total_checked = 0
        total_fixed = 0

        for model_label, field_name in MODEL_FIELDS:
            model = apps.get_model(model_label)
            missing = []
            qs = model.objects.exclude(**{f'{field_name}__isnull': True}).exclude(
                **{field_name: ''})
            for obj in qs.only('id', field_name).iterator(chunk_size=500):
                name = getattr(obj, field_name).name
                if not name or name.startswith('defaults/'):
                    continue
                total_checked += 1
                try:
                    exists = default_storage.exists(name)
                except Exception as exc:  # noqa: BLE001 - report, don't crash the audit
                    self.stdout.write(self.style.WARNING(
                        f'{model_label} #{obj.pk} {field_name}={name}: storage error: {exc}'))
                    continue
                if not exists:
                    missing.append((obj.pk, name))

            still_missing = []
            for pk, name in missing:
                total_missing += 1
                fixed = False
                if fix_prefix and (name.startswith('media/') or name.startswith('media\\')):
                    stripped = name[6:]
                    try:
                        if default_storage.exists(stripped):
                            model.objects.filter(pk=pk).update(**{field_name: stripped})
                            total_fixed += 1
                            fixed = True
                            self.stdout.write(self.style.SUCCESS(
                                f'FIXED {model_label} #{pk} {field_name}: {name} -> {stripped}'))
                    except Exception as exc:  # noqa: BLE001 - report, keep auditing
                        self.stdout.write(self.style.WARNING(
                            f'{model_label} #{pk}: prefix-fix check failed: {exc}'))
                if not fixed:
                    still_missing.append(pk)
                    self.stdout.write(self.style.WARNING(
                        f'MISSING {model_label} #{pk} {field_name}={name}'))

            if clear and still_missing:
                model.objects.filter(pk__in=still_missing).update(**{field_name: None})
                self.stdout.write(self.style.SUCCESS(
                    f'Cleared {len(still_missing)} dangling reference(s) on {model_label}.{field_name}.'))

        if not total_missing:
            self.stdout.write(self.style.SUCCESS(
                f'All {total_checked} referenced file(s) exist in storage.'))
        else:
            remaining = total_missing - total_fixed
            self.stdout.write(
                f'{total_missing} of {total_checked} referenced file(s) missing '
                f'({total_fixed} prefix-fixed, {remaining} still dangling). '
                + ('' if remaining == 0 else 'Re-run with --clear to null the dangling references.'))
