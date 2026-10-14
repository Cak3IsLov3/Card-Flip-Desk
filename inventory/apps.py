from django.apps import AppConfig


class InventoryConfig(AppConfig):
    name = 'inventory'

    def ready(self):
        from . import photos  # noqa: F401  registreert het post_delete-signaal
