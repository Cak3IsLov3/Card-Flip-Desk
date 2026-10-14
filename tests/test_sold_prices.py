"""Sold prices without the eBay API: a link to eBay's sold items search and pasted prices."""

from datetime import date
from decimal import Decimal as D
from urllib.parse import parse_qs, urlparse

import pytest
from django.urls import reverse

from pricing.advice import build_advice, parse_sold_prices, sold_search_url
from pricing.models import PriceSnapshot, PriceSource
from sales.services import register_sale

TODAY = date(2026, 10, 14)


@pytest.fixture
def card(user, make_card):
    return make_card(user, cost="3.00", player="Lamine Yamal", set_name="Topps Chrome", year=2024, card_number="1",
                     variants=["rookie", "parallel"], parallel_name="Gold Refractor", parallel_serial="23/50")


# --- parsing -----------------------------------------------------------------

@pytest.mark.parametrize(
    "text, expected",
    [
        ("12,50  14 9,99", ["9.99", "12.50", "14.00"]),
        ("EUR 15,00\n€ 1.234,56; 12.5", ["12.50", "15.00", "1234.56"]),
        ("12,50, 14, 9.99", ["9.99", "12.50", "14.00"]),  # comma + space separates prices
        ("1,234.56 | 1.234", ["1234.00", "1234.56"]),  # English notation, thousands without cents
        ("EUR12,50 15€", ["12.50", "15.00"]),
    ],
)
def test_parse_sold_prices(text, expected):
    assert parse_sold_prices(text).prices == [D(x) for x in expected]


def test_parse_reports_what_it_ignores():
    result = parse_sold_prices("12,50 lot 0 -3 abc 99999999 1,2,3")
    assert result.prices == [D("12.50")]
    assert result.ignored == ["lot", "0", "-3", "abc", "99999999", "1,2,3"]


def test_parse_empty_and_limits():
    assert parse_sold_prices("").stats is None
    many = parse_sold_prices(" ".join(["5"] * 300))
    assert len(many.prices) == 200
    assert len(parse_sold_prices("x " * 50).ignored) == 10


# --- link to eBay ------------------------------------------------------------

def test_sold_search_url_uses_marketplace_and_sold_filter(settings):
    settings.EBAY_MARKETPLACE_ID = "EBAY_DE"
    url = urlparse(sold_search_url("2024 Topps Chrome Lamine Yamal /50"))
    params = parse_qs(url.query)
    assert (url.scheme, url.hostname, url.path) == ("https", "www.ebay.de", "/sch/i.html")
    assert params == {"_nkw": ["2024 Topps Chrome Lamine Yamal /50"], "LH_Sold": ["1"], "LH_Complete": ["1"]}
    settings.EBAY_MARKETPLACE_ID = "EBAY_NL"
    assert urlparse(sold_search_url("x")).hostname == "www.ebay.nl"


# --- advice ------------------------------------------------------------------

def test_sold_prices_give_the_suggested_price_and_a_snapshot(card, fee_profile, respx_mock):
    advice = build_advice(card, fetch=False, today=TODAY, sold=parse_sold_prices("20 25 30,50"))
    assert advice.suggested_price == D("25.00")
    assert advice.basis == "median of the sold prices you entered"
    assert advice.summary[0] == "3 sold prices entered, median €25.00 (lowest €20.00, highest €30.50)."
    snapshot = PriceSnapshot.objects.get()
    assert (snapshot.source, snapshot.price, snapshot.listing_count) == (PriceSource.MANUAL_SOLD, D("25.00"), 3)
    assert not respx_mock.calls  # no eBay API


def test_sold_prices_beat_own_history(user, card, fee_profile, make_card):
    for price in ("6.00", "7.00"):
        register_sale(make_card(user, player="Lamine Yamal", set_name="Topps Chrome", cost="1"),
                      sale_price=D(price), sold_at=date(2026, 9, 1))
    advice = build_advice(card, fetch=False, today=TODAY, sold=parse_sold_prices("20 30"))
    assert advice.suggested_price == D("25.00")


def test_one_sold_price_does_not_beat_two_own_sales(user, card, fee_profile, make_card):
    for price in ("6.00", "8.00"):
        register_sale(make_card(user, player="Lamine Yamal", set_name="Topps Chrome", cost="1"),
                      sale_price=D(price), sold_at=date(2026, 9, 1))
    advice = build_advice(card, fetch=False, today=TODAY, sold=parse_sold_prices("40"))
    assert advice.suggested_price == D("7.00")
    assert advice.basis == "median of your own sales"


def test_a_single_sold_price_is_used_when_nothing_else(card, fee_profile):
    advice = build_advice(card, fetch=False, today=TODAY, sold=parse_sold_prices("18,00"))
    assert (advice.suggested_price, advice.basis) == (D("18.00"), "the only sold price you entered")


# --- view --------------------------------------------------------------------

def test_page_shows_sold_link_for_the_card(user, card, client_for):
    html = client_for(user).get(reverse("pricing:card_advice", args=[card.pk])).content.decode()
    assert "Open sold items on eBay" in html
    assert "https://www.ebay.de/sch/i.html?_nkw=2024+Topps+Chrome+Lamine+Yamal+1+Rookie+Gold+Refractor+%2F50" \
           "&amp;LH_Sold=1&amp;LH_Complete=1" in html
    assert 'target="_blank" rel="noopener noreferrer"' in html


def test_posting_sold_prices_does_not_call_ebay(user, card, fee_profile, client_for, ebay_keys, respx_mock):
    resp = client_for(user).post(
        reverse("pricing:card_advice", args=[card.pk]),
        {"action": "sold", "q": "Yamal gold /50", "prices": "20 25 <b>x</b>"},
        HTTP_HX_REQUEST="true",
    )
    html = resp.content.decode()
    assert resp.status_code == 200
    assert not respx_mock.calls
    assert "Suggested price: <strong>€22.50</strong>" in html
    assert "Ignored: &lt;b&gt;x&lt;/b&gt;" in html
    assert "_nkw=Yamal+gold+%2F50" in html  # the link follows the custom query
    assert PriceSnapshot.objects.get(source=PriceSource.MANUAL_SOLD).query == "Yamal gold /50"


def test_posting_nothing_usable_shows_a_message(user, card, client_for):
    resp = client_for(user).post(reverse("pricing:card_advice", args=[card.pk]), {"action": "sold", "prices": "abc"})
    assert "No prices found" in resp.content.decode()
    assert not PriceSnapshot.objects.exists()


def test_other_user_cannot_post_sold_prices(other_user, card, client_for):
    resp = client_for(other_user).post(reverse("pricing:card_advice", args=[card.pk]),
                                       {"action": "sold", "prices": "10"})
    assert resp.status_code == 404
    assert not PriceSnapshot.objects.exists()
