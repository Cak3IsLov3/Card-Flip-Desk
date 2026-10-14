from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from finance.models import FeeProfile
from inventory.models import Card, Purchase


@pytest.fixture(autouse=True)
def private_media(settings, tmp_path):
    """Each test writes photos to its own temporary folder."""
    settings.PRIVATE_MEDIA_ROOT = tmp_path / "private_media"
    return settings.PRIVATE_MEDIA_ROOT


@pytest.fixture(autouse=True)
def isolated_ebay(settings):
    """No real eBay keys and a clean cache (tokens, budget) for every test."""
    from django.core.cache import cache

    settings.EBAY_ENVIRONMENT = "sandbox"
    settings.EBAY_CLIENT_ID = ""
    settings.EBAY_CLIENT_SECRET = ""
    settings.EBAY_RUNAME = ""
    settings.EBAY_MARKETPLACE_ID = "EBAY_DE"
    settings.EBAY_CURRENCY = "EUR"
    settings.EBAY_CATEGORY_IDS = ""
    settings.EBAY_DAILY_CALL_BUDGET = 4500
    settings.EBAY_CACHE_SECONDS = 3600
    # Tests run with DEBUG=False, which requires an explicit key.
    settings.TOKEN_ENCRYPTION_KEYS = ["dGVzdC1rZXktZm9yLXRlc3RzLW9ubHktbm90LXNlY3I="]
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def ebay_keys(settings):
    settings.EBAY_CLIENT_ID = "test-client-id"
    settings.EBAY_CLIENT_SECRET = "test-client-secret"
    settings.EBAY_RUNAME = "Test_RuName-123"


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user("alice", password="test-pass-123")


@pytest.fixture
def other_user(db):
    return get_user_model().objects.create_user("bob", password="test-pass-123")


@pytest.fixture
def fee_profile(user):
    return FeeProfile.objects.create(
        user=user,
        category="Sports cards",
        commission_percentage=Decimal("13.25"),
        fixed_fee=Decimal("0.35"),
        payment_percentage=Decimal("0.00"),
        valid_from=date(2024, 1, 1),
    )


@pytest.fixture
def make_card():
    def _make(owner, cost=None, **kwargs):
        defaults = dict(player="Erling Haaland", set_name="Topps Chrome", year=2023, card_number="15")
        defaults.update(kwargs)
        card = Card.objects.create(owner=owner, **defaults)
        if cost is not None:
            Purchase.objects.create(card=card, price=Decimal(cost), date=date(2024, 5, 1))
        return card

    return _make


@pytest.fixture
def client_for():
    from django.test import Client

    def _client(u):
        c = Client()
        c.force_login(u)
        return c

    return _client
