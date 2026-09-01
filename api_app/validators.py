import io
import logging

try:
    import magic
except Exception:  # noqa: BLE001 - libmagic is optional; fall back to byte sniffing
    magic = None
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.template.defaultfilters import filesizeformat
from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)

# Single source of truth for the per-photo size cap — settings.py sets
# MAX_PHOTO_SIZE and also derives DATA_UPLOAD_MAX_MEMORY_SIZE /
# FILE_UPLOAD_MAX_MEMORY_SIZE from it, so the request-body cap and the
# per-file cap can no longer drift apart the way they did before (5MB
# per-photo vs. a 5MB whole-request cap meant 2+ photos were always
# rejected before this validator ever ran).
MAX_IMAGE_SIZE = getattr(settings, 'MAX_PHOTO_SIZE', 3 * 1024 * 1024)
MAX_PDF_SIZE = 5 * 1024 * 1024     # 5 MB — unrelated to photo uploads, left as-is

# Resize/re-encode target for compress_image(). 1600px longest side is
# plenty for map markers, list thumbnails, and full-detail view — well
# above what any of those UI surfaces actually render at.
MAX_IMAGE_DIMENSION = 1600
COMPRESS_JPEG_QUALITY = 82

# Real MIME (sniffed from bytes) -> the Pillow format string(s) it must match.
ALLOWED_IMAGE_MIME_TO_PIL_FORMAT = {
    'image/jpeg': {'JPEG'},
    'image/png': {'PNG'},
    'image/gif': {'GIF'},
    'image/webp': {'WEBP'},
}


def _sniff_image_mime(header):
    if magic is not None:
        try:
            return magic.from_buffer(header, mime=True)
        except Exception:  # noqa: BLE001 - libmagic failure falls back to magic-byte sniffing
            logger.warning('[MIME] libmagic image sniff failed; falling back to magic bytes.')
    if header.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if header.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if header.startswith((b'GIF87a', b'GIF89a')):
        return 'image/gif'
    if header.startswith(b'RIFF') and len(header) >= 12 and header[8:12] == b'WEBP':
        return 'image/webp'
    return 'application/octet-stream'


def _sniff_pdf_mime(header):
    if magic is not None:
        try:
            return magic.from_buffer(header, mime=True)
        except Exception:  # noqa: BLE001 - libmagic failure falls back to magic-byte sniffing
            logger.warning('[MIME] libmagic pdf sniff failed; falling back to magic bytes.')
    if header.lstrip().startswith(b'%PDF-'):
        return 'application/pdf'
    return 'application/octet-stream'


def validate_image_file(uploaded_file):
    """
    Defence-in-depth image validator:
      1. Size cap.
      2. Real MIME type sniffed from file BYTES, not the
         filename extension — defeats renaming a .php/.html file to .jpg.
      3. Pillow actually opens and structurally verifies the file, and its
         detected format must match what the MIME sniff said — catches
         malformed / polyglot files that pass the magic-byte check but
         aren't a genuine, fully-decodable image.
    Raises ValidationError on failure. Always leaves the file pointer at 0
    afterwards so the normal upload flow can still read it.
    """
    if uploaded_file.size > MAX_IMAGE_SIZE:
        raise ValidationError(
            f'Image too large ({filesizeformat(uploaded_file.size)}). '
            f'Max size is {filesizeformat(MAX_IMAGE_SIZE)}.'
        )

    uploaded_file.seek(0)
    header = uploaded_file.read(2048)
    uploaded_file.seek(0)

    mime = _sniff_image_mime(header)
    if mime not in ALLOWED_IMAGE_MIME_TO_PIL_FORMAT:
        raise ValidationError(
            f'Unsupported or spoofed file type detected ({mime}). '
            f'Only JPEG, PNG, GIF, and WebP images are allowed.'
        )

    try:
        img = Image.open(uploaded_file)
        img.verify()  # structural integrity check (doesn't decode pixels)
        detected_format = img.format
    except (UnidentifiedImageError, OSError, ValueError):
        raise ValidationError('File is not a valid, readable image.')
    finally:
        uploaded_file.seek(0)

    if detected_format not in ALLOWED_IMAGE_MIME_TO_PIL_FORMAT[mime]:
        raise ValidationError(
            'File extension/content mismatch — the actual image format '
            'does not match its declared type.'
        )


def validate_pdf_file(uploaded_file):
    """
    Defence-in-depth PDF validator: size cap + real MIME sniff from file
    bytes + a check that the file actually starts with the %PDF- magic
    number, so a renamed .exe/.html can't sneak through as a "PDF".
    """
    if uploaded_file.size > MAX_PDF_SIZE:
        raise ValidationError(
            f'File too large ({filesizeformat(uploaded_file.size)}). '
            f'Max size is {filesizeformat(MAX_PDF_SIZE)}.'
        )

    uploaded_file.seek(0)
    header = uploaded_file.read(2048)
    uploaded_file.seek(0)

    mime = _sniff_pdf_mime(header)
    if mime != 'application/pdf':
        raise ValidationError(
            f'Unsupported or spoofed file type detected ({mime}). '
            f'Only PDF files are allowed.'
        )

    if not header.lstrip().startswith(b'%PDF-'):
        raise ValidationError('File does not appear to be a valid PDF.')


def sanitize_image(uploaded_file, quality=88):
    """
    Fully decodes the image and re-encodes it from scratch into a brand
    new file. This is the strongest layer: any bytes appended after the
    image's real end (a classic polyglot trick — e.g. a valid JPEG with
    an HTML/PHP payload appended after it) are dropped, since only the
    decoded pixel data survives, not the original byte stream.

    Call this AFTER validate_image_file() has confirmed the file is
    genuinely readable, from a serializer's validate_<field>, and use its
    return value in place of the original upload.
    """
    uploaded_file.seek(0)
    img = Image.open(uploaded_file)
    img_format = img.format  # capture before .load()/save() changes state
    img.load()

    # JPEG has no alpha channel — flatten if needed. PNG/GIF/WebP keep mode.
    if img_format == 'JPEG' and img.mode in ('RGBA', 'P'):
        img = img.convert('RGB')

    buffer = io.BytesIO()
    save_kwargs = {'format': img_format}
    if img_format == 'JPEG':
        save_kwargs.update(quality=quality, optimize=True)
    img.save(buffer, **save_kwargs)
    buffer.seek(0)

    original_name = getattr(uploaded_file, 'name', 'upload')
    return ContentFile(buffer.read(), name=original_name)


def compress_image(uploaded_file, max_dimension=MAX_IMAGE_DIMENSION, quality=COMPRESS_JPEG_QUALITY):
    """
    Resize (if needed) and re-encode an image for storage, so a raw 3-5MB
    phone JPEG isn't saved and then served at full size to every map
    marker and list thumbnail.

    Call this AFTER sanitize_image() — the input here should already be a
    clean, re-encoded copy, so this only needs to handle resizing/
    re-compression, not defending against malformed input.

    Images with an alpha channel (RGBA/LA/P) are kept as PNG to preserve
    transparency; everything else is re-encoded as JPEG for predictable,
    smaller file sizes.

    Note: like sanitize_image(), re-encoding here does not preserve EXIF
    (including GPS tags). That's fine for this project specifically —
    the frontend already extracts photo GPS client-side before upload and
    sends it separately as photo_latitude/photo_longitude (or the
    per-extra-photo equivalents), so nothing downstream reads EXIF GPS
    off the stored file.
    """
    uploaded_file.seek(0)
    img = Image.open(uploaded_file)
    img.load()

    is_alpha = img.mode in ('RGBA', 'LA', 'P')
    out_format = 'PNG' if is_alpha else 'JPEG'

    if out_format == 'JPEG' and img.mode != 'RGB':
        img = img.convert('RGB')

    width, height = img.size
    if max(width, height) > max_dimension:
        scale = max_dimension / float(max(width, height))
        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        img = img.resize(new_size, Image.LANCZOS)

    buffer = io.BytesIO()
    save_kwargs = {'format': out_format, 'optimize': True}
    if out_format == 'JPEG':
        save_kwargs['quality'] = quality
    img.save(buffer, **save_kwargs)
    buffer.seek(0)

    original_name = getattr(uploaded_file, 'name', 'upload')
    base_name = original_name.rsplit('.', 1)[0] if '.' in original_name else original_name
    ext = 'jpg' if out_format == 'JPEG' else 'png'

    return ContentFile(buffer.read(), name=f'{base_name}.{ext}')