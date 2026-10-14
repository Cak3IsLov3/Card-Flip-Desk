"""Shipping methods: starter list, filling in the shipping cost, own data only."""

import importlib
from decimal import Decimal as D

import pytest
from django.urls import reverse

from finance.forms import CalculatorForm
from finance.models import FeeProfile, ShippingMethod
from finance.starter import STARTER_SHIPPING, create_starter_costs
from sales.models import Sale

starter_migration = importlib.import_module("finance.migrations.0005_starter_shipping_methods")


@pytest.fixture
def kompaktbrief(user):
    return ShippingMethod.objects.create(user=user, name="Deutsche Post Kompaktbrief", cost=D("1.10"))


# --- starter list ------------------------------------------------------------

def test_signup_gets_dhl_shipping_methods(client, db):
    client.post(
        reverse("signup"),
        {"username": "carla", "password1": "a-long-password-42", "password2": "a-long-password-42"},
    )
    methods = ShippingMethod.objects.filter(user__username="carla")
    assert methods.count() == len(STARTER_SHIPPING)
    assert methods.get(name="Deutsche Post Großbrief").cost == D("1.80")
    assert methods.get(name="DHL Päckchen S").cost == D("4.19")
    assert methods.first().name == "Deutsche Post Standardbrief"  # cheapest first


def test_create_starter_costs_gives_free_private_fee_profile(user):
    create_starter_costs(user)
    profile = FeeProfile.objects.get(user=user)
    assert (profile.commission_percentage, profile.fixed_fee, profile.payment_percentage) == (0, 0, 0)
    assert user.shipping_methods.count() == len(STARTER_SHIPPING)


def test_migration_copy_of_the_starter_list_matches():
    assert starter_migration.STARTER_SHIPPING == STARTER_SHIPPING


def test_migration_fills_only_users_without_methods(user, other_user, kompaktbrief):
    from django.apps import apps

    starter_migration.forwards(apps, None)
    assert user.shipping_methods.count() == 1  # already had one, left alone
    assert other_user.shipping_methods.count() == len(STARTER_SHIPPING)


# --- filling in the shipping cost --------------------------------------------

def calculator_data(**extra):
    return {"mode": "forward", "sale_price": "20.00", "shipping_income": "1.95", "shipping_cost": "0",
            "packaging_cost": "0", "purchase_cost": "12.00", **extra}


def test_calculator_uses_method_cost_when_cost_left_at_zero(user, fee_profile, kompaktbrief):
    form = CalculatorForm(user, calculator_data(fee_profile=fee_profile.pk, shipping_method=kompaktbrief.pk))
    assert form.is_valid(), form.errors
    assert form.cleaned_data["shipping_cost"] == D("1.10")
    assert "shipping_method" not in form.cleaned_data


def test_typed_shipping_cost_wins_over_method(user, fee_profile, kompaktbrief):
    data = calculator_data(fee_profile=fee_profile.pk, shipping_method=kompaktbrief.pk, shipping_cost="2.40")
    form = CalculatorForm(user, data)
    assert form.is_valid()
    assert form.cleaned_data["shipping_cost"] == D("2.40")


def test_options_carry_their_cost_for_the_script(user, fee_profile, kompaktbrief):
    html = str(CalculatorForm(user)["shipping_method"])
    assert 'data-fills="shipping_cost"' in html
    assert f'<option value="{kompaktbrief.pk}" data-cost="1.10">' in html
    assert "Other (enter the cost yourself)" in html


def test_sale_with_shipping_method_stores_the_amount(user, fee_profile, kompaktbrief, make_card, client_for):
    card = make_card(user, cost="3.00")
    resp = client_for(user).post(
        reverse("sales:sale_create", args=[card.pk]),
        {"sale_price": "10.00", "shipping_income": "1.95", "shipping_method": kompaktbrief.pk,
         "shipping_cost": "", "packaging_cost": "0", "sold_at": "2025-04-02", "category": "Sports cards"},
    )
    assert resp.status_code == 302
    sale = Sale.objects.get()
    assert sale.shipping_cost == D("1.10")
    # A later price change does not alter the sale.
    kompaktbrief.cost = D("1.25")
    kompaktbrief.save()
    sale.refresh_from_db()
    assert sale.shipping_cost == D("1.10")


def test_other_users_method_is_not_a_valid_choice(user, other_user, fee_profile):
    theirs = ShippingMethod.objects.create(user=other_user, name="Secret courier", cost=D("0.01"))
    form = CalculatorForm(user, calculator_data(fee_profile=fee_profile.pk, shipping_method=theirs.pk))
    assert not form.is_valid()
    assert "shipping_method" in form.errors
    assert "Secret courier" not in str(CalculatorForm(user)["shipping_method"])


# --- managing methods --------------------------------------------------------

def test_add_edit_and_delete_method(user, client_for):
    client = client_for(user)
    resp = client.post(reverse("finance:shipping_methods"), {"name": "Hermes Päckchen", "cost": "4.50", "note": ""})
    assert resp.status_code == 302
    method = ShippingMethod.objects.get(user=user)
    url = reverse("finance:shipping_method_edit", args=[method.pk])
    client.post(url, {"name": "Hermes Päckchen", "cost": "4.75", "note": "Tracking"})
    method.refresh_from_db()
    assert (method.cost, method.note) == (D("4.75"), "Tracking")
    client.post(url, {"delete": "1"})
    assert not ShippingMethod.objects.filter(pk=method.pk).exists()


def test_duplicate_name_is_rejected(user, kompaktbrief, client_for):
    resp = client_for(user).post(
        reverse("finance:shipping_methods"), {"name": "deutsche post kompaktbrief", "cost": "1.00"}
    )
    assert resp.status_code == 200
    assert "already have a shipping method" in resp.content.decode()


def test_negative_cost_is_rejected(user, client_for):
    resp = client_for(user).post(reverse("finance:shipping_methods"), {"name": "Odd", "cost": "-1"})
    assert resp.status_code == 200
    assert not ShippingMethod.objects.exists()


@pytest.mark.parametrize("method", ["get", "post"])
def test_other_user_gets_404(method, other_user, kompaktbrief, client_for):
    url = reverse("finance:shipping_method_edit", args=[kompaktbrief.pk])
    resp = getattr(client_for(other_user), method)(url, {"delete": "1"} if method == "post" else None)
    assert resp.status_code == 404
    assert ShippingMethod.objects.filter(pk=kompaktbrief.pk).exists()


def test_list_shows_only_own_methods(user, other_user, kompaktbrief, client_for):
    ShippingMethod.objects.create(user=other_user, name="Their courier", cost=D("3.00"))
    html = client_for(user).get(reverse("finance:shipping_methods")).content.decode()
    assert "Deutsche Post Kompaktbrief" in html
    assert "Their courier" not in html
