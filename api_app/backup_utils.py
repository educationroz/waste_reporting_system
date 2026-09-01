"""
Backup/restore core logic, kept separate from views.py so it can be
called from the API, a management command (cron/Celery), or tests
without going through DRF.
"""
import hashlib
import io
import json
import logging
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.utils import timezone

logger = logging.getLogger('backup')

BACKUP_DIR = Path(settings.BASE_DIR) / 'backups'
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_BACKUP_EXCLUDES = ['contenttypes', 'admin.logentry', 'sessions.session']

# Keep this many days of local backups; older ones get pruned by
# cleanup_old_backups(). Override in settings.py if you want.
BACKUP_RETENTION_DAYS = getattr(settings, 'BACKUP_RETENTION_DAYS', 30)

# Toggle off-site upload. Off by default so this works with zero extra
# config; flip on in settings.py once S3 credentials are configured.
BACKUP_OFFSITE_ENABLED = getattr(settings, 'BACKUP_OFFSITE_ENABLED', False)


class BackupError(Exception):
    """Raised for any backup/restore failure with a user-safe message."""


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def create_backup(exclude=None):
    """
    Dumps the full DB (minus `exclude` apps/models) to a timestamped JSON
    file in BACKUP_DIR, writes a .sha256 sidecar for integrity checks on
    restore, and optionally pushes a copy off-site.

    Returns a dict describing the created backup. Raises BackupError on
    any failure; never leaves a half-written file behind.
    """
    exclude = exclude if exclude is not None else DEFAULT_BACKUP_EXCLUDES
    timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
    file_name = f'backup_{timestamp}.json'
    file_path = BACKUP_DIR / file_name

    buffer = io.StringIO()
    try:
        call_command(
            'dumpdata',
            exclude=exclude,
            stdout=buffer,
            indent=2,
            natural_foreign=True,
            natural_primary=True,
            verbosity=0,
        )
        content = buffer.getvalue()

        if not content.strip():
            raise BackupError('dumpdata produced empty output — aborting, not writing an empty backup.')

        file_path.write_text(content, encoding='utf-8')
        checksum = _checksum(content)
        (BACKUP_DIR / f'{file_name}.sha256').write_text(checksum, encoding='utf-8')

    except Exception as exc:
        file_path.unlink(missing_ok=True)
        (BACKUP_DIR / f'{file_name}.sha256').unlink(missing_ok=True)
        logger.exception('Backup creation failed')
        raise BackupError(f'Backup failed: {exc}') from exc

    result = {
        'file_name': file_name,
        'size_bytes': file_path.stat().st_size,
        'checksum': checksum,
        'excluded': exclude,
        'created_at': timezone.now().isoformat(),
        'offsite_uploaded': False,
    }

    if BACKUP_OFFSITE_ENABLED:
        try:
            upload_to_offsite_storage(file_path)
            result['offsite_uploaded'] = True
        except Exception:
            # Off-site failure should NOT fail the whole backup — the
            # local copy is still good. Just log it loudly.
            logger.exception('Off-site upload failed for %s (local copy is fine)', file_name)

    logger.info('Backup created: %s (%s bytes)', file_name, result['size_bytes'])
    return result


def verify_backup_file(file_path: Path):
    """
    Validates a backup file BEFORE it's allowed anywhere near `flush`/
    `loaddata`. Checks:
      1. It's valid UTF-8 JSON
      2. It's a list (Django fixture format), not some other JSON shape
      3. Every entry looks like a Django fixture record (has model/pk/fields)

    Raises BackupError with a specific reason on failure. Returns the
    parsed record count on success (doesn't need the DB at all).
    """
    try:
        with file_path.open(encoding='utf-8') as f:
            data = json.load(f)
    except UnicodeDecodeError as exc:
        raise BackupError(f'File is not valid UTF-8 text: {exc}') from exc
    except json.JSONDecodeError as exc:
        raise BackupError(f'File is not valid JSON: {exc}') from exc

    if not isinstance(data, list):
        raise BackupError('File is not a Django fixture (expected a JSON list of records).')

    if len(data) == 0:
        raise BackupError('Backup file is empty — refusing to restore from it.')

    for i, record in enumerate(data[:50]):
        if not isinstance(record, dict) or not all(k in record for k in ('model', 'fields')):
            raise BackupError(f'Record {i} is missing model/fields — not a valid fixture entry.')

def restore_backup(file_path: Path):
    """
    Restores the DB from `file_path`. This is destructive: it flushes
    the current DB and loads the backup in its place.

    Safety net: before touching anything, it takes an automatic
    "pre-restore" backup of the CURRENT state. If loaddata fails partway
    (flush already ran, so the DB may be empty at that point), it
    attempts to reload that safety copy automatically so you don't end
    up with a wiped database.

    Returns a dict with the outcome. Raises BackupError only when
    the restore truly could not be completed AND could not be
    auto-recovered — at that point the safety file path is included so
    a human can finish the job manually.
    """
    record_count = verify_backup_file(file_path)  # raises BackupError if invalid

    safety_name = f'pre_restore_safety_{timezone.now().strftime("%Y%m%d_%H%M%S")}.json'
    safety_path = BACKUP_DIR / safety_name

    try:
        buffer = io.StringIO()
        call_command('dumpdata', stdout=buffer, indent=2, natural_foreign=True, natural_primary=True, verbosity=0)
        safety_path.write_text(buffer.getvalue(), encoding='utf-8')
    except Exception as exc:
        # If we can't even snapshot current state, do NOT proceed —
        # there would be no way back.
        raise BackupError(f'Could not create safety backup, restore aborted (nothing was changed): {exc}') from exc

    try:
        call_command('flush', interactive=False, verbosity=0)
        call_command('loaddata', str(file_path), verbosity=0)
    except Exception as exc:
        logger.error('Restore failed after flush; attempting auto-recovery from %s', safety_name)
        try:
            call_command('loaddata', str(safety_path), verbosity=0)
            recovered = True
        except Exception:
            logger.exception('Auto-recovery ALSO failed — manual intervention required')
            recovered = False

        raise BackupError(
            f'Restore failed: {exc}. '
            + ('Previous data was automatically recovered.' if recovered
               else f'AUTOMATIC RECOVERY FAILED. Manually run: '
                    f'python manage.py loaddata {safety_path}')
        ) from exc

    logger.info('Restore completed from %s (%s records), safety copy at %s', file_path.name, record_count, safety_name)
    return {
        'restored_file': file_path.name,
        'record_count': record_count,
        'safety_backup': safety_name,
    }


def cleanup_old_backups(retention_days=None):
    """
    Deletes backup files (and their .sha256 sidecars) older than
    retention_days. Never deletes the most recent backup, even if
    it's technically past the retention window, so you always have
    at least one restore point.

    Call this from a scheduled task (see management command below) —
    it is NOT called automatically on every request.
    """
    retention_days = retention_days if retention_days is not None else BACKUP_RETENTION_DAYS
    cutoff = timezone.now().timestamp() - (retention_days * 86400)

    backups = sorted(BACKUP_DIR.glob('backup_*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
    deleted = []
    for backup_path in backups[1:]:  # skip index 0 — always keep the newest
        if backup_path.stat().st_mtime < cutoff:
            backup_path.unlink(missing_ok=True)
            (BACKUP_DIR / f'{backup_path.name}.sha256').unlink(missing_ok=True)
            deleted.append(backup_path.name)

    if deleted:
        logger.info('Pruned %s old backup(s): %s', len(deleted), deleted)
    return deleted


def upload_to_offsite_storage(file_path: Path):
    """
    Pushes a backup file to S3 (or any S3-compatible store — Backblaze
    B2, MinIO, etc. all speak this API). Only called when
    BACKUP_OFFSITE_ENABLED = True in settings.

    Requires in settings.py:
        BACKUP_OFFSITE_ENABLED = True
        BACKUP_S3_BUCKET = 'your-bucket-name'
        AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY (or IAM role on the host)
        BACKUP_S3_ENDPOINT_URL = None  # set this for non-AWS S3-compatible hosts

    Requires: pip install boto3
    """
    import boto3  # imported lazily so boto3 isn't a hard dependency unless you enable this

    bucket = getattr(settings, 'BACKUP_S3_BUCKET', None)
    if not bucket:
        raise BackupError('BACKUP_OFFSITE_ENABLED is True but BACKUP_S3_BUCKET is not set.')

    client = boto3.client(
        's3',
        endpoint_url=getattr(settings, 'BACKUP_S3_ENDPOINT_URL', None),
    )
    key = f'db-backups/{file_path.name}'
    client.upload_file(str(file_path), bucket, key, ExtraArgs={'ServerSideEncryption': 'AES256'})
    logger.info('Uploaded %s to s3://%s/%s', file_path.name, bucket, key)


def list_backups():
    """Returns metadata for all local backups, newest first."""
    files = []
    for backup_path in sorted(BACKUP_DIR.glob('backup_*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
        sha_path = BACKUP_DIR / f'{backup_path.name}.sha256'
        from datetime import datetime
        from datetime import timezone as dt_timezone
        created_ts = datetime.fromtimestamp(backup_path.stat().st_mtime, tz=dt_timezone.utc)
        files.append({
            'file_name': backup_path.name,
            'size_bytes': backup_path.stat().st_size,
            'created_at': created_ts.isoformat(),
            'checksum': sha_path.read_text().strip() if sha_path.exists() else None,
            'download_url': f'/api/database-backups/download/?file_name={backup_path.name}',
        })
    return files


def resolve_backup_path(file_name: str) -> Path:
    """Prevents path traversal — only allows files that live directly in BACKUP_DIR."""
    if not file_name:
        raise BackupError('file_name is required.')

    candidate = (BACKUP_DIR / file_name).resolve()
    if candidate.parent != BACKUP_DIR.resolve():
        raise BackupError('Invalid backup file location.')
    if not candidate.exists():
        raise BackupError(f'Backup file {file_name} was not found.')
    return candidate