import io
import magic
from PIL import Image, UnidentifiedImageError
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.template.defaultfilters import filesizeformat

MAX_IMAGE_SIZE = 5 * 1024 * 1024   # 5 MB
MAX_PDF_SIZE = 5 * 1024 * 1024     # 5 MB

# Real MIME (sniffed from bytes) -> the Pillow format string(s) it must match.
ALLOWED_IMAGE_MIME_TO_PIL_FORMAT = {
    'image/jpeg': {'JPEG'},
    'image/png': {'PNG'},
    'image/gif': {'GIF'},
    'image/webp': {'WEBP'},
}


def validate_image_file(uploaded_file):
    """
    Defence-in-depth image validator:
      1. Size cap.
      2. Real MIME type sniffed from file BYTES (python-magic), not the
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

    mime = magic.from_buffer(header, mime=True)
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

    mime = magic.from_buffer(header, mime=True)
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