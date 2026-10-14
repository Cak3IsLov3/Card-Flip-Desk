from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from finance.models import FeeProfile
from inventory.models import Card, Purchase


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
        category="Sportkaarten",
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
