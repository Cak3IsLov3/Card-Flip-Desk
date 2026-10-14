"""Versleuteling van tokens in de database (Fernet: AES-128-CBC + HMAC).

Sleutels komen uit `TOKEN_ENCRYPTION_KEYS`. De eerste sleutel versleutelt,
alle sleutels mogen ontsleutelen, zodat je kunt roteren zonder dat oude
tokens onleesbaar worden. Alleen in DEBUG wordt bij gebrek aan een sleutel
er een afgeleid van SECRET_KEY, zodat lokaal ontwikkelen zonder extra stap
werkt.
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
            raise ImproperlyConfigured("TOKEN_ENCRYPTION_KEYS ontbreekt; tokens kunnen niet veilig worden opgeslagen.")
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
        raise ValueError("Token kan niet worden ontsleuteld (verkeerde of ontbrekende sleutel).") from None


class EncryptedTextField(models.TextField):
    """Tekstveld dat versleuteld in de database staat. Niet doorzoekbaar."""

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value in (None, ""):
            return value
        return encrypt(value)

    def from_db_value(self, value, expression, connection):
        if value in (None, ""):
            return value
        return decrypt(value)
