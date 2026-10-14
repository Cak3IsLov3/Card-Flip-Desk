import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage, storages


class PrivatePhotoStorage(FileSystemStorage):
    """Lokale opslag zonder publieke URL.

    `url()` faalt bewust: bestanden gaan alleen via `inventory:photo_file`,
    die de eigenaar controleert. De locatie wordt bij elk gebruik uit de
    settings gelezen, zodat tests een tijdelijke map kunnen instellen.
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
        raise ValueError("Foto's hebben geen publieke URL; gebruik de view photo_file.")


def photo_storage():
    return storages["photos"]
