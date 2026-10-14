from decimal import Decimal as D

import pytest
from django.urls import reverse

from inventory.models import Card, CardStatus


def test_login_required(client, db):
    resp = client.get(reverse("inventory:card_list"))
    assert resp.status_code == 302
    assert reverse("login") in resp.url


def test_create_card_with_purchase(user, client_for):
    resp = client_for(user).post(
        reverse("inventory:card_create"),
        {
            "player": "Lamine Yamal",
            "set_name": "Topps Chrome",
            "year": "2024",
            "variants": ["rookie", "parallel"],
            "parallel_name": "Gold Refractor",
            "parallel_serial": "23 / 50",
            "condition": "mint",
            "status": "in_stock",
            "purchase-price": "7.50",
            "purchase-shipping_in": "1.00",
            "purchase-date": "2025-01-02",
        },
    )
    assert resp.status_code == 302
    card = Card.objects.get()
    assert card.owner == user
    assert card.total_cost == D("8.50")
    assert card.variants == ["rookie", "parallel"]
    assert (card.parallel_name, card.parallel_serial) == ("Gold Refractor", "23/50")
    assert card.variant_display == "Rookie, Parallel (Gold Refractor 23/50)"
    assert card.get_condition_display() == "Mint"


def test_create_card_without_purchase(user, client_for):
    resp = client_for(user).post(
        reverse("inventory:card_create"),
        {"player": "Kane", "set_name": "Topps", "year": "2021", "status": "in_stock",
         "purchase-shipping_in": "0.00"},
    )
    assert resp.status_code == 302
    card = Card.objects.get()
    assert not card.purchases.exists()
    assert card.variants == [] and card.variant_display == "Base"


def test_for_sale_sets_listed_since(user, client_for):
    client_for(user).post(
        reverse("inventory:card_create"),
        {"player": "Kane", "set_name": "Topps", "year": "2021", "status": "for_sale",
         "purchase-shipping_in": "0.00"},
    )
    assert Card.objects.get().listed_since is not None


def test_list_filters_and_totals(user, other_user, make_card, client_for):
    make_card(user, cost="5.00", player="Haaland")
    make_card(user, cost="2.00", player="Saka", set_name="Prizm", status=CardStatus.SOLD)
    make_card(other_user, cost="100.00", player="Haaland")

    client = client_for(user)
    resp = client.get(reverse("inventory:card_list"))
    assert resp.context["inventory_value"] == D("5.00")  # sold cards and other users' cards do not count
    assert len(resp.context["page"].object_list) == 2

    resp = client.get(reverse("inventory:card_list"), {"q": "haal"}, HTTP_HX_REQUEST="true")
    assert [c.player for c in resp.context["page"]] == ["Haaland"]
    assert "inventory/_card_table.html" in [t.name for t in resp.templates]

    resp = client.get(reverse("inventory:card_list"), {"status": "sold"})
    assert [c.player for c in resp.context["page"]] == ["Saka"]


@pytest.mark.parametrize(
    "name, method",
    [
        ("inventory:card_detail", "get"),
        ("inventory:card_update", "get"),
        ("inventory:card_update", "post"),
        ("inventory:card_delete", "get"),
        ("inventory:card_delete", "post"),
        ("inventory:purchase_add", "post"),
        ("sales:sale_create", "get"),
    ],
)
def test_other_user_cannot_see_or_change_card(name, method, user, other_user, make_card, client_for):
    card = make_card(user, cost="5.00")
    client = client_for(other_user)
    resp = getattr(client, method)(reverse(name, args=[card.pk]), {"player": "Stolen", "price": "1"})
    assert resp.status_code == 404
    card.refresh_from_db()
    assert card.player == "Erling Haaland"
    assert card.purchases.count() == 1


def test_calculator_prefill_from_other_users_card_is_404(user, other_user, make_card, client_for):
    card = make_card(user, cost="5.00")
    resp = client_for(other_user).get(reverse("finance:calculator"), {"card": card.pk})
    assert resp.status_code == 404


def test_calculator_view_forward_and_reverse(user, fee_profile, client_for):
    client = client_for(user)
    base = {"fee_profile": fee_profile.pk, "shipping_income": "2.50", "shipping_cost": "1.95",
            "packaging_cost": "0.30", "purchase_cost": "3.00"}
    resp = client.post(reverse("finance:calculator"), {**base, "mode": "forward", "sale_price": "10.00"},
                       HTTP_HX_REQUEST="true")
    assert resp.context["result"].profit == D("5.24")

    resp = client.post(reverse("finance:calculator"), {**base, "mode": "reverse", "target_profit": "5.24"})
    assert resp.context["required_price"] == D("9.99")


def test_fee_profiles_are_private(user, other_user, fee_profile, client_for):
    resp = client_for(other_user).get(reverse("finance:fee_profile_edit", args=[fee_profile.pk]))
    assert resp.status_code == 404
    resp = client_for(other_user).post(
        reverse("finance:calculator"),
        {"mode": "forward", "fee_profile": fee_profile.pk, "sale_price": "10"},
    )
    assert "fee_profile" in resp.context["form"].errors


def test_signup_creates_starter_fee_profile(client, db):
    resp = client.post(
        reverse("signup"),
        {"username": "carla", "password1": "a-long-password-42", "password2": "a-long-password-42"},
    )
    assert resp.status_code == 302
    from finance.models import FeeProfile

    assert FeeProfile.objects.filter(user__username="carla").count() == 1
