from decimal import Decimal as D

import pytest
from django.urls import reverse

from inventory import photos as photo_svc
from inventory.models import CardStatus, PhotoLabel
from sales import listing_generator as gen
from sales.forms import ListingTemplateForm
from sales.models import Listing, ListingStatus, ListingTemplate
from tests.test_photos import image_bytes, upload

TITLE = gen.DEFAULT_TITLE_PATTERN
DESC = gen.DEFAULT_DESCRIPTION_PATTERN


@pytest.fixture
def card(user, make_card):
    return make_card(
        user, cost="3.00", player="Erling Haaland", set_name="Topps Chrome", year=2023,
        card_number="15", variants=["rookie"], condition="near_mint",
    )


def add_front_and_back(card):
    photo_svc.add_photos(card, [upload(image_bytes(size=(50, 70)))], PhotoLabel.FRONT)
    photo_svc.add_photos(card, [upload(image_bytes(size=(50, 70)))], PhotoLabel.BACK)


# --- title -------------------------------------------------------------------

def test_default_title(card):
    add_front_and_back(card)
    result = gen.generate(card, TITLE, DESC)
    assert result.title == "2023 Topps Chrome Erling Haaland #15 Rookie Near Mint"
    assert not result.was_truncated
    assert result.warnings == []


def test_missing_fields_leave_no_debris(card):
    card.card_number = ""
    card.condition = ""
    card.variants = []
    result = gen.generate(card, TITLE, DESC)
    assert result.title == "2023 Topps Chrome Erling Haaland"  # no stray '#' or spaces
    assert any("card number" in w and "condition" in w for w in result.warnings)


def test_orphan_punctuation_is_removed():
    values = {"player": "Saka", "number": "", "condition": ""}
    text, empty = gen.render("{player} #{number} ({condition}) - [{number}] |", values, single_line=True)
    assert text == "Saka"
    assert empty == ["condition", "number"]


def test_special_characters_kept_and_control_chars_removed(card):
    card.player = "Kylian  Mbappé\n\tLottin\x00"
    card.set_name = "Topps Chrome UCL <Sapphire> & co"
    title = gen.generate(card, TITLE, DESC).title
    assert title == "2023 Topps Chrome UCL <Sapphire> & co Kylian Mbappé Lottin #15 Rookie Near Mint"
    assert "\n" not in title and "\x00" not in title


def test_unicode_is_normalised(card):
    card.player = "Martin Ödegaard"  # 'Ö' as two code points
    title = gen.generate(card, "{player}", "").title
    assert title == "Martin Ödegaard"
    assert len(title) == 15


def test_title_exactly_at_limit_is_not_truncated(card):
    card.player = "x" * (80 - len("2023 Topps Chrome  #15 Rookie Near Mint"))
    result = gen.generate(card, TITLE, DESC)
    assert len(result.title) == 80
    assert not result.was_truncated
    assert not any("was cut" in w for w in result.warnings)


def test_title_over_limit_is_cut_at_word_boundary(card):
    card.variants = ["rookie", "parallel"]
    card.parallel_name = "Gold Refractor centered sharp corners pack fresh straight from the box"
    result = gen.generate(card, TITLE, DESC)
    assert len(result.full_title) > 80
    assert len(result.title) <= 80
    assert result.full_title.startswith(result.title)
    assert result.full_title[len(result.title)] == " "  # not in the middle of a word
    warning = next(w for w in result.warnings if "was cut" in w)
    assert str(len(result.full_title)) in warning


def test_single_word_longer_than_limit_is_hard_cut():
    assert gen.truncate_title("y" * 100) == "y" * 80


def test_truncation_does_not_leave_trailing_hash():
    title = "a" * 78 + " # 9 Rookie"  # cutting at the word boundary leaves "aaa… #"
    assert gen.truncate_title(title) == "a" * 78


def test_card_values_are_not_reinterpreted_as_placeholders(card):
    card.player = "{set}"
    assert gen.generate(card, "{player}", "").title == "{set}"


def test_unknown_placeholder_raises():
    with pytest.raises(gen.PatternError, match="name"):
        gen.render("{player} {name}", {}, single_line=True)


# --- description -------------------------------------------------------------

def test_description_with_condition_notes_and_defects(card):
    card.notes = "Small white dot on the back.\nOtherwise sharp."
    photo_svc.add_photos(card, [upload(image_bytes(size=(50, 70)))], PhotoLabel.DEFECT)
    desc = gen.generate(card, TITLE, DESC).description
    assert "Condition: Near Mint" in desc
    assert "Small white dot on the back.\nOtherwise sharp." in desc
    assert "Note: 1 photo of defects included." in desc


def test_description_drops_empty_label_lines(card):
    card.variants = []
    card.notes = ""
    desc = gen.generate(card, TITLE, DESC).description
    assert "Variant:" not in desc
    assert "\n\n\n" not in desc


# --- photo checklist ---------------------------------------------------------

def test_photo_checklist_is_part_of_the_checks(card):
    assert "There are no photos yet." in gen.generate(card, TITLE, DESC).warnings
    photo_svc.add_photos(card, [upload(image_bytes(size=(50, 70)))], PhotoLabel.FRONT)
    assert "Back photo is missing." in gen.generate(card, TITLE, DESC).warnings


# --- template form -----------------------------------------------------------

def test_template_form_rejects_unknown_placeholders(user):
    form = ListingTemplateForm(
        {"name": "Short", "title_pattern": "{player} {playr}", "description_pattern": "{bla}"}, user=user
    )
    assert not form.is_valid()
    assert "{playr}" in form.errors["title_pattern"][0]
    assert "{bla}" in form.errors["description_pattern"][0]


def test_template_names_unique_per_user(user, other_user):
    ListingTemplate.objects.create(user=user, name="Short", title_pattern="{player}")
    data = {"name": "short", "title_pattern": "{player}", "description_pattern": ""}
    assert not ListingTemplateForm(data, user=user).is_valid()
    assert ListingTemplateForm(data, user=other_user).is_valid()


# --- views -------------------------------------------------------------------

def test_generator_page_prefills_generated_title(user, card, client_for):
    resp = client_for(user).get(reverse("sales:listing_generator", args=[card.pk]))
    assert resp.status_code == 200
    assert resp.context["form"].initial["title"] == "2023 Topps Chrome Erling Haaland #15 Rookie Near Mint"


def test_generator_with_own_template_via_htmx(user, card, client_for):
    tpl = ListingTemplate.objects.create(user=user, name="Short", title_pattern="{player} {year} RC")
    resp = client_for(user).get(
        reverse("sales:listing_generator", args=[card.pk]), {"template": tpl.pk}, HTTP_HX_REQUEST="true"
    )
    assert "sales/_listing_form.html" in [t.name for t in resp.templates]
    assert resp.context["form"].initial["title"] == "Erling Haaland 2023 RC"


def test_other_users_template_and_card_are_404(user, other_user, card, client_for):
    foreign = ListingTemplate.objects.create(user=other_user, name="X", title_pattern="{player}")
    client = client_for(user)
    resp = client.get(reverse("sales:listing_generator", args=[card.pk]), {"template": foreign.pk})
    assert resp.status_code == 404
    resp = client_for(other_user).get(reverse("sales:listing_generator", args=[card.pk]))
    assert resp.status_code == 404
    resp = client_for(other_user).get(reverse("sales:listing_profit", args=[card.pk]), {"asking_price": "5"})
    assert resp.status_code == 404
    resp = client_for(user).get(reverse("sales:template_edit", args=[foreign.pk]))
    assert resp.status_code == 404


def test_save_draft_then_update_same_listing(user, card, client_for):
    client = client_for(user)
    url = reverse("sales:listing_generator", args=[card.pk])
    client.post(url, {"title": "Title 1", "description": "", "asking_price": "9.99", "save": "1"})
    client.post(url, {"title": "Title 2", "description": "Text", "asking_price": "8.50", "save": "1"})
    listing = Listing.objects.get(card=card)
    assert (listing.title, listing.asking_price, listing.status) == ("Title 2", D("8.50"), ListingStatus.DRAFT)

    # Without ?template the page shows the saved version.
    resp = client.get(url)
    assert resp.context["form"].initial["title"] == "Title 2"
    assert resp.context["showing_saved"]
    assert b"Saved version" in resp.content


def test_saved_asking_price_survives_dutch_locale(user, card, client_for):
    """A type=number field does not accept '8,50'; the value must be '8.50' in any locale."""
    Listing.objects.create(card=card, title="x", asking_price=D("8.50"))
    resp = client_for(user).get(reverse("sales:listing_generator", args=[card.pk]))
    assert b'name="asking_price"' in resp.content
    assert b'value="8.50"' in resp.content


def test_activate_marks_card_for_sale(user, card, client_for):
    url = reverse("sales:listing_generator", args=[card.pk])
    client_for(user).post(url, {"title": "Haaland", "description": "", "asking_price": "9.99", "activate": "1"})
    listing = Listing.objects.get(card=card)
    card.refresh_from_db()
    assert listing.status == ListingStatus.ACTIVE and listing.listed_at
    assert card.status == CardStatus.FOR_SALE and card.listed_since


def test_title_over_80_is_rejected_on_save(user, card, client_for):
    resp = client_for(user).post(
        reverse("sales:listing_generator", args=[card.pk]),
        {"title": "x" * 81, "description": "", "asking_price": "1", "save": "1"},
    )
    assert resp.status_code == 200
    assert "title" in resp.context["form"].errors
    assert not Listing.objects.exists()


def test_html_in_card_data_is_escaped(user, card, client_for):
    card.notes = "<script>alert(1)</script>"
    card.save()
    resp = client_for(user).get(reverse("sales:listing_generator", args=[card.pk]))
    assert b"<script>alert(1)</script>" not in resp.content
    assert b"&lt;script&gt;alert(1)&lt;/script&gt;" in resp.content


def test_profit_preview_reuses_calculator(user, fee_profile, card, client_for):
    resp = client_for(user).get(reverse("sales:listing_profit", args=[card.pk]), {"asking_price": "10.00"})
    # 10.00 - (1.33 + 0.35) - 3.00 cost = 5.32
    assert resp.context["preview"].profit == D("5.32")
    resp = client_for(user).get(reverse("sales:listing_profit", args=[card.pk]), {"asking_price": "abc"})
    assert resp.context["preview"] is None


def test_sale_uses_the_generated_listing(user, fee_profile, card, client_for):
    from datetime import date

    from sales.services import register_sale

    client_for(user).post(
        reverse("sales:listing_generator", args=[card.pk]),
        {"title": "My title", "description": "", "asking_price": "9.99", "activate": "1"},
    )
    sale = register_sale(card, sale_price=D("9.50"), sold_at=date(2026, 10, 1))
    assert sale.listing.title == "My title"
    assert Listing.objects.filter(card=card).count() == 1
