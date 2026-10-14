from datetime import date
from decimal import Decimal as D

import pytest

from finance.calculator import CostInput, Fees, calculate, money, required_price
from finance.models import FeeProfile

EBAY = Fees(commission_percentage=D("13.25"), fixed_fee=D("0.35"))


def test_known_example():
    r = calculate(
        CostInput(
            sale_price=D("10.00"),
            shipping_income=D("2.50"),
            shipping_cost=D("1.95"),
            packaging_cost=D("0.30"),
            purchase_cost=D("3.00"),
        ),
        EBAY,
    )
    assert r.gross == D("12.50")
    assert r.commission == D("2.01")  # 1.65625 -> 1.66, + 0.35 vast
    assert r.payment_fee == D("0.00")
    assert r.net_proceeds == D("8.24")
    assert r.profit == D("5.24")
    assert r.margin == D("41.9")
    assert not r.is_loss


def test_payment_fee_is_rounded_separately():
    fees = Fees(commission_percentage=D("10"), payment_percentage=D("2.9"), fixed_fee=D("0.30"))
    r = calculate(CostInput(sale_price=D("19.99")), fees)
    assert r.commission == D("2.30")  # 1.999 -> 2.00 + 0.30
    assert r.payment_fee == D("0.58")  # 0.57971 -> 0.58
    assert r.net_proceeds == D("17.11")


@pytest.mark.parametrize(
    "price, expected",
    [
        (D("0.05"), D("0.01")),  # 0.005 -> half up
        (D("0.25"), D("0.03")),  # 0.025 -> 0.03 (bankiers-afronding zou 0.02 geven)
        (D("0.04"), D("0.00")),  # 0.004 -> omlaag
        (D("0.15"), D("0.02")),  # 0.015 -> half up
    ],
)
def test_rounding_boundaries_half_up(price, expected):
    r = calculate(CostInput(sale_price=price), Fees(commission_percentage=D("10")))
    assert r.commission == expected


def test_zero_profit():
    r = calculate(CostInput(sale_price=D("5.00"), purchase_cost=D("5.00")), Fees(D("0")))
    assert r.profit == D("0.00")
    assert r.margin == D("0.0")
    assert not r.is_loss


def test_negative_profit():
    r = calculate(CostInput(sale_price=D("1.00"), purchase_cost=D("2.00")), EBAY)
    # commissie 0.1325 -> 0.13 + 0.35 = 0.48; netto 0.52; winst -1.48
    assert r.commission == D("0.48")
    assert r.profit == D("-1.48")
    assert r.margin == D("-148.0")
    assert r.is_loss


def test_zero_gross_has_no_margin():
    r = calculate(CostInput(sale_price=D("0")), Fees(D("13.25")))
    assert r.margin is None


def test_float_is_rejected():
    with pytest.raises(TypeError):
        calculate(CostInput(sale_price=9.99), EBAY)
    with pytest.raises(TypeError):
        money(0.1)


@pytest.mark.parametrize(
    "fees",
    [
        EBAY,
        Fees(commission_percentage=D("10"), payment_percentage=D("2.9"), fixed_fee=D("0.30")),
        Fees(commission_percentage=D("15.6"), fixed_fee=D("0.00")),
        Fees(commission_percentage=D("0")),
    ],
)
def test_reverse_calculator_round_trips(fees):
    extras = dict(
        shipping_income=D("2.50"),
        shipping_cost=D("1.95"),
        packaging_cost=D("0.30"),
        purchase_cost=D("4.00"),
    )
    for cents in range(0, 5001, 37):  # doelwinst 0,00 .. 50,00 in onregelmatige stappen
        target = D(cents) / 100
        price = required_price(target, fees, **extras)
        assert calculate(CostInput(price, **extras), fees).profit == target, target
        # Het is ook de laagste prijs die dat haalt.
        if price > 0:
            assert calculate(CostInput(price - D("0.01"), **extras), fees).profit < target


def test_reverse_known_value():
    price = required_price(D("5.24"), EBAY, shipping_income=D("2.50"), shipping_cost=D("1.95"),
                           packaging_cost=D("0.30"), purchase_cost=D("3.00"))
    # Bij 10,00 is de winst 5,24, maar bij 9,99 ook: de commissie rondt dan
    # af naar 1,65 in plaats van 1,66. De laagste prijs wint.
    assert price == D("9.99")


def test_reverse_negative_target_allowed():
    price = required_price(D("-1.00"), EBAY, purchase_cost=D("3.00"))
    assert calculate(CostInput(price, purchase_cost=D("3.00")), EBAY).profit == D("-1.00")


def test_reverse_impossible_rate():
    with pytest.raises(ValueError):
        required_price(D("1"), Fees(commission_percentage=D("60"), payment_percentage=D("40")))


def test_fee_profile_current_for_picks_latest_valid(user):
    old = FeeProfile.objects.create(user=user, commission_percentage=D("12.00"), valid_from=date(2024, 1, 1))
    new = FeeProfile.objects.create(user=user, commission_percentage=D("13.25"), valid_from=date(2025, 3, 1))
    FeeProfile.objects.create(user=user, category="Overig", commission_percentage=D("9"), valid_from=date(2025, 6, 1))

    assert FeeProfile.objects.current_for(user, "Sportkaarten", date(2025, 2, 28)) == old
    assert FeeProfile.objects.current_for(user, "Sportkaarten", date(2025, 3, 1)) == new
    assert FeeProfile.objects.current_for(user, "Sportkaarten", date(2023, 12, 31)) is None
    assert new.to_fees().commission_percentage == D("13.25")
