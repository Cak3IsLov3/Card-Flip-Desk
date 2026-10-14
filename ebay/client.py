"""Client for the eBay REST APIs.

- Application token via the client credentials grant (for the Browse API),
  cached until shortly before it expires.
- Retries with exponential backoff on network errors, 429 and 5xx; a
  Retry-After header takes precedence.
- A daily budget below the eBay limit, so the app is not cut off halfway
  through the day.
- GET responses are stored in CachedResponse with their ETag (If-None-Match).
  If eBay is unreachable, the client falls back to the last response it
  fetched (marked as `stale`).

`http`, `sleep` and `now` are injectable, so tests run without a network and
without waiting.
"""

import base64
import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .models import CachedResponse

log = logging.getLogger(__name__)

HOSTS = {
    "sandbox": {"api": "https://api.sandbox.ebay.com", "auth": "https://auth.sandbox.ebay.com"},
    "production": {"api": "https://api.ebay.com", "auth": "https://auth.ebay.com"},
}
APP_SCOPE = "https://api.ebay.com/oauth/api_scope"
TOKEN_PATH = "/identity/v1/oauth2/token"
SEARCH_PATH = "/buy/browse/v1/item_summary/search"
TOKEN_MARGIN_SECONDS = 300  # renew a token five minutes before it expires


class EbayError(Exception):
    pass


class EbayNotConfigured(EbayError):
    pass


class EbayUnavailable(EbayError):
    """eBay is (temporarily) unreachable or returning server errors."""


class EbayRateLimited(EbayUnavailable):
    pass


class EbayAPIError(EbayError):
    def __init__(self, status: int, body: str):
        super().__init__(f"eBay returned HTTP {status}: {body[:300]}")
        self.status = status
        self.body = body


@dataclass
class ApiResult:
    data: dict
    fetched_at: datetime
    from_cache: bool = False
    stale: bool = False  # True = eBay was unreachable, this is an older copy


class EbayClient:
    def __init__(
        self,
        *,
        environment: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        http: httpx.Client | None = None,
        sleep=time.sleep,
        now=timezone.now,
        max_retries: int = 3,
        backoff_seconds: float = 0.5,
    ):
        self.environment = environment or settings.EBAY_ENVIRONMENT
        if self.environment not in HOSTS:
            raise EbayNotConfigured(f"Unknown EBAY_ENVIRONMENT: {self.environment}")
        self.client_id = client_id if client_id is not None else settings.EBAY_CLIENT_ID
        self.client_secret = client_secret if client_secret is not None else settings.EBAY_CLIENT_SECRET
        self.http = http or httpx.Client(timeout=10.0)
        self.sleep = sleep
        self.now = now
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds

    # --- configuratie -------------------------------------------------------

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def api_base(self) -> str:
        return HOSTS[self.environment]["api"]

    @property
    def auth_base(self) -> str:
        return HOSTS[self.environment]["auth"]

    def basic_auth_header(self) -> str:
        raw = f"{self.client_id}:{self.client_secret}".encode()
        return "Basic " + base64.b64encode(raw).decode()

    # --- tokens -------------------------------------------------------------

    def _app_token_key(self) -> str:
        return f"ebay:app-token:{self.environment}:{hashlib.sha256(self.client_id.encode()).hexdigest()[:12]}"

    def app_token(self, *, force: bool = False) -> str:
        if not self.configured:
            raise EbayNotConfigured("EBAY_CLIENT_ID and EBAY_CLIENT_SECRET are not set.")
        key = self._app_token_key()
        if not force and (token := cache.get(key)):
            return token
        payload = self.token_request({"grant_type": "client_credentials", "scope": APP_SCOPE})
        timeout = max(int(payload.get("expires_in", 7200)) - TOKEN_MARGIN_SECONDS, 60)
        cache.set(key, payload["access_token"], timeout=timeout)
        return payload["access_token"]

    def token_request(self, form: dict) -> dict:
        """POST to the token endpoint (all grant types)."""
        response = self._send(
            "POST",
            self.api_base + TOKEN_PATH,
            headers={
                "Authorization": self.basic_auth_header(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=form,
            count_towards_budget=False,  # tokens have their own eBay limit
        )
        if response.status_code >= 400:
            raise EbayAPIError(response.status_code, response.text)
        return response.json()

    # --- HTTP with retries and budget --------------------------------------

    def _budget_key(self) -> str:
        return f"ebay:calls:{self.environment}:{self.now().date().isoformat()}"

    def _spend_budget(self):
        key = self._budget_key()
        cache.add(key, 0, timeout=26 * 3600)
        used = cache.incr(key)
        if used > settings.EBAY_DAILY_CALL_BUDGET:
            raise EbayRateLimited(
                f"The daily budget of {settings.EBAY_DAILY_CALL_BUDGET} eBay calls is used up; try again tomorrow."
            )

    def calls_today(self) -> int:
        return cache.get(self._budget_key(), 0)

    def _send(self, method, url, *, headers, params=None, data=None, count_towards_budget=True):
        last_error = None
        for attempt in range(self.max_retries + 1):
            if count_towards_budget:
                self._spend_budget()
            try:
                response = self.http.request(method, url, headers=headers, params=params, data=data)
            except httpx.TransportError as exc:
                last_error = EbayUnavailable(f"Could not connect to eBay: {exc.__class__.__name__}")
                retry_after = None
            else:
                if response.status_code == 429:
                    last_error = EbayRateLimited("eBay reports too many requests (HTTP 429).")
                elif response.status_code >= 500:
                    last_error = EbayUnavailable(f"eBay returned HTTP {response.status_code}.")
                else:
                    return response
                retry_after = _retry_after_seconds(response)

            if attempt == self.max_retries:
                break
            delay = retry_after if retry_after is not None else self._backoff(attempt)
            log.warning("eBay request failed (%s), attempt %s; retrying in %.1fs", last_error, attempt + 1, delay)
            self.sleep(delay)
        raise last_error

    def _backoff(self, attempt: int) -> float:
        # 0.5 s, 1 s, 2 s, ... with some jitter so retries do not line up
        return self.backoff_seconds * (2**attempt) * random.uniform(0.8, 1.2)

    # --- GET with cache and ETag -------------------------------------------

    def get_json(self, path: str, params: dict, *, ttl_seconds: int | None = None) -> ApiResult:
        ttl = timedelta(seconds=settings.EBAY_CACHE_SECONDS if ttl_seconds is None else ttl_seconds)
        key = hashlib.sha256(
            json.dumps({"env": self.environment, "mp": settings.EBAY_MARKETPLACE_ID, **params}, sort_keys=True).encode()
        ).hexdigest()
        cached = CachedResponse.objects.filter(endpoint=path, key=key).first()
        now = self.now()
        if cached and now - cached.fetched_at < ttl:
            return ApiResult(cached.data, cached.fetched_at, from_cache=True)

        try:
            response = self._authorized_get(path, params, etag=cached.etag if cached else "")
        except EbayUnavailable:
            if cached:
                return ApiResult(cached.data, cached.fetched_at, from_cache=True, stale=True)
            raise

        if response.status_code == 304 and cached:
            cached.fetched_at = now
            cached.save(update_fields=["fetched_at"])
            return ApiResult(cached.data, now, from_cache=True)
        if response.status_code >= 400:
            raise EbayAPIError(response.status_code, response.text)

        data = response.json()
        CachedResponse.objects.update_or_create(
            endpoint=path,
            key=key,
            defaults={"data": data, "etag": response.headers.get("ETag", ""), "fetched_at": now},
        )
        return ApiResult(data, now)

    def _authorized_get(self, path, params, *, etag=""):
        def headers(token):
            h = {
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": settings.EBAY_MARKETPLACE_ID,
                "Accept": "application/json",
            }
            if etag:
                h["If-None-Match"] = etag
            return h

        url = self.api_base + path
        response = self._send("GET", url, headers=headers(self.app_token()), params=params)
        if response.status_code == 401:
            # Token revoked or expired earlier than expected: try once more.
            response = self._send("GET", url, headers=headers(self.app_token(force=True)), params=params)
        return response

    # --- Browse API ---------------------------------------------------------

    def search_items(self, query: str, *, limit: int = 50, category_ids: str = "") -> ApiResult:
        """Active fixed-price listings (the Browse default)."""
        params = {"q": query, "limit": str(min(max(limit, 1), 200))}
        if category_ids:
            params["category_ids"] = category_ids
        return self.get_json(SEARCH_PATH, params)


def _retry_after_seconds(response) -> float | None:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return min(float(value), 10.0)  # do not keep a web request waiting longer
    except ValueError:
        return None
