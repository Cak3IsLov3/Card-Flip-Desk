from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from .crypto import EncryptedTextField


class OAuthToken(models.Model):
    """Gebruikerstoken (Authorization Code Flow), versleuteld opgeslagen."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="oauth_tokens"
    )
    provider = models.CharField(max_length=20, default="ebay")
    environment = models.CharField(max_length=20)
    access_token = EncryptedTextField()
    refresh_token = EncryptedTextField(blank=True)
    scopes = models.TextField(blank=True)
    expires_at = models.DateTimeField("verloopt op")
    refresh_expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "provider", "environment"], name="one_token_per_provider_env"
            )
        ]

    def __str__(self):
        return f"{self.provider} ({self.environment}) – {self.user}"

    def expires_soon(self, margin=timedelta(minutes=5), now=None) -> bool:
        return self.expires_at <= (now or timezone.now()) + margin

    def refresh_expired(self, now=None) -> bool:
        return bool(self.refresh_expires_at and self.refresh_expires_at <= (now or timezone.now()))


class CachedResponse(models.Model):
    """Antwoorden van eBay, met ETag. Dient ook als noodvoorraad als eBay
    niet bereikbaar is."""

    endpoint = models.CharField(max_length=200)
    key = models.CharField(max_length=64)  # sha256 van de parameters
    data = models.JSONField()
    etag = models.CharField(max_length=200, blank=True)
    fetched_at = models.DateTimeField("opgehaald op")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["endpoint", "key"], name="unique_cached_response")]

    def __str__(self):
        return f"{self.endpoint} ({self.fetched_at:%d-%m-%Y %H:%M})"
