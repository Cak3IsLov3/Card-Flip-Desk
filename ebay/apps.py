from django.apps import AppConfig


class EbayConfig(AppConfig):
    name = 'ebay'

    def ready(self):
        # Registers the check for wrongly pasted settings (config.W001).
        from config import env_checks  # noqa: F401
