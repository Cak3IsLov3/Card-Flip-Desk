from datetime import date
from decimal import Decimal as D

import httpx
import pytest
from django.urls import reverse

from ebay.client import EbayClient
from pricing.advice import PriceStats, build_advice, parse_items, search_query
from pricing.models import PriceSnapshot, PriceSource
from sales.services import register_sale

API = "https://api.sandbox.ebay.com"
TOKEN_URL = API + "/identity/v1/oauth2/token"
SEARCH_URL = API + "/buy/browse/v1/item_summary/search"
TODAY = date(2026, 10, 14)


def item(title, value, currency="EUR", url="https://www.ebay.nl/itm/1", image="https://i.ebayimg.com/x.jpg"):
    return {"title": title, "price": {"value": value, "currency": currency}, "itemWebUrl": url,
            "condition": "Ungraded", "image": {"imageUrl": image}}


SEARCH_RESPONSE = {
    "total": 7,
    "itemSummaries": [
        item("2023 Topps Chrome Erling Haaland #15", "8.50"),
        item("Haaland Topps Chrome 2023 RC", "5.00"),
        item("ERLING HAALAND chrome #15 refractor", "14.99"),
        item("Haaland 2023 USD listing", "9.00", currency="USD"),
        item("Mbappé Topps Chrome 2023", "3.00"),  # another player
        item("Haaland bad price", "abc"),
        item("Haaland free?", "0.00"),
    ],
}


@pytest.fixture
def card(user, make_card):
    return make_card(user, cost="3.00", player="Erling Haaland", set_name="Topps Chrome", year=2023, card_number="15")


@pytest.fixture
def ebay_ok(ebay_keys, respx_mock):
    respx_mock.post(TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "t", "expires_in": 7200}))
    return respx_mock.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=SEARCH_RESPONSE))


def test_search_query(card):
    assert search_query(card) == "2023 Topps Chrome Erling Haaland 15"
    card.variants = ["rookie"]
    card.card_number = ""
    assert search_query(card) == "2023 Topps Chrome Erling Haaland Rookie"


def test_parse_items_filters_and_stats(card):
    active = parse_items(SEARCH_RESPONSE, card)
    assert [i.price for i in active.items] == [D("5.00"), D("8.50"), D("14.99")]
    assert active.stats == PriceStats(3, D("5.00"), D("8.50"), D("14.99"))
    assert active.excluded_currency == 1
    assert active.excluded_irrelevant == 1
    assert active.total == 7


def test_median_of_even_count():
    assert PriceStats.of([D("1.00"), D("2.00"), D("4.00"), D("10.00")]).median == D("3.00")
    assert PriceStats.of([D("1.00"), D("2.25")]).median == D("1.63")  # 1.625 → half up
    assert PriceStats.of([]) is None


@pytest.mark.parametrize(
    "url, kept",
    [
        ("https://www.ebay.nl/itm/1", True),
        ("https://www.sandbox.ebay.com/itm/1", True),
        ("javascript:alert(1)", False),
        ("http://www.ebay.nl/itm/1", False),
        ("https://evil-ebay.attacker.com/itm/1", False),
        ("https://ebay.nl.attacker.com/itm/1", False),
    ],
)
def test_only_safe_ebay_links(card, url, kept):
    active = parse_items({"itemSummaries": [item("Haaland", "1.00", url=url, image="https://evil.com/x.jpg")]}, card)
    assert bool(active.items[0].url) is kept
    assert active.items[0].image == ""


def test_advice_from_active_listings(card, fee_profile, ebay_ok):
    advice = build_advice(card, fetch=True, today=TODAY)
    assert advice.summary == ["3 active listings, median €8.50 (lowest €5.00, highest €14.99)."]
    assert advice.suggested_price == D("8.50")
    assert "not sale prices" in advice.basis
    assert advice.preview.profit == D("4.02")  # 8.50 - (1.13 + 0.35) - 3.00 cost
    snap = PriceSnapshot.objects.get()
    assert (snap.source, snap.price, snap.listing_count) == (PriceSource.EBAY_ACTIVE, D("8.50"), 3)
    assert ebay_ok.calls[0].request.url.params["q"] == "2023 Topps Chrome Erling Haaland 15"


def test_own_history_wins_with_two_or_more_sales(user, card, fee_profile, ebay_ok, make_card):
    for price in ("6.00", "7.00", "9.00"):
        register_sale(make_card(user, player="Erling Haaland", set_name="topps chrome", cost="1"),
                      sale_price=D(price), sold_at=date(2026, 9, 1))
    register_sale(make_card(user, player="Erling Haaland", set_name="Prizm", cost="1"),
                  sale_price=D("99.00"), sold_at=date(2026, 9, 1))  # another set
    advice = build_advice(card, fetch=True, today=TODAY)
    assert advice.own.stats.count == 3
    assert advice.suggested_price == D("7.00")
    assert advice.basis == "median of your own sales"
    assert "You sold 3 yourself" in advice.summary[1]
    assert PriceSnapshot.objects.filter(source=PriceSource.OWN_HISTORY).count() == 1


def test_without_ebay_keys_uses_own_history_only(user, card, fee_profile, make_card, respx_mock):
    register_sale(make_card(user, player="Erling Haaland", set_name="Topps Chrome", cost="1"),
                  sale_price=D("6.50"), sold_at=date(2026, 9, 1))
    advice = build_advice(card, fetch=True, today=TODAY)
    assert advice.active.not_configured
    assert advice.suggested_price == D("6.50")
    assert advice.basis == "your only previous sale"
    assert not respx_mock.calls


def test_ebay_down_degrades_gracefully(card, ebay_keys, respx_mock):
    respx_mock.post(TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "t", "expires_in": 7200}))
    respx_mock.get(SEARCH_URL).mock(return_value=httpx.Response(503))
    advice = build_advice(card, fetch=True, today=TODAY, client=EbayClient(sleep=lambda s: None))
    assert "unreachable" in advice.active.error
    assert advice.suggested_price is None
    assert not PriceSnapshot.objects.exists()


def test_view_get_does_not_call_ebay(user, card, client_for, ebay_ok):
    resp = client_for(user).get(reverse("pricing:card_advice", args=[card.pk]))
    assert resp.status_code == 200
    assert ebay_ok.call_count == 0
    assert b"asking prices" in resp.content


def test_view_post_fetches_with_custom_query_and_escapes(user, card, client_for, ebay_keys, respx_mock):
    respx_mock.post(TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "t", "expires_in": 7200}))
    route = respx_mock.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={
        "total": 1, "itemSummaries": [item("<script>alert(1)</script> Haaland", "4.00")]}))
    resp = client_for(user).post(reverse("pricing:card_advice", args=[card.pk]), {"q": "Haaland chrome"},
                                 HTTP_HX_REQUEST="true")
    assert route.calls[0].request.url.params["q"] == "Haaland chrome"
    assert "pricing/_advice.html" in [t.name for t in resp.templates]
    assert b"<script>alert(1)</script>" not in resp.content
    assert b"&lt;script&gt;" in resp.content


def test_other_user_cannot_get_advice(other_user, card, client_for):
    assert client_for(other_user).get(reverse("pricing:card_advice", args=[card.pk])).status_code == 404
    assert client_for(other_user).post(reverse("pricing:card_advice", args=[card.pk])).status_code == 404
