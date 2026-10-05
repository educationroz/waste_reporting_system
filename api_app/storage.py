"""
api_app/storage.py

Cloudinary media storage backend.

django-cloudinary-storage ships three fixed storages: images only
(MediaCloudinaryStorage), raw files only (RawMediaCloudinaryStorage) and videos
only (VideoMediaCloudinaryStorage). A single storage must be able to hold BOTH
report/complaint/profile photos (Cloudinary "image" resources, so URLs come off
the CDN optimised) AND the driver licence PDF (Cloudinary "raw" resources —
uploading a PDF as an image resource is rejected by Cloudinary).

This backend picks the Cloudinary resource type from the file extension, so one
STORAGES['default'] backend correctly serves every media file the app stores.
Everything else (URL building via https + CDN, HEAD-based exists(), download-
based open()) is inherited from MediaCloudinaryStorage.
"""
import os
from cloudinary_storage.storage import RESOURCE_TYPES, MediaCloudinaryStorage
import cloudinary
from django.core.files.uploadedfile import UploadedFile

_IMAGE_EXTENSIONS = {
    'jpg', 'jpeg', 'jpe', 'jfif', 'png', 'gif', 'webp', 'bmp',
    'tif', 'tiff', 'ico', 'avif', 'apng', 'svg', 'svgz',
}

# Cloudinary strips extensions from public_ids, so every name the database
# stores (e.g. `waste_photos/photo-1791109490193_tsquqo`) is extensionless.
# These prefixes disambiguate those names without any network call: they
# mirror every upload_to in the project (plus thumbnails/ and branding/,
# which are always generated images). driver_licenses/ is the only prefix
# that holds non-image (PDF) uploads.
_IMAGE_PREFIXES = (
    'waste_photos/',
    'complaint_photos/',
    'profile_pics/',
    'thumbnails/',
    'branding/',
    'defaults/',
)
_RAW_PREFIXES = (
    'driver_licenses/',
)

# Django-cache key prefix for the persistent public_id -> resource_type
# registry written at upload time (see _upload). Unlike the process-local
# dict below, this survives restarts/redeploys when the cache backend is
# shared (Redis in production).
_RESOURCE_TYPE_CACHE_KEY_PREFIX = 'cloudinary_res_type:'
_RESOURCE_TYPE_CACHE_TIMEOUT = 60 * 60 * 24 * 30  # 30 days; a type never changes


class SmartMediaCloudinaryStorage(MediaCloudinaryStorage):
    """
    MediaCloudinaryStorage that routes a file to the correct Cloudinary
    resource type based on its extension instead of forcing everything to
    'image'.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Fast process-local map Cloudinary public_id -> resource_type,
        # populated at upload time. It does NOT survive restarts, so it is
        # only layer 2 of _get_resource_type() — never the sole source of
        # truth for extensionless stored names (see below).
        self._resource_type_cache = {}

    def _registry_key(self, name):
        """Normalise a name to its registry form: the storage prefix
        (``media/`` from MEDIA_URL — prepended by _save(), so every stored
        public_id carries it) is stripped so upload-time, url()-time and
        DB-stored names all map to one key (``waste_photos/x``)."""
        key = str(name)
        try:
            prefix = self._normalize_path(self._get_prefix().lstrip('/'))
        except Exception:
            prefix = ''
        if prefix and key.startswith(prefix):
            key = key[len(prefix):]
        return key

    def _get_resource_type(self, name):
        key = str(name)
        base = key.rsplit('/', 1)[-1]
        ext = base.rsplit('.', 1)[-1].lower() if '.' in base else ''
        if ext:
            # A name that still carries an extension is unambiguous.
            if ext in _IMAGE_EXTENSIONS:
                return RESOURCE_TYPES['IMAGE']
            return RESOURCE_TYPES['RAW']
        # Extensionless Cloudinary public_id — resolve without guessing:
        # 1. process-local upload registry (this process uploaded it), then
        # 2. persistent Django-cache registry (an earlier process uploaded
        #    it; survives restarts when the cache backend is shared), then
        # 3. upload_to prefix heuristic (deterministic; covers every writer
        #    in the project), defaulting to IMAGE — the legacy behaviour and
        #    the common case (photos outnumber PDFs by orders of magnitude).
        # The old code fell through to RAW here, which is why every photo
        # broke with raw/upload URLs after each restart/redeploy.
        norm = self._registry_key(key)
        if norm in self._resource_type_cache:
            return self._resource_type_cache[norm]
        try:
            from django.core.cache import cache
            cached = cache.get(_RESOURCE_TYPE_CACHE_KEY_PREFIX + norm)
            if cached in (RESOURCE_TYPES['IMAGE'], RESOURCE_TYPES['RAW'], RESOURCE_TYPES['VIDEO']):
                self._resource_type_cache[norm] = cached
                return cached
        except Exception:
            pass
        lowered = norm.lower()
        for prefix in _RAW_PREFIXES:
            if lowered.startswith(prefix):
                return RESOURCE_TYPES['RAW']
        return RESOURCE_TYPES['IMAGE']

    def _remember_resource_type(self, public_id, resource_type):
        if not public_id or resource_type not in (
            RESOURCE_TYPES['IMAGE'], RESOURCE_TYPES['RAW'], RESOURCE_TYPES['VIDEO']
        ):
            return
        norm = self._registry_key(public_id)
        self._resource_type_cache[norm] = resource_type
        try:
            from django.core.cache import cache
            cache.set(
                _RESOURCE_TYPE_CACHE_KEY_PREFIX + norm,
                resource_type,
                _RESOURCE_TYPE_CACHE_TIMEOUT,
            )
        except Exception:
            pass

    def _upload(self, name, content):
        # Get resource type BEFORE Cloudinary strips extension
        resource_type = self._get_resource_type(name)
        options = {'use_filename': True, 'resource_type': resource_type, 'tags': self.TAG}
        folder = os.path.dirname(name)
        if folder:
            options['folder'] = folder
        response = cloudinary.uploader.upload(content, **options)

        # Remember the resource_type for this public_id (Cloudinary returns
        # it without extension) in both the process-local and the persistent
        # registry so url()/exists()/delete() stay correct after restarts.
        self._remember_resource_type(response.get('public_id'), resource_type)
        return response

    def _save(self, name, content):
        name = self._normalise_name(name)
        name = self._prepend_prefix(name)
        content = UploadedFile(content, name)
        response = self._upload(name, content)
        return response['public_id']

    def delete_raw_resource(self, name):
        """Best-effort destroy of a resource stored under the RAW type.

        Used to clean up pre-fix artefacts (e.g. extensionless thumbnails
        the old code uploaded as raw). Returns True on success, False
        otherwise — never raises.
        """
        try:
            response = cloudinary.uploader.destroy(
                self._prepend_prefix(str(name)), invalidate=True, resource_type=RESOURCE_TYPES['RAW']
            )
            return isinstance(response, dict) and response.get('result') == 'ok'
        except Exception:
            return False

    def url(self, name):
        # Check cache first for correct resource_type (registry keys are
        # prefix-stripped; the DB/stored name may carry the media/ prefix).
        norm = self._registry_key(name)
        if norm in self._resource_type_cache:
            resource_type = self._resource_type_cache[norm]
            name = self._prepend_prefix(str(name))
            cloudinary_resource = cloudinary.CloudinaryResource(name, default_resource_type=resource_type)
            return cloudinary_resource.url
        return super().url(name)