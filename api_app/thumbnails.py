"""
api_app/thumbnails.py

On-demand image thumbnail generation.

Waste-report, complaint and profile photos are stored as a single "full"
image (capped by compress_image() at MAX_IMAGE_DIMENSION, default 1600px).
List/map UI renders those same files at 36-90px, so every list page loaded a
full 1-3MB file per row just to paint a 48px thumbnail. This module creates
(once, lazily) a small resized copy per (image, size) and returns its URL —
bandwidth and storage drop dramatically, and the copy is cached in the same
storage backend as the source (local FileSystemStorage now, S3 later), so it
needs no extra serving infrastructure.

Storage-agnostic: operates through the FieldFile's storage, so it works with
any STORAGES backend.

Concurrency: generating the same thumbnail from two requests at once is
benign (last writer wins, both get a valid image). A process-local lock
dedupes the common duplicate work; cross-process duplication is limited to a
one-time cost per unique file+size.
"""

import hashlib
import io
import logging
import threading

from PIL import Image

logger = logging.getLogger(__name__)

THUMBNAIL_SIZES = {}

_locks = {}

# Sources already reported missing (per-process): a dangling DB reference
# would otherwise log an identical WARNING on every page render that touches
# it. The audit command `manage.py audit_media` lists them all for cleanup.
_missing_logged = set()
_missing_lock = threading.Lock()


def _parse_size(size):
    """Parse 'WxH' (e.g. '100x100') into a (width, height) tuple."""
    if not size:
        return None
    size = str(size).lower().strip()
    try:
        w, h = size.split('x')
        return int(w), int(h)
    except (ValueError, TypeError):
        return None


def _target_name(field_name, size_key, source_name, extension=''):
    """Build a stable cache path inside MEDIA_ROOT/thumbnails/.

    ``extension`` (e.g. '.jpg') MUST be supplied for non-local backends:
    Cloudinary classifies uploads by filename extension, and an
    extensionless target would be stored as a ``raw`` resource whose URL no
    browser can render as an image.
    """
    digest = hashlib.sha1(
        f'{field_name}:{size_key}:{source_name}'.encode()
    ).hexdigest()[:16]
    base = source_name.rsplit('/', 1)[-1]
    # Strip any stale extension from the source tail so the digest-named
    # target carries exactly one, correct extension.
    if '.' in base:
        base = base.rsplit('.', 1)[0]
    return f'thumbnails/{size_key}/{digest}-{base}{extension}'


def _legacy_target_name(field_name, size_key, source_name):
    """Pre-fix target path (no extension) — used only to clean up the
    raw/upload thumbnails the old code produced."""
    digest = hashlib.sha1(
        f'{field_name}:{size_key}:{source_name}'.encode()
    ).hexdigest()[:16]
    base = source_name.rsplit('/', 1)[-1]
    return f'thumbnails/{size_key}/{digest}-{base}'


def _thumbnail_lock(target):
    return _locks.setdefault(target, threading.Lock())


def get_or_create_thumbnail(file_field, size='100x100'):
    """
    Return the storage-relative name of a resized copy of ``file_field``,
    creating (and caching) it on demand. Returns '' when generation isn't
    possible.

    ``file_field`` must expose .name and .storage (a FieldFile, or the
    _ThumbnailSource stand-in used by the API view).
    """
    if not file_field or not getattr(file_field, 'name', None):
        return ''

    dims = _parse_size(size)
    if dims is None:
        return file_field.name
    width, height = dims
    if width <= 0 or height <= 0:
        return file_field.name

    storage = file_field.storage
    source_name = file_field.name
    size_key = f'{width}x{height}'
    # Candidate targets, one per encodable format. The source mode decides
    # which one wins below; checking both first keeps the cache-hit path to
    # cheap exists() calls with no image decode.
    candidate_targets = {
        'JPEG': _target_name(source_name, size_key, source_name, '.jpg'),
        'PNG': _target_name(source_name, size_key, source_name, '.png'),
    }

    def _existing_target():
        for candidate in candidate_targets.values():
            try:
                if storage.exists(candidate):
                    return candidate
            except Exception:  # noqa: BLE001 - storage glitch; try next candidate
                logger.warning('[THUMB] storage.exists failed for %s', candidate)
        return ''

    hit = _existing_target()
    if hit:
        return hit

    lock = _thumbnail_lock(size_key + ':' + source_name)
    with lock:
        hit = _existing_target()
        if hit:
            return hit

        try:
            with storage.open(source_name, 'rb') as src:
                img = Image.open(src)
                img.load()
        except Exception as exc:  # noqa: BLE001 - any read/decode failure handled below
            # Distinguish "file gone" (dangling DB reference — e.g. uploads
            # lost in an ephemeral container, or a backend switch that
            # stranded files) from transient read errors. Gone files return ''
            # so templates render their placeholder instead of a broken image;
            # transient errors keep the original URL so the next page load
            # retries generation.
            try:
                source_missing = not storage.exists(source_name)
            except Exception:  # noqa: BLE001 - exists() itself glitched; treat as transient
                source_missing = False
            if source_missing:
                with _missing_lock:
                    first_sight = source_name not in _missing_logged
                    _missing_logged.add(source_name)
                if first_sight:
                    logger.warning(
                        '[THUMB] source file missing from storage: %s '
                        '(dangling reference — run `manage.py audit_media` to list all).',
                        source_name,
                    )
                return ''
            logger.warning('[THUMB] could not open source %s: %s', source_name, exc)
            return source_name  # fall back to the original on transient failure

        is_alpha = img.mode in ('RGBA', 'LA', 'P')
        out_format = 'PNG' if is_alpha else 'JPEG'
        target = candidate_targets[out_format]

        src_w, src_h = img.size
        target_ratio = width / float(height)
        src_ratio = src_w / float(src_h)

        if src_ratio > target_ratio:
            new_h = src_h
            new_w = round(new_h * target_ratio)
        else:
            new_w = src_w
            new_h = round(new_w / target_ratio)

        left = (src_w - new_w) // 2
        top = (src_h - new_h) // 2
        img = img.crop((left, top, left + new_w, top + new_h))
        img = img.resize((width, height), Image.LANCZOS)

        if out_format == 'JPEG' and img.mode != 'RGB':
            img = img.convert('RGB')

        buffer = io.BytesIO()
        save_kwargs = {'format': out_format, 'optimize': True}
        if out_format == 'JPEG':
            save_kwargs['quality'] = 75
        img.save(buffer, **save_kwargs)
        buffer.seek(0)

        try:
            stored_name = storage.save(target, buffer)
        except Exception as exc:  # noqa: BLE001 - fall back to the original on any failure
            logger.warning('[THUMB] storage.save failed for %s: %s', target, exc)
            return file_field.name
        # Best-effort cleanup of the pre-fix artefacts: the old code saved
        # the same thumbnail under an extensionless name, which Cloudinary
        # stored as an unrenderable `raw` resource. The orphan lives under
        # the RAW type, so plain exists()/delete() (which now correctly
        # resolve thumbnails/ to IMAGE) cannot see it — the storage backend
        # exposes a raw-type delete for exactly this case. Ignore all
        # errors: the orphan is harmless, just wasted bytes.
        try:
            legacy = _legacy_target_name(source_name, size_key, source_name)
            delete_raw = getattr(storage, 'delete_raw_resource', None)
            if legacy != target and callable(delete_raw):
                delete_raw(legacy)
        except Exception:  # noqa: BLE001, S110 - cleanup must never break serving
            pass
        return stored_name


def generate_thumbnail(file_field, size='100x100'):
    """
    Return a public URL for a lazily-generated, cached thumbnail of
    ``file_field`` (a Django FieldFile). Returns '' (safe to inline in
    src="") when generation isn't possible, so templates never break.
    """
    if not file_field or not getattr(file_field, 'name', None):
        return ''

    stored = get_or_create_thumbnail(file_field, size)
    if not stored:
        return ''
    try:
        return file_field.storage.url(stored)
    except Exception as exc:  # noqa: BLE001 - template-safe fallback returns ''
        logger.warning('[THUMB] storage.url failed for %s: %s', stored, exc)
        return ''