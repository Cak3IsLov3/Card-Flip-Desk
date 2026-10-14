import base64
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.urls import reverse
from django.utils import timezone

from ebay import crypto, oauth
from ebay.client import (
    APP_SCOPE,
    EbayAPIError,
    EbayClient,
    EbayNotConfigured,
    EbayRateLimited,
    EbayUnavailable,
)
from ebay.models import CachedResponse, OAuthToken

API = "https://api.sandbox.ebay.com"
TOKEN_URL = API + "/identity/v1/oauth2/token"
SEARCH_URL = API + "/buy/browse/v1/item_summary/search"

pytestmark = pytest.mark.django_db


def token_json(token="app-token-1", expires_in=7200):
    return {"access_token": token, "expires_in": expires_in, "token_type": "Application Access Token"}


@pytest.fixture
def sleeps():
    return []


@pytest.fixture
def client(ebay_keys, sleeps):
    return EbayClient(sleep=sleeps.append, http=httpx.Client())


@pytest.fixture
def token_route(respx_mock):
    return respx_mock.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=token_json()))


# --- application token -------------------------------------------------------

def test_not_configured_raises(settings):
    with pytest.raises(EbayNotConfigured):
        EbayClient().app_token()


def test_app_token_request_and_caching(client, token_route):
    assert client.app_token() == "app-token-1"
    assert client.app_token() == "app-token-1"
    assert token_route.call_count == 1  # second time from the cache

    request = token_route.calls[0].request
    expected = "Basic " + base64.b64encode(b"test-client-id:test-client-secret").decode()
    assert request.headers["Authorization"] == expected
    form = parse_qs(request.content.decode())
    assert form == {"grant_type": ["client_credentials"], "scope": [APP_SCOPE]}


def test_app_token_is_renewed_before_expiry(client, respx_mock):
    route = respx_mock.post(TOKEN_URL).mock(
        side_effect=[httpx.Response(200, json=token_json("t1", 400)), httpx.Response(200, json=token_json("t2"))]
    )
    assert client.app_token() == "t1"
    # 400 s valid - 300 s margin = 100 s in the cache; after that it is gone.
    cache.delete(client._app_token_key())
    assert client.app_token() == "t2"
    assert route.call_count == 2


def test_invalid_credentials_give_api_error(client, respx_mock):
    respx_mock.post(TOKEN_URL).mock(return_value=httpx.Response(401, json={"error": "invalid_client"}))
    with pytest.raises(EbayAPIError) as exc:
        client.app_token()
    assert exc.value.status == 401


# --- search, cache and ETag ----------------------------------------------------

def test_search_sends_headers_and_caches_with_etag(client, token_route, respx_mock):
    route = respx_mock.get(SEARCH_URL).mock(
        return_value=httpx.Response(200, json={"total": 1, "itemSummaries": []}, headers={"ETag": '"abc"'})
    )
    result = client.search_items("2023 Topps Chrome Haaland")
    assert not result.from_cache
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer app-token-1"
    assert request.headers["X-EBAY-C-MARKETPLACE-ID"] == "EBAY_NL"
    assert request.url.params["q"] == "2023 Topps Chrome Haaland"
    cached = CachedResponse.objects.get()
    assert cached.etag == '"abc"' and cached.data["total"] == 1

    again = client.search_items("2023 Topps Chrome Haaland")
    assert again.from_cache and route.call_count == 1  # no call within the TTL


def test_expired_cache_revalidates_with_etag_304(client, token_route, respx_mock):
    route = respx_mock.get(SEARCH_URL).mock(
        side_effect=[
            httpx.Response(200, json={"total": 5}, headers={"ETag": '"v1"'}),
            httpx.Response(304),
        ]
    )
    client.search_items("x")
    CachedResponse.objects.update(fetched_at=timezone.now() - timedelta(hours=2))
    result = client.search_items("x")
    assert route.calls[1].request.headers["If-None-Match"] == '"v1"'
    assert result.from_cache and not result.stale and result.data == {"total": 5}
    assert timezone.now() - CachedResponse.objects.get().fetched_at < timedelta(minutes=1)


def test_429_is_retried_after_retry_after(client, token_route, respx_mock, sleeps):
    route = respx_mock.get(SEARCH_URL).mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "2"}), httpx.Response(200, json={"total": 0})]
    )
    assert client.search_items("x").data == {"total": 0}
    assert route.call_count == 2
    assert sleeps == [2.0]


def test_5xx_is_retried_with_growing_backoff(client, token_route, respx_mock, sleeps):
    respx_mock.get(SEARCH_URL).mock(
        side_effect=[httpx.Response(503), httpx.Response(500), httpx.Response(502), httpx.Response(200, json={})]
    )
    client.search_items("x")
    assert len(sleeps) == 3
    assert sleeps[0] < sleeps[1] < sleeps[2]  # 0.5 → 1 → 2 s (with jitter)


def test_persistent_failure_raises_unavailable(client, token_route, respx_mock, sleeps):
    route = respx_mock.get(SEARCH_URL).mock(return_value=httpx.Response(503))
    with pytest.raises(EbayUnavailable):
        client.search_items("x")
    assert route.call_count == 4  # 1 + 3 retries


def test_network_error_falls_back_to_stale_cache(client, token_route, respx_mock):
    route = respx_mock.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"total": 3}))
    client.search_items("x")
    CachedResponse.objects.update(fetched_at=timezone.now() - timedelta(days=2))
    route.mock(side_effect=httpx.ConnectError("geen netwerk"))
    result = client.search_items("x")
    assert result.stale and result.from_cache and result.data == {"total": 3}


def test_401_refreshes_token_once(client, respx_mock):
    tokens = respx_mock.post(TOKEN_URL).mock(
        side_effect=[httpx.Response(200, json=token_json("old")), httpx.Response(200, json=token_json("new"))]
    )
    search = respx_mock.get(SEARCH_URL).mock(side_effect=[httpx.Response(401), httpx.Response(200, json={})])
    client.search_items("x")
    assert tokens.call_count == 2
    assert search.calls[1].request.headers["Authorization"] == "Bearer new"


def test_4xx_is_not_retried(client, token_route, respx_mock):
    route = respx_mock.get(SEARCH_URL).mock(return_value=httpx.Response(400, json={"errors": []}))
    with pytest.raises(EbayAPIError):
        client.search_items("x")
    assert route.call_count == 1


def test_daily_budget_stops_calls(client, token_route, respx_mock, settings):
    settings.EBAY_DAILY_CALL_BUDGET = 2
    route = respx_mock.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={}))
    client.search_items("a")
    client.search_items("b")
    with pytest.raises(EbayRateLimited, match="daily budget"):
        client.search_items("c")
    assert route.call_count == 2
    assert client.calls_today() == 3


# --- encryption ----------------------------------------------------------------

def test_tokens_are_encrypted_at_rest(user):
    token = OAuthToken.objects.create(
        user=user, environment="sandbox", access_token="secret-access", refresh_token="secret-refresh",
        expires_at=timezone.now(),
    )
    with connection.cursor() as cur:
        cur.execute("SELECT access_token, refresh_token FROM ebay_oauthtoken WHERE id = %s", [token.pk])
        raw_access, raw_refresh = cur.fetchone()
    assert "secret" not in raw_access and "secret" not in raw_refresh
    token.refresh_from_db()
    assert token.access_token == "secret-access"


def test_key_rotation(settings):
    from cryptography.fernet import Fernet

    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    settings.TOKEN_ENCRYPTION_KEYS = [old]
    encrypted = crypto.encrypt("value")
    settings.TOKEN_ENCRYPTION_KEYS = [new, old]
    assert crypto.decrypt(encrypted) == "value"
    settings.TOKEN_ENCRYPTION_KEYS = [new]
    with pytest.raises(ValueError):
        crypto.decrypt(encrypted)


def test_production_requires_encryption_key(settings):
    settings.DEBUG = False
    settings.TOKEN_ENCRYPTION_KEYS = []
    with pytest.raises(ImproperlyConfigured):
        crypto.encrypt("x")


# --- Authorization Code Flow -------------------------------------------------

def test_authorize_url(client):
    url = urlparse(oauth.authorize_url(client, "state123"))
    q = parse_qs(url.query)
    assert url.netloc == "auth.sandbox.ebay.com" and url.path == "/oauth2/authorize"
    assert q["client_id"] == ["test-client-id"]
    assert q["redirect_uri"] == ["Test_RuName-123"]
    assert q["response_type"] == ["code"]
    assert q["state"] == ["state123"]
    assert "sell.inventory.readonly" in q["scope"][0]


def test_connect_and_callback_flow(user, ebay_keys, client_for, respx_mock):
    client = client_for(user)
    resp = client.post(reverse("ebay:connect"))
    assert resp.status_code == 302 and resp.url.startswith("https://auth.sandbox.ebay.com/oauth2/authorize")
    state = parse_qs(urlparse(resp.url).query)["state"][0]

    route = respx_mock.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={
            "access_token": "user-access", "expires_in": 7200, "refresh_token": "user-refresh",
            "refresh_token_expires_in": 47304000, "token_type": "User Access Token",
        })
    )
    resp = client.get(reverse("ebay:callback"), {"state": state, "code": "auth-code-1"})
    assert resp.url == reverse("ebay:connection")
    form = parse_qs(route.calls[0].request.content.decode())
    assert form == {"grant_type": ["authorization_code"], "code": ["auth-code-1"], "redirect_uri": ["Test_RuName-123"]}
    token = OAuthToken.objects.get(user=user)
    assert token.access_token == "user-access" and token.refresh_token == "user-refresh"
    assert token.refresh_expires_at > timezone.now() + timedelta(days=500)


def test_callback_rejects_wrong_or_reused_state(user, ebay_keys, client_for, respx_mock):
    route = respx_mock.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=token_json()))
    client = client_for(user)
    state = parse_qs(urlparse(client.post(reverse("ebay:connect")).url).query)["state"][0]
    client.get(reverse("ebay:callback"), {"state": "forged", "code": "x"})
    client.get(reverse("ebay:callback"), {"state": state, "code": "x"})  # state has already been used
    assert route.call_count == 0
    assert not OAuthToken.objects.exists()


def make_user_token(user, *, expires_in_minutes=60, refresh_expired=False):
    now = timezone.now()
    return OAuthToken.objects.create(
        user=user, environment="sandbox", access_token="current", refresh_token="refresh-1",
        expires_at=now + timedelta(minutes=expires_in_minutes),
        refresh_expires_at=now + (timedelta(days=-1) if refresh_expired else timedelta(days=300)),
        scopes=APP_SCOPE,
    )


def test_user_token_valid_is_returned_without_call(user, client, respx_mock):
    make_user_token(user)
    assert oauth.user_access_token(user, client) == "current"
    assert not respx_mock.calls


def test_user_token_refreshed_shortly_before_expiry(user, client, respx_mock):
    make_user_token(user, expires_in_minutes=3)
    route = respx_mock.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "fresh", "expires_in": 7200})
    )
    assert oauth.user_access_token(user, client) == "fresh"
    form = parse_qs(route.calls[0].request.content.decode())
    assert form["grant_type"] == ["refresh_token"] and form["refresh_token"] == ["refresh-1"]
    token = OAuthToken.objects.get()
    assert token.refresh_token == "refresh-1"  # kept when eBay does not send a new one
    assert token.expires_at > timezone.now() + timedelta(minutes=100)


@pytest.mark.parametrize("setup", ["none", "refresh_expired"])
def test_user_token_needs_reauthorization(user, client, setup):
    if setup == "refresh_expired":
        make_user_token(user, expires_in_minutes=-5, refresh_expired=True)
    with pytest.raises(oauth.NeedsReauthorization):
        oauth.user_access_token(user, client)


def test_disconnect_only_removes_own_token(user, other_user, client_for):
    make_user_token(user)
    client_for(other_user).post(reverse("ebay:disconnect"))
    assert OAuthToken.objects.filter(user=user).exists()
    client_for(user).post(reverse("ebay:disconnect"))
    assert not OAuthToken.objects.exists()


def test_connection_page_without_keys(user, client_for):
    resp = client_for(user).get(reverse("ebay:connection"))
    assert resp.status_code == 200
    assert b"EBAY_CLIENT_ID" in resp.content
