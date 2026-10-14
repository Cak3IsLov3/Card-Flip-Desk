from django.apps import AppConfig


class InventoryConfig(AppConfig):
    name = 'inventory'

    def ready(self):
        from . import photos  # noqa: F401  registers the post_delete signal
