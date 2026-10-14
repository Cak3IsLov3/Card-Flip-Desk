"""Multiple variants, parallel/insert names, serial numbers and condition choices."""

import importlib

import pytest
from django.apps import apps
from django.urls import reverse

from inventory.csv_import import import_cards
from inventory.forms import CardForm
from inventory.models import Card, normalise_serial, normalise_variants, parse_condition
from pricing.advice import search_query
from sales import listing_generator as gen

condition_migration = importlib.import_module("inventory.migrations.0007_condition_choices_and_serial")


# --- variants ----------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ([], []),
        (["base"], []),
        (["Auto", "rookie", "ROOKIE"], ["rookie", "auto"]),  # fixed order, no duplicates
        (["insert", "parallel", "auto", "rookie"], ["rookie", "auto", "parallel", "insert"]),
        ("rookie", ["rookie"]),
    ],
)
def test_normalise_variants(raw, expected):
    assert normalise_variants(raw) == expected


def test_unknown_variant_is_rejected():
    with pytest.raises(ValueError, match="holo"):
        normalise_variants(["rookie", "holo"])


def test_variant_display_and_title_labels(user, make_card):
    card = make_card(user, variants=["parallel", "rookie", "insert"], parallel_name="Gold Refractor",
                     parallel_serial="23/50", insert_name="Future Stars")
    assert card.variants == ["rookie", "parallel", "insert"]
    assert card.variant_display == "Rookie, Parallel (Gold Refractor 23/50), Insert (Future Stars)"
    assert card.variant_labels == ["Rookie", "Gold Refractor 23/50", "Future Stars"]
    assert make_card(user).variant_display == "Base"


def test_names_are_cleared_when_variant_is_unticked(user, make_card):
    card = make_card(user, variants=["parallel", "insert"], parallel_name="Refractor", parallel_serial="/99",
                     insert_name="Future Stars")
    card.variants = ["rookie"]
    card.save()
    card.refresh_from_db()
    assert (card.parallel_name, card.parallel_serial, card.insert_name) == ("", "", "")


def test_filter_by_variant(user, make_card, client_for):
    make_card(user, player="Base card")
    make_card(user, player="Rookie auto", variants=["rookie", "auto"])
    make_card(user, player="Parallel", variants=["parallel"])
    client = client_for(user)

    def players(variant):
        resp = client.get(reverse("inventory:card_list"), {"variant": variant})
        return sorted(c.player for c in resp.context["page"])

    assert players("auto") == ["Rookie auto"]
    assert players("rookie") == ["Rookie auto"]
    assert players("base") == ["Base card"]
    assert len(players("")) == 3


# --- serial number -----------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [("23/50", "23/50"), (" 23 / 50 ", "23/50"), ("/99", "/99"), ("", "")])
def test_normalise_serial(raw, expected):
    assert normalise_serial(raw) == expected


@pytest.mark.parametrize("raw", ["51/50", "abc", "23", "23/", "1/2/3"])
def test_invalid_serial(raw):
    with pytest.raises(ValueError):
        normalise_serial(raw)


def test_card_form_validates_serial_and_shows_fields_for_parallel():
    data = {"player": "Yamal", "set_name": "Topps Chrome", "year": "2024", "status": "in_stock",
            "variants": ["parallel"], "parallel_serial": "60/50"}
    form = CardForm(data)
    assert not form.is_valid()
    assert "parallel_serial" in form.errors
    html = str(CardForm()["parallel_serial"])
    assert 'data-show-with-variant="parallel"' in html


# --- remembered parallel and insert names ------------------------------------

def test_used_names_most_used_first_and_case_insensitive(user, other_user, make_card):
    for name in ["Gold Refractor", "Gold Refractor", "gold refractor", "Prizm Silver"]:
        make_card(user, variants=["parallel"], parallel_name=name)
    make_card(user, variants=["insert"], insert_name="Future Stars")
    make_card(other_user, variants=["parallel"], parallel_name="Someone Else's Parallel")
    own = Card.objects.owned_by(user)
    assert own.used_names("parallel_name") == ["Gold Refractor", "Prizm Silver"]
    assert own.used_names("insert_name") == ["Future Stars"]


def test_card_form_suggests_only_own_earlier_names(user, other_user, make_card, client_for):
    make_card(user, variants=["parallel"], parallel_name="Gold Refractor")
    make_card(user, variants=["insert"], insert_name="Future Stars")
    make_card(other_user, variants=["parallel"], parallel_name="Secret <b>Parallel</b>")
    html = client_for(user).get(reverse("inventory:card_create")).content.decode()
    assert 'list="id_parallel_name-suggestions"' in html
    assert '<datalist id="id_parallel_name-suggestions"><option value="Gold Refractor"></datalist>' in html
    assert '<option value="Future Stars">' in html
    assert "Secret" not in html


def test_card_form_suggests_earlier_players_sports_and_sets(user, other_user, make_card, client_for):
    make_card(user, player="Lamine Yamal", set_name="Topps Chrome", sport="Football")
    make_card(user, player="Lamine Yamal", set_name="Panini Prizm", sport="Football")
    make_card(user, player="Jude Bellingham", set_name="Panini Prizm", sport="Basketball")
    make_card(other_user, player="Hidden Player", set_name="Hidden Set", sport="Hidden Sport")
    html = client_for(user).get(reverse("inventory:card_create")).content.decode()
    assert ('<datalist id="id_player-suggestions"><option value="Lamine Yamal">'
            '<option value="Jude Bellingham"></datalist>') in html
    assert ('<datalist id="id_set_name-suggestions"><option value="Panini Prizm">'
            '<option value="Topps Chrome"></datalist>') in html
    assert ('<datalist id="id_sport-suggestions"><option value="Football">'
            '<option value="Basketball"></datalist>') in html
    assert "Hidden" not in html


def test_card_form_without_earlier_names_has_no_datalist(user, client_for):
    html = client_for(user).get(reverse("inventory:card_create")).content.decode()
    assert "<datalist" not in html


def test_suggestions_are_escaped(user, make_card):
    make_card(user, variants=["parallel"], parallel_name='Red "Wave" <i>')
    html = str(CardForm(user=user)["parallel_name"])
    assert '<option value="Red &quot;Wave&quot; &lt;i&gt;">' in html


# --- condition ---------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [("Near Mint", "near_mint"), ("NM-MT", "near_mint"), ("nm", "near_mint"), ("EX", "excellent"),
     ("Very good", "very_good"), ("mint", "mint"), ("", ""), ("slight crease", None)],
)
def test_parse_condition(raw, expected):
    assert parse_condition(raw) == expected


def test_condition_migration_maps_text_and_keeps_the_rest_in_notes(user, make_card):
    known = make_card(user, player="known")
    unknown = make_card(user, player="unknown", notes="Bought at a fair.")
    Card.objects.filter(pk=known.pk).update(condition="NM-MT")
    # The current column holds 20 characters (PostgreSQL enforces that; SQLite does not).
    Card.objects.filter(pk=unknown.pk).update(condition="crease top left")
    condition_migration.forwards(apps, None)
    known.refresh_from_db()
    unknown.refresh_from_db()
    assert known.condition == "near_mint"
    assert unknown.condition == ""
    assert unknown.notes == "Bought at a fair.\nCondition (before it became a choice): crease top left"


# --- where it is used --------------------------------------------------------

def test_title_uses_variant_names_and_condition_label(user, make_card):
    card = make_card(user, player="Lamine Yamal", set_name="Topps Chrome", year=2024, card_number="1",
                     variants=["rookie", "parallel"], parallel_name="Gold Refractor", parallel_serial="23/50",
                     condition="mint")
    title = gen.generate(card, gen.DEFAULT_TITLE_PATTERN, "").title
    assert title == "2024 Topps Chrome Lamine Yamal #1 Rookie Gold Refractor 23/50 Mint"
    assert gen.generate(card, "{player} {parallel} {serial}", "").title == "Lamine Yamal Gold Refractor 23/50"


def test_search_query_uses_print_run_not_exact_serial(user, make_card):
    card = make_card(user, player="Lamine Yamal", set_name="Topps Chrome", year=2024, card_number="1",
                     variants=["rookie", "parallel"], parallel_name="Gold Refractor", parallel_serial="23/50")
    assert search_query(card) == "2024 Topps Chrome Lamine Yamal 1 Rookie Gold Refractor /50"


def test_csv_import_multiple_variants_condition_and_serial(user):
    csv = (
        "player,set,year,variants,parallel,serial,condition\n"
        "Yamal,Topps Chrome,2024,Rookie/Parallel,Gold Refractor,23/50,NM\n"
        "Wemby,Prizm,2023,rookie auto,,,EX\n"
        "Bad,Prizm,2023,rookie,,,cracked\n"
        "Bad2,Prizm,2023,parallel,,99/50,mint\n"
    )
    mapping = {"player": "player", "set_name": "set", "year": "year", "variants": "variants",
               "parallel_name": "parallel", "parallel_serial": "serial", "condition": "condition"}
    report = import_cards(csv, mapping, user)
    assert report.created == 2
    assert [e.row for e in report.errors] == [4, 5]
    yamal = Card.objects.get(player="Yamal")
    assert (yamal.variants, yamal.parallel_name, yamal.parallel_serial, yamal.condition) == (
        ["rookie", "parallel"], "Gold Refractor", "23/50", "near_mint")
    assert Card.objects.get(player="Wemby").variants == ["rookie", "auto"]
