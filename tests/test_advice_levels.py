"""Price advice extras: price levels, "use this price", history chart, last advice on the card."""

import json
from datetime import date, datetime, timedelta
from decimal import Decimal as D

import pytest
from django.urls import reverse
from django.utils import timezone

from pricing.advice import PriceStats, build_advice, parse_sold_prices, price_history
from pricing.models import PriceSnapshot, PriceSource

TODAY = date(2026, 11, 20)


@pytest.fixture
def card(user, make_card):
    return make_card(user, cost="3.00", player="Lamine Yamal", set_name="Topps Chrome", year=2024, card_number="1")


# --- levels ------------------------------------------------------------------

def test_quartiles_from_three_prices():
    stats = PriceStats.of([D("31.00"), D("20.00"), D("25.00"), D("22.00"), D("27.50")])
    assert (stats.low, stats.median, stats.high) == (D("22.00"), D("25.00"), D("27.50"))
    assert PriceStats.of([D("10.00"), D("20.00")]).low is None
    # Quartiles do not take part in equality, so existing comparisons keep working.
    assert stats == PriceStats(5, D("20.00"), D("25.00"), D("31.00"))


def test_three_levels_with_profit(card, fee_profile):
    advice = build_advice(card, fetch=False, today=TODAY, sold=parse_sold_prices("20 22 25 27,50 31"))
    assert [(lv.key, lv.price) for lv in advice.levels] == [
        ("quick", D("22.00")), ("normal", D("25.00")), ("patient", D("27.50"))]
    # 13.25% + €0.35 test profile, €3.00 purchase: 25.00 - 3.31 - 0.35 - 3.00
    assert advice.levels[1].preview.profit == D("18.34")
    assert advice.levels[0].preview.profit < advice.levels[2].preview.profit


def test_no_levels_below_three_prices(card, fee_profile):
    advice = build_advice(card, fetch=False, today=TODAY, sold=parse_sold_prices("20 30"))
    assert advice.levels == []
    assert advice.suggested_price == D("25.00")


def test_levels_without_fee_profile_show_no_profit(card):
    advice = build_advice(card, fetch=False, today=TODAY, sold=parse_sold_prices("20 25 30"))
    assert [lv.preview for lv in advice.levels] == [None, None, None]


def test_advice_page_links_each_level_to_the_listing_generator(user, card, fee_profile, client_for):
    html = client_for(user).post(reverse("pricing:card_advice", args=[card.pk]),
                                 {"action": "sold", "prices": "20 22 25 27,50 31"}).content.decode()
    base = reverse("sales:listing_generator", args=[card.pk])
    for price in ("22.00", "25.00", "27.50"):
        assert f'href="{base}?price={price}"' in html
    assert "Quick sale" in html and "Patient" in html


# --- use this price ----------------------------------------------------------

def test_listing_generator_takes_the_price_from_the_link(user, card, client_for):
    resp = client_for(user).get(reverse("sales:listing_generator", args=[card.pk]) + "?price=26.25")
    html = resp.content.decode()
    assert 'value="26.25"' in html
    assert "Asking price set to €26.25 from the price advice" in html


@pytest.mark.parametrize("raw", ["abc", "-5", "0", "999999", "<script>"])
def test_listing_generator_ignores_bad_prices(user, card, client_for, raw):
    html = client_for(user).get(reverse("sales:listing_generator", args=[card.pk]), {"price": raw}).content.decode()
    assert "from the price advice" not in html
    assert "<script>" not in html.split("</head>", 1)[1].split("<script", 1)[0]


# --- history -----------------------------------------------------------------

def snapshot(card, source, price, days_ago):
    s = PriceSnapshot.objects.create(card=card, source=source, price=D(price), listing_count=3)
    taken = timezone.make_aware(datetime(2026, 11, 20, 12, 0)) - timedelta(days=days_ago)
    PriceSnapshot.objects.filter(pk=s.pk).update(taken_at=taken)


def test_price_history_per_day_and_source(card):
    snapshot(card, PriceSource.MANUAL_SOLD, "24.00", 10)
    snapshot(card, PriceSource.MANUAL_SOLD, "25.00", 10)  # same day: the latest wins
    snapshot(card, PriceSource.MANUAL_SOLD, "27.00", 2)
    snapshot(card, PriceSource.EBAY_ACTIVE, "30.00", 2)
    history = price_history(card)
    assert history["days"] == ["10-11-2026", "18-11-2026"]
    assert history["series"] == [
        {"key": "manual_sold", "label": "eBay sold prices (entered)", "values": ["25.00", "27.00"]},
        {"key": "ebay_active", "label": "eBay active listings", "values": [None, "30.00"]},
    ]


def test_no_history_with_one_day(card):
    assert price_history(card) is None
    snapshot(card, PriceSource.MANUAL_SOLD, "24.00", 1)
    assert price_history(card) is None


def test_advice_page_shows_the_chart_only_with_history(user, card, client_for):
    url = reverse("pricing:card_advice", args=[card.pk])
    assert "chart-price-history" not in client_for(user).get(url).content.decode()
    snapshot(card, PriceSource.MANUAL_SOLD, "24.00", 5)
    snapshot(card, PriceSource.MANUAL_SOLD, "26.00", 1)
    html = client_for(user).get(url).content.decode()
    assert 'id="chart-price-history"' in html
    data = json.loads(html.split('<script id="price-history" type="application/json">')[1].split("</script>")[0])
    assert data["series"][0]["values"] == ["24.00", "26.00"]


# --- card detail -------------------------------------------------------------

def test_card_detail_shows_the_last_advice(user, card, client_for):
    url = reverse("inventory:card_detail", args=[card.pk])
    assert "Check the price" in client_for(user).get(url).content.decode()
    snapshot(card, PriceSource.MANUAL_SOLD, "26.25", 3)
    html = client_for(user).get(url).content.decode()
    assert "€26.25" in html and "eBay sold prices (entered)" in html
