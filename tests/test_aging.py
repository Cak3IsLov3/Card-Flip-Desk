from datetime import date, timedelta
from decimal import Decimal as D
from io import StringIO

import pytest
from django.core import mail
from django.core.management import call_command
from django.urls import reverse

from inventory import aging
from inventory.digest import send_digests
from inventory.forms import StaleThresholdForm
from inventory.models import Card, CardStatus, InventoryNote, NoteKind, Purchase, StaleThreshold
from sales.dashboard import build_dashboard
from sales.models import Listing, ListingStatus

TODAY = date(2026, 10, 14)


def days_ago(n):
    return TODAY - timedelta(days=n)


@pytest.fixture
def for_sale(user, make_card):
    """Kaart die `age` dagen te koop staat, optioneel met vraagprijs."""

    def _make(age, cost="3.00", asking=None, owner=None, **kwargs):
        card = make_card(owner or user, cost=cost, status=CardStatus.FOR_SALE,
                         listed_since=days_ago(age), **kwargs)
        if asking:
            Listing.objects.create(card=card, title=str(card), asking_price=D(asking),
                                   status=ListingStatus.ACTIVE)
        return card

    return _make


# --- niveaus en leeftijd -----------------------------------------------------

@pytest.mark.parametrize(
    "age, expected",
    [(None, None), (0, None), (29, None), (30, "warning"), (31, "warning"), (59, "warning"),
     (60, "action"), (61, "action"), (89, "action"), (90, "critical"), (91, "critical"), (400, "critical")],
)
def test_level_boundaries(age, expected):
    t = StaleThreshold(warning_days=30, action_days=60, critical_days=90)
    assert aging.level_for(age, t) == expected


def test_age_start_rules(user, make_card):
    listed = make_card(user, cost="1", status=CardStatus.FOR_SALE, listed_since=days_ago(10), player="listed")
    in_stock = make_card(user, player="stock")
    Purchase.objects.create(card=in_stock, price=D("1"), date=days_ago(50))
    Purchase.objects.create(card=in_stock, price=D("1"), date=days_ago(40))
    for_sale_no_date = make_card(user, cost="1", status=CardStatus.FOR_SALE, player="nodate")  # inkoop 2024-05-01
    no_purchase = make_card(user, player="empty")

    starts = {c.player: c.age_start for c in Card.objects.with_age_start()}
    assert starts["listed"] == days_ago(10)
    assert starts["stock"] == days_ago(50)  # eerste inkoop
    assert starts["nodate"] == date(2024, 5, 1)
    assert starts["empty"] == no_purchase.created_at.date()


# --- welke kaarten verschijnen -----------------------------------------------

@pytest.mark.parametrize("age, shown", [(29, False), (30, True), (31, True)])
def test_threshold_boundary(user, for_sale, age, shown):
    for_sale(age)
    assert bool(aging.stale_items(user, TODAY)) is shown


def test_pinned_cards_are_not_shown(user, for_sale):
    card = for_sale(100)
    card.held_until = TODAY  # tot en met vandaag vast
    card.save()
    assert aging.stale_items(user, TODAY) == []
    card.held_until = days_ago(1)  # verlopen
    card.save()
    assert [i.card for i in aging.stale_items(user, TODAY)] == [card]


def test_sold_and_foreign_cards_are_not_shown(user, other_user, for_sale):
    sold = for_sale(100)
    sold.status = CardStatus.SOLD
    sold.save()
    for_sale(100, owner=other_user)
    assert aging.stale_items(user, TODAY) == []


def test_custom_thresholds(user, for_sale):
    StaleThreshold.objects.create(user=user, warning_days=7, action_days=14, critical_days=21)
    for_sale(7)
    for_sale(14, player="b")
    items = aging.stale_items(user, TODAY)
    assert [i.level for i in items] == ["action", "warning"]  # oudste eerst


# --- voorstellen -------------------------------------------------------------

def test_warning_advice(user, for_sale):
    for_sale(35)
    item = aging.stale_items(user, TODAY)[0]
    assert item.level == "warning"
    assert "foto" in item.advice.lower()


def test_price_suggestion_reuses_calculator(user, fee_profile, for_sale):
    for_sale(65, cost="3.00", asking="10.00")
    item = aging.stale_items(user, TODAY)[0]
    assert item.level == "action"
    assert item.price.new_price == D("9.00")  # 10% van 10,00
    assert item.price.current.profit == D("5.32")  # 10 - 1,68 - 3
    assert item.price.new.profit == D("4.46")  # 9 - (1,19 + 0,35) - 3
    assert item.price.new.margin == D("49.6")
    assert not item.price.is_loss


def test_price_suggestion_with_negative_profit_warns(user, fee_profile, for_sale):
    for_sale(65, cost="9.00", asking="10.00")
    summary = aging.attention(user, TODAY)
    item = summary.items[0]
    assert item.price.new.profit == D("-1.54")
    assert item.price.is_loss
    assert summary.losses == [item]


def test_action_without_listing_asks_for_price(user, for_sale):
    for_sale(65)
    item = aging.stale_items(user, TODAY)[0]
    assert item.price is None
    assert "vraagprijs" in item.advice


def test_critical_suggests_bundle_or_write_off(user, for_sale, make_card):
    a = for_sale(95, set_name="Prizm", year=2022, player="a")
    for_sale(120, set_name="Prizm", year=2022, player="b")
    make_card(user, set_name="Prizm", year=2022, player="c")  # jong, telt mee voor de bundel
    alone = for_sale(100, set_name="Select", year=2021, player="d")
    items = {i.card.pk: i for i in aging.stale_items(user, TODAY)}
    assert items[a.pk].bundle_with == 2
    assert "Bundel met 2" in items[a.pk].advice
    assert items[alone.pk].bundle_with == 0
    assert "Afschrijven" in items[alone.pk].advice


def test_summary_totals_and_dashboard(user, fee_profile, for_sale):
    for_sale(30, cost="1.00")
    for_sale(60, cost="2.50", player="b")
    for_sale(90, cost="4.00", player="c")
    for_sale(10, cost="100.00", player="young")  # telt niet mee
    summary = aging.attention(user, TODAY)
    assert summary.total == D("7.50")
    assert summary.counts == {"warning": 1, "action": 1, "critical": 1}
    assert [i.card.player for i in summary.items] == ["c", "b", "Erling Haaland"]

    dash = build_dashboard(user, today=TODAY)
    assert dash.attention.total == D("7.50")


def test_stale_query_count_is_bounded(user, fee_profile, for_sale, django_assert_max_num_queries):
    for i in range(8):
        for_sale(40 + i * 10, asking="10.00", player=f"p{i}")
    StaleThreshold.for_user(user)  # bestaat in de praktijk al na het eerste bezoek
    # drempels, kaarten, listings (prefetch), kostenprofiel, aantallen per set
    with django_assert_max_num_queries(5):
        items = aging.stale_items(user, TODAY)
        [i.price for i in items]
    assert len(items) == 8


# --- instellingen ------------------------------------------------------------

def test_threshold_form_requires_increasing_values(user):
    t = StaleThreshold.for_user(user)
    form = StaleThresholdForm({"warning_days": 60, "action_days": 30, "critical_days": 90,
                               "price_drop_percentage": "10", "weekly_email": ""}, instance=t)
    assert not form.is_valid()
    form = StaleThresholdForm({"warning_days": 20, "action_days": 40, "critical_days": 80,
                               "price_drop_percentage": "15", "weekly_email": "on"}, instance=t)
    assert not form.is_valid() and "email" in form.errors  # mail aan maar geen adres
    form = StaleThresholdForm({"warning_days": 20, "action_days": 40, "critical_days": 80,
                               "price_drop_percentage": "15", "weekly_email": "on", "email": "a@example.com"},
                              instance=t)
    assert form.is_valid()
    form.save()
    user.refresh_from_db()
    assert user.email == "a@example.com"


# --- views -------------------------------------------------------------------

def test_attention_page_and_card_list_colours(user, for_sale, client_for):
    for_sale(95)
    client = client_for(user)
    assert client.get(reverse("inventory:attention")).status_code == 200
    resp = client.get(reverse("inventory:card_list"))
    assert b"badge-critical" in resp.content and b"kritiek" in resp.content


def test_pin_and_unpin(user, for_sale, client_for):
    card = for_sale(95)
    client = client_for(user)
    until = (date.today() + timedelta(days=30)).isoformat()
    client.post(reverse("inventory:pin_card", args=[card.pk]), {"held_until": until})
    card.refresh_from_db()
    assert card.held_until.isoformat() == until
    assert InventoryNote.objects.get(card=card).kind == NoteKind.PINNED
    client.post(reverse("inventory:unpin_card", args=[card.pk]))
    card.refresh_from_db()
    assert card.held_until is None


def test_pin_in_the_past_rejected(user, for_sale, client_for):
    card = for_sale(95)
    client_for(user).post(reverse("inventory:pin_card", args=[card.pk]), {"held_until": "2020-01-01"})
    card.refresh_from_db()
    assert card.held_until is None


def test_pin_does_not_open_redirect(user, for_sale, client_for):
    card = for_sale(95)
    resp = client_for(user).post(
        reverse("inventory:pin_card", args=[card.pk]),
        {"held_until": (date.today() + timedelta(days=5)).isoformat(), "next": "https://evil.example/"},
    )
    assert resp.url == reverse("inventory:attention")


def test_price_apply_and_preview(user, fee_profile, for_sale, client_for):
    card = for_sale(65, cost="9.00", asking="10.00")
    client = client_for(user)
    resp = client.get(reverse("inventory:price_preview", args=[card.pk]), {"percentage": "10"},
                      HTTP_HX_REQUEST="true")
    assert resp.context["price"].new_price == D("9.00")
    assert "verlies".encode() in resp.content

    client.post(reverse("inventory:price_apply", args=[card.pk]), {"percentage": "10"})
    assert Listing.objects.get(card=card).asking_price == D("9.00")
    note = InventoryNote.objects.get(card=card, kind=NoteKind.PRICE_LOWERED)
    assert note.details == {"old": "10.00", "new": "9.00", "percentage": "10"}


@pytest.mark.parametrize("name", ["inventory:pin_card", "inventory:unpin_card", "inventory:price_apply"])
def test_other_user_cannot_act(name, user, other_user, for_sale, client_for):
    card = for_sale(95, asking="10.00")
    resp = client_for(other_user).post(reverse(name, args=[card.pk]),
                                       {"held_until": "2099-01-01", "percentage": "50"})
    assert resp.status_code == 404
    assert Listing.objects.get(card=card).asking_price == D("10.00")
    assert not InventoryNote.objects.exists()


# --- wekelijkse mail ---------------------------------------------------------

@pytest.fixture
def mail_user(user):
    user.email = "alice@example.com"
    user.save()
    StaleThreshold.for_user(user)
    return user


def test_digest_sends_nothing_when_nothing_to_report(mail_user, for_sale):
    for_sale(5)
    result = send_digests(TODAY)
    assert mail.outbox == []
    assert result.skipped_nothing_to_report == ["alice"]


def test_digest_sends_one_message(mail_user, fee_profile, for_sale):
    for_sale(65, cost="9.00", asking="10.00")
    send_digests(TODAY)
    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert msg.to == ["alice@example.com"]
    assert msg.subject == "Card Flip Desk: 1 kaart vragen aandacht"
    assert "65 dagen" in msg.body and "LET OP: verlies" in msg.body
    assert "/aandacht/" in msg.body
    assert msg.alternatives[0].mimetype == "text/html"


def test_digest_once_per_week_unless_forced(mail_user, for_sale):
    for_sale(40)
    send_digests(TODAY)
    send_digests(TODAY + timedelta(days=6))
    assert len(mail.outbox) == 1
    send_digests(TODAY + timedelta(days=6), force=True)
    send_digests(TODAY + timedelta(days=13))
    assert len(mail.outbox) == 3


def test_digest_respects_opt_out_and_missing_email(mail_user, other_user, for_sale):
    for_sale(40)
    for_sale(40, owner=other_user)  # bob heeft geen e-mailadres
    StaleThreshold.for_user(other_user)
    mail_user.stale_threshold.weekly_email = False
    mail_user.stale_threshold.save()
    assert send_digests(TODAY).sent == []
    assert mail.outbox == []


def test_digest_dry_run(mail_user, for_sale):
    for_sale(40)
    assert send_digests(TODAY, dry_run=True).sent == ["alice"]
    assert mail.outbox == []
    mail_user.stale_threshold.refresh_from_db()
    assert mail_user.stale_threshold.last_digest_sent_on is None


def test_management_command(mail_user, for_sale):
    for_sale(40)
    out = StringIO()
    call_command("send_stale_digest", "--today", "2026-10-14", stdout=out)
    assert "Verstuurd naar: alice" in out.getvalue()
    assert len(mail.outbox) == 1
