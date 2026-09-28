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


class SmartMediaCloudinaryStorage(MediaCloudinaryStorage):
    """
    MediaCloudinaryStorage that routes a file to the correct Cloudinary
    resource type based on its extension instead of forcing everything to
    'image'.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Map Cloudinary public_id -> resource_type for correct URL generation
        # since Cloudinary strips extensions from public_ids.
        self._resource_type_cache = {}

    def _get_resource_type(self, name):
        base = str(name).rsplit('/', 1)[-1]
        ext = base.rsplit('.', 1)[-1].lower() if '.' in base else ''
        if ext in _IMAGE_EXTENSIONS:
            return RESOURCE_TYPES['IMAGE']
        # Check cache for Cloudinary public_ids (no extension)
        if name in self._resource_type_cache:
            return self._resource_type_cache[name]
        return RESOURCE_TYPES['RAW']

    def _upload(self, name, content):
        # Get resource type BEFORE Cloudinary strips extension
        resource_type = self._get_resource_type(name)
        options = {'use_filename': True, 'resource_type': resource_type, 'tags': self.TAG}
        folder = os.path.dirname(name)
        if folder:
            options['folder'] = folder
        response = cloudinary.uploader.upload(content, **options)

        # Cache the resource_type for this public_id (Cloudinary returns it without extension)
        public_id = response.get('public_id')
        if public_id:
            self._resource_type_cache[public_id] = resource_type
        return response

    def _save(self, name, content):
        name = self._normalise_name(name)
        name = self._prepend_prefix(name)
        content = UploadedFile(content, name)
        response = self._upload(name, content)
        return response['public_id']

    def url(self, name):
        # Check cache first for correct resource_type
        if name in self._resource_type_cache:
            resource_type = self._resource_type_cache[name]
            name = self._prepend_prefix(name)
            cloudinary_resource = cloudinary.CloudinaryResource(name, default_resource_type=resource_type)
            return cloudinary_resource.url
        return super().url(name)