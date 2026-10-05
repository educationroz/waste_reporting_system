"""
api_app/management/commands/warm_cloudinary_types.py

Heal + verify Cloudinary URL generation after the SmartMediaCloudinaryStorage
fix (image-vs-raw resource_type mismatch).

Background: Cloudinary strips extensions from public_ids, so every stored
name (e.g. ``waste_photos/photo-1791109490193_tsquqo``) is extensionless.
The old storage resolved those to ``raw`` whenever its process-local cache
was cold — i.e. after every restart/redeploy all previously uploaded photos
were served as unrenderable ``raw/upload`` URLs ("yesterday's data disappears
today"). The fixed storage resolves extensionless names deterministically
(extension -> registry -> upload_to prefix), so URLs are correct in every
process without any warm-up.

This command:
  1. walks every model field that stores an uploaded file (same list as
     audit_media.py),
  2. resolves each name's resource type through the storage backend and
     writes it to the persistent (Redis-backed in production) registry, so
     even exotic names keep working, and
  3. with --verify, HEAD-checks each file under its resolved type and
     reports genuinely missing files vs. type mismatches.

Read-only for the database: it only writes cache entries, never rows. Safe
to run on production.

    python manage.py warm_cloudinary_types
    python manage.py warm_cloudinary_types --verify
"""

from django.apps import apps
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

# Every model field that stores an uploaded file. Mirrors audit_media.py.
MODEL_FIELDS = [
    ('api_app.Driver', 'license_document'),
    ('api_app.WasteRequest', 'photo'),
    ('api_app.WasteRequestPhoto', 'photo'),
    ('api_app.Complaint', 'photo'),
    ('auth_app.User', 'profile_picture'),
]


class Command(BaseCommand):
    help = 'Warm the Cloudinary resource-type registry and optionally verify every referenced file.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--verify', action='store_true',
            help='HEAD-check each file under its resolved type and report missing/mismatched files.',
        )

    def handle(self, *args, **options):
        verify = options['verify']
        storage = default_storage
        resolve = getattr(storage, '_get_resource_type', None)
        remember = getattr(storage, '_remember_resource_type', None)

        total = warmed = 0
        ok = missing = mismatched = errors = 0

        for model_label, field_name in MODEL_FIELDS:
            try:
                model = apps.get_model(model_label)
            except LookupError:
                self.stdout.write(self.style.WARNING(f'{model_label}: model not found, skipped.'))
                continue
            qs = model.objects.exclude(**{f'{field_name}__isnull': True}).exclude(
                **{field_name: ''})
            for obj in qs.only('id', field_name).iterator(chunk_size=500):
                name = getattr(obj, field_name).name
                if not name or name.startswith('defaults/'):
                    continue
                total += 1
                try:
                    resource_type = resolve(name) if resolve else 'image'
                except Exception as exc:  # noqa: BLE001 - report, keep warming the rest
                    errors += 1
                    self.stdout.write(self.style.WARNING(
                        f'{model_label} #{obj.pk} {field_name}={name}: resolve error: {exc}'))
                    continue
                if remember:
                    try:
                        remember(name, resource_type)
                        warmed += 1
                    except Exception:  # noqa: BLE001, S110 - cache write is best-effort
                        pass
                if verify:
                    status = self._verify(storage, name, resource_type)
                    if status == 'ok':
                        ok += 1
                    elif status == 'mismatch':
                        mismatched += 1
                        self.stdout.write(self.style.WARNING(
                            f'MISMATCH {model_label} #{obj.pk} {field_name}={name}: '
                            f'not reachable as {resource_type}.'))
                    elif status == 'missing':
                        missing += 1
                        self.stdout.write(self.style.WARNING(
                            f'MISSING {model_label} #{obj.pk} {field_name}={name}.'))
                    else:
                        errors += 1

        summary = f'Done: {total} reference(s) seen, {warmed} registry-written.'
        if verify:
            summary += f' Verify: {ok} ok, {mismatched} mismatched, {missing} missing, {errors} errors.'
        self.stdout.write(self.style.SUCCESS(summary))

    @staticmethod
    def _verify(storage, name, resource_type):
        """HEAD the file under its resolved type, then the alternate type.

        Returns 'ok' | 'mismatch' (exists, but under the other type) |
        'missing' | 'error'.
        """
        try:
            if storage.exists(name):
                return 'ok'
        except Exception:  # noqa: BLE001, S110 - fall through to the alternate-type probe
            pass
        try:
            import cloudinary
            other = 'raw' if resource_type == 'image' else 'image'
            prefixed = storage._prepend_prefix(name) if hasattr(storage, '_prepend_prefix') else name
            url = cloudinary.CloudinaryResource(
                prefixed, default_resource_type=other,
            ).url
            import requests
            response = requests.head(url, timeout=10)
            if response.status_code == 200:
                return 'mismatch'
            if response.status_code == 404:
                return 'missing'
            return 'error'
        except Exception:  # noqa: BLE001 - network/auth glitch; report as error
            return 'error'
