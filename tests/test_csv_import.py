from decimal import Decimal as D

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from inventory.csv_import import decode, import_cards, suggest_mapping
from inventory.models import Card

MAPPING = {
    "player": "Player",
    "set_name": "Set",
    "year": "Year",
    "card_number": "Number",
    "variants": "Variant",
    "purchase_price": "Cost",
}

CSV = (
    "Player;Set;Year;Number;Variant;Cost\n"
    "Haaland;Topps Chrome;2023;15;rookie;4,50\n"
    ";Topps Chrome;2023;16;;1,00\n"  # player missing
    "Mbappé;Prizm;abc;7;;2\n"  # invalid year
    "\n"  # blank line is skipped
    "Bellingham;Topps;2022;3;holo;\n"  # unknown variant
    "Saka;Topps;2022;9;;€ 0,99\n"
)


def test_bad_rows_reported_without_blocking_good_rows(user):
    report = import_cards(CSV, MAPPING, user)

    assert report.created == 2
    assert [e.row for e in report.errors] == [3, 4, 6]
    assert "Player" in report.errors[0].errors
    assert "Year" in report.errors[1].errors
    assert "Variants" in report.errors[2].errors

    haaland = Card.objects.get(player="Haaland")
    assert haaland.owner == user
    assert haaland.variants == ["rookie"]
    assert haaland.total_cost == D("4.50")
    assert Card.objects.get(player="Saka").total_cost == D("0.99")


def test_empty_variant_defaults_to_base(user):
    import_cards("player,set,year\nKane,Topps,2021\n", {"player": "player", "set_name": "set", "year": "year"}, user)
    card = Card.objects.get()
    assert card.variants == []
    assert not card.purchases.exists()


def test_missing_required_mapping_raises(user):
    with pytest.raises(ValueError, match="Year"):
        import_cards("a,b\n1,2\n", {"player": "a", "set_name": "b"}, user)


def test_purchase_details_without_price_is_an_error(user):
    report = import_cards(
        "p,s,y,d\nKane,Topps,2021,2024-01-01\n",
        {"player": "p", "set_name": "s", "year": "y", "purchase_date": "d"},
        user,
    )
    assert report.created == 0
    assert "Purchase price" in report.errors[0].errors


def test_suggest_mapping_recognises_headers():
    mapping = suggest_mapping(["Player", "Set", "Year", "#", "Price"])
    assert mapping == {
        "player": "Player",
        "set_name": "Set",
        "year": "Year",
        "card_number": "#",
        "purchase_price": "Price",
    }


def test_suggest_mapping_also_recognises_dutch_headers():
    mapping = suggest_mapping(["Speler", "Jaar", "Inkoopprijs"])
    assert mapping == {"player": "Speler", "year": "Jaar", "purchase_price": "Inkoopprijs"}


def test_decode_handles_bom_and_cp1252():
    assert decode("\ufeffPlayer\n".encode("utf-8")) == "Player\n"
    assert decode("Mbappé".encode("cp1252")) == "Mbappé"


def test_upload_and_map_flow(user, client_for):
    client = client_for(user)
    upload = SimpleUploadedFile("cards.csv", CSV.encode("utf-8"), content_type="text/csv")
    resp = client.post(reverse("inventory:csv_upload"), {"file": upload})
    assert resp.status_code == 302

    resp = client.get(reverse("inventory:csv_map"))
    assert resp.status_code == 200
    # the suggested mapping is already selected
    assert resp.context["form"].initial["player"] == "Player"

    data = {k: v for k, v in MAPPING.items()}
    resp = client.post(reverse("inventory:csv_map"), data)
    assert resp.status_code == 200
    assert resp.context["report"].created == 2
    assert Card.objects.filter(owner=user).count() == 2
