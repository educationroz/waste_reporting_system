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

from cloudinary_storage.storage import RESOURCE_TYPES, MediaCloudinaryStorage

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

    def _get_resource_type(self, name):
        base = str(name).rsplit('/', 1)[-1]
        ext = base.rsplit('.', 1)[-1].lower() if '.' in base else ''
        if ext in _IMAGE_EXTENSIONS:
            return RESOURCE_TYPES['IMAGE']
        return RESOURCE_TYPES['RAW']