"""Authorization Code Flow voor gebruikerstokens.

Het prijsadvies heeft dit niet nodig (de Browse API werkt met een
applicatietoken), maar Sell-API's, zoals listings plaatsen of eigen
verkopen ophalen, wel. Tokens staan versleuteld in OAuthToken en worden vijf
minuten vóór ze verlopen automatisch vernieuwd.
"""

import secrets
from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .client import EbayClient, EbayNotConfigured
from .models import OAuthToken

STATE_SESSION_KEY = "ebay_oauth_state"


class NeedsReauthorization(Exception):
    """Geen (geldige) refreshtoken: de gebruiker moet opnieuw koppelen."""


def new_state(session) -> str:
    state = secrets.token_urlsafe(32)
    session[STATE_SESSION_KEY] = state
    return state


def pop_state_matches(session, state: str | None) -> bool:
    expected = session.pop(STATE_SESSION_KEY, None)
    return bool(expected and state and secrets.compare_digest(expected, state))


def authorize_url(client: EbayClient, state: str) -> str:
    if not (client.configured and settings.EBAY_RUNAME):
        raise EbayNotConfigured("EBAY_CLIENT_ID, EBAY_CLIENT_SECRET en EBAY_RUNAME zijn nodig om te koppelen.")
    query = urlencode(
        {
            "client_id": client.client_id,
            "redirect_uri": settings.EBAY_RUNAME,
            "response_type": "code",
            "scope": " ".join(settings.EBAY_USER_SCOPES),
            "state": state,
        }
    )
    return f"{client.auth_base}/oauth2/authorize?{query}"


def _store(user, client, payload) -> OAuthToken:
    now = timezone.now()
    defaults = {
        "access_token": payload["access_token"],
        "expires_at": now + timedelta(seconds=int(payload.get("expires_in", 7200))),
        "scopes": " ".join(settings.EBAY_USER_SCOPES),
    }
    if "refresh_token" in payload:
        defaults["refresh_token"] = payload["refresh_token"]
        if payload.get("refresh_token_expires_in"):
            defaults["refresh_expires_at"] = now + timedelta(seconds=int(payload["refresh_token_expires_in"]))
    token, _ = OAuthToken.objects.update_or_create(
        user=user, provider="ebay", environment=client.environment, defaults=defaults
    )
    return token


def exchange_code(user, code: str, client: EbayClient | None = None) -> OAuthToken:
    client = client or EbayClient()
    payload = client.token_request(
        {"grant_type": "authorization_code", "code": code, "redirect_uri": settings.EBAY_RUNAME}
    )
    return _store(user, client, payload)


def user_access_token(user, client: EbayClient | None = None) -> str:
    """Geldige access token voor de gebruiker; vernieuwt hem zo nodig."""
    client = client or EbayClient()
    with transaction.atomic():
        token = (
            OAuthToken.objects.select_for_update()
            .filter(user=user, provider="ebay", environment=client.environment)
            .first()
        )
        if token is None:
            raise NeedsReauthorization("Nog geen eBay-account gekoppeld.")
        if not token.expires_soon():
            return token.access_token
        if not token.refresh_token or token.refresh_expired():
            raise NeedsReauthorization("De eBay-koppeling is verlopen; koppel opnieuw.")
        payload = client.token_request(
            {
                "grant_type": "refresh_token",
                "refresh_token": token.refresh_token,
                "scope": token.scopes or " ".join(settings.EBAY_USER_SCOPES),
            }
        )
        return _store(user, client, payload).access_token
