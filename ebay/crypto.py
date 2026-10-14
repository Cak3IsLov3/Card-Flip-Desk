"""Encryption of tokens in the database (Fernet: AES-128-CBC + HMAC).

Keys come from `TOKEN_ENCRYPTION_KEYS`. The first key encrypts, every key may
decrypt, so you can rotate keys without old tokens becoming unreadable. Only
in DEBUG, when no key is set, one is derived from SECRET_KEY so local
development works without an extra step.
"""

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.signals import setting_changed
from django.db import models
from django.dispatch import receiver


@lru_cache(maxsize=1)
def _fernet() -> MultiFernet:
    keys = list(settings.TOKEN_ENCRYPTION_KEYS)
    if not keys:
        if not settings.DEBUG:
            raise ImproperlyConfigured("TOKEN_ENCRYPTION_KEYS is not set; tokens cannot be stored safely.")
        digest = hashlib.sha256(("card-flip-desk-tokens:" + settings.SECRET_KEY).encode()).digest()
        keys = [base64.urlsafe_b64encode(digest).decode()]
    return MultiFernet([Fernet(k) for k in keys])


@receiver(setting_changed)
def _reset(setting, **kwargs):
    if setting in ("TOKEN_ENCRYPTION_KEYS", "SECRET_KEY", "DEBUG"):
        _fernet.cache_clear()


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        raise ValueError("Token cannot be decrypted (wrong or missing key).") from None


class EncryptedTextField(models.TextField):
    """Text field stored encrypted in the database. Not searchable."""

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value in (None, ""):
            return value
        return encrypt(value)

    def from_db_value(self, value, expression, connection):
        if value in (None, ""):
            return value
        return decrypt(value)
