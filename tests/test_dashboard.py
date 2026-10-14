import json
from datetime import date
from decimal import Decimal as D

import pytest
from django.urls import reverse

from inventory.models import CardStatus, Purchase
from sales.dashboard import build_dashboard, margin
from sales.services import register_sale

TODAY = date(2026, 10, 14)


@pytest.fixture
def shop(user, other_user, fee_profile, make_card):
    """Drie verkopen, drie onverkochte kaarten en wat ruis van een ander."""
    a = make_card(user, cost="1.00", player="A", listed_since=date(2026, 9, 1))
    register_sale(a, sale_price=D("10.00"), sold_at=date(2026, 10, 5))  # winst 7,32; 34 dagen
    b = make_card(user, cost="20.00", player="B")  # inkoop 2024-05-01, geen 'te koop sinds'
    register_sale(b, sale_price=D("10.00"), sold_at=date(2026, 8, 10))  # winst -11,68
    c = make_card(user, cost="2.00", player="C", set_name="Prizm", year=2022)
    register_sale(c, sale_price=D("10.00"), sold_at=date(2025, 1, 10))  # buiten 12 maanden

    d = make_card(user, cost="5.00", player="D")  # oudste inkoop
    e = make_card(user, player="E", status=CardStatus.FOR_SALE)
    Purchase.objects.create(card=e, price=D("3.00"), date=date(2026, 1, 1))
    f = make_card(user, player="F")  # geen inkoop
    make_card(other_user, cost="999.00", player="Ander")
    return {"a": a, "b": b, "c": c, "d": d, "e": e, "f": f}


def test_totals_for_last_12_months(user, shop):
    d = build_dashboard(user, today=TODAY, period="365")
    assert d.start == date(2025, 10, 15)
    assert d.sales_count == 2
    assert d.revenue == D("20.00")
    assert d.profit == D("-4.36")
    assert d.margin == D("-21.8")


def test_totals_all_time(user, shop):
    d = build_dashboard(user, today=TODAY, period="all")
    assert d.start is None
    assert d.sales_count == 3
    assert d.profit == D("1.96")
    assert d.margin == D("6.5")  # 1,96 / 30,00


def test_unknown_period_falls_back_to_default(user, shop):
    assert build_dashboard(user, today=TODAY, period="bogus").period == "365"


def test_months_include_empty_months(user, shop):
    months = build_dashboard(user, today=TODAY, period="365").months
    assert [m["month"] for m in months][0] == date(2025, 11, 1)
    assert months[-1]["month"] == date(2026, 10, 1)
    assert len(months) == 12
    by_month = {m["month"]: m for m in months}
    assert by_month[date(2026, 10, 1)]["profit"] == D("7.32")
    assert by_month[date(2026, 8, 1)]["profit"] == D("-11.68")
    assert by_month[date(2026, 9, 1)]["revenue"] == D("0.00")


def test_short_period_limits_months(user, shop):
    months = build_dashboard(user, today=TODAY, period="30").months
    assert [m["month"] for m in months] == [date(2026, 9, 1), date(2026, 10, 1)]


def test_per_set(user, shop):
    sets = build_dashboard(user, today=TODAY, period="all").sets
    assert [(s["set_name"], s["count"], s["profit"], s["margin"]) for s in sets] == [
        ("Prizm", 1, D("6.32"), D("63.2")),
        ("Topps Chrome", 2, D("-4.36"), D("-21.8")),
    ]


def test_best_worst_fastest_slowest(user, shop):
    d = build_dashboard(user, today=TODAY, period="all")
    assert [s.listing.card.player for s in d.best_cards] == ["A", "C", "B"]
    assert [s.listing.card.player for s in d.worst_cards] == ["B", "C", "A"]
    assert d.fastest[0].listing.card.player == "A"
    assert d.fastest[0].days_to_sale.days == 34
    slowest = d.slowest[0]
    assert slowest.listing.card.player == "B"
    assert slowest.days_to_sale.days == (date(2026, 8, 10) - date(2024, 5, 1)).days


def test_stock_oldest_first(user, shop):
    d = build_dashboard(user, today=TODAY)
    assert d.stock_value == D("8.00")  # D 5,00 + E 3,00 + F 0; andermans kaart telt niet
    assert d.stock_count == 3
    assert [c.player for c in d.oldest_stock] == ["D", "E", "F"]
    assert d.oldest_stock[0].age_days == (TODAY - date(2024, 5, 1)).days
    assert d.oldest_stock[2].age_days is None


def test_empty_dashboard(user):
    d = build_dashboard(user, today=TODAY)
    assert (d.sales_count, d.revenue, d.profit, d.margin) == (0, D("0"), D("0"), None)
    assert len(d.months) == 12
    assert d.sets == d.best_cards == d.oldest_stock == []


def test_margin_helper():
    assert margin(D("1"), D("3")) == D("33.3")
    assert margin(D("2"), D("3")) == D("66.7")
    assert margin(D("1"), D("0")) is None


def test_dashboard_view(user, shop, client_for, django_assert_max_num_queries):
    client = client_for(user)
    # incl. het blok "Aandacht nodig" en het aanmaken van de drempels bij het eerste bezoek
    with django_assert_max_num_queries(20):
        resp = client.get(reverse("dashboard"), {"periode": "all"})
    assert resp.status_code == 200
    data = json.loads(json.dumps(resp.context["chart_data"]))  # moet JSON-serialiseerbaar zijn
    assert data["sets"]["labels"] == ["Prizm 2022", "Topps Chrome 2023"]
    assert data["sets"]["margin"] == ["63.2", "-21.8"]
    assert len(data["months"]["labels"]) == 12
    assert b'id="chart-data"' in resp.content
    assert b"Ander" not in resp.content


def test_dashboard_requires_login(client, db):
    resp = client.get(reverse("dashboard"))
    assert resp.status_code == 302


def test_login_redirects_to_dashboard(user, client):
    resp = client.post(reverse("login"), {"username": "alice", "password": "test-pass-123"})
    assert resp.url == reverse("dashboard")
