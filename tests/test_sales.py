from datetime import date
from decimal import Decimal as D

import pytest
from django.urls import reverse

from finance.models import FeeProfile
from inventory.models import CardStatus, Purchase
from sales.models import ListingStatus, Sale
from sales.services import NoFeeProfile, card_profit, register_sale


def test_register_sale_uses_fee_profile_and_marks_sold(user, fee_profile, make_card):
    card = make_card(user, cost="3.00")
    sale = register_sale(
        card,
        sale_price=D("10.00"),
        shipping_income=D("2.50"),
        shipping_cost=D("1.95"),
        packaging_cost=D("0.30"),
        sold_at=date(2025, 4, 2),
    )
    assert sale.ebay_commission == D("2.01")
    assert sale.net_proceeds == D("8.24")
    assert card_profit(card) == D("5.24")

    card.refresh_from_db()
    assert card.status == CardStatus.SOLD
    assert sale.listing.status == ListingStatus.SOLD


def test_sale_uses_profile_valid_on_sale_date(user, fee_profile, make_card):
    FeeProfile.objects.create(
        user=user, commission_percentage=D("20.00"), fixed_fee=D("0"), valid_from=date(2025, 6, 1)
    )
    before = register_sale(make_card(user), sale_price=D("10.00"), sold_at=date(2025, 5, 31))
    after = register_sale(make_card(user), sale_price=D("10.00"), sold_at=date(2025, 6, 1))
    assert before.ebay_commission == D("1.68")  # 13.25% + 0.35
    assert after.ebay_commission == D("2.00")  # 20%


def test_no_fee_profile_raises(user, make_card):
    with pytest.raises(NoFeeProfile):
        register_sale(make_card(user), sale_price=D("5"), sold_at=date(2025, 1, 1))


def test_profit_with_multiple_purchases_not_double_counted(user, fee_profile, make_card):
    card = make_card(user, cost="2.00")
    Purchase.objects.create(card=card, price=D("1.00"), shipping_in=D("0.50"), date=date(2024, 5, 2))
    register_sale(card, sale_price=D("10.00"), sold_at=date(2025, 1, 10))

    row = Sale.objects.owned_by(user).with_profit().get()
    assert row.cost == D("3.50")
    assert row.net == D("8.32")  # 10 - (1.33 + 0.35)
    assert row.profit == D("4.82")


def test_profit_per_month(user, fee_profile, make_card):
    register_sale(make_card(user, cost="1.00"), sale_price=D("10.00"), sold_at=date(2025, 1, 5))
    register_sale(make_card(user, cost="1.00"), sale_price=D("10.00"), sold_at=date(2025, 1, 20))
    register_sale(make_card(user, cost="20.00"), sale_price=D("10.00"), sold_at=date(2025, 2, 1))

    months = list(Sale.objects.owned_by(user).profit_per_month())
    assert [m["month"].month for m in months] == [1, 2]
    assert months[0]["revenue"] == D("20.00")
    assert months[0]["profit_total"] == D("14.64")  # 2 x (8.32 - 1.00)
    assert months[1]["profit_total"] == D("-11.68")


def test_sale_view(user, fee_profile, make_card, client_for):
    card = make_card(user, cost="3.00")
    resp = client_for(user).post(
        reverse("sales:sale_create", args=[card.pk]),
        {
            "sale_price": "10.00",
            "shipping_income": "2.50",
            "shipping_cost": "1.95",
            "packaging_cost": "0.30",
            "sold_at": "2025-04-02",
            "buyer_country": "de",
            "category": "Sports cards",
        },
    )
    assert resp.status_code == 302
    sale = Sale.objects.get()
    assert sale.buyer_country == "DE"
    assert card_profit(card) == D("5.24")
