import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage, storages


class PrivatePhotoStorage(FileSystemStorage):
    """Local storage without a public URL.

    `url()` fails on purpose: files are only served through
    `inventory:photo_file`, which checks ownership. The location is read
    from settings on every use, so tests can point it at a temporary folder.
    """

    @property
    def base_location(self):
        return self._value_or_setting(self._location, settings.PRIVATE_MEDIA_ROOT)

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    @property
    def base_url(self):
        return None

    def url(self, name):
        raise ValueError("Photos have no public URL; use the photo_file view.")


def photo_storage():
    return storages["photos"]
