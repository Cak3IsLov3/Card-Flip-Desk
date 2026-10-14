import io
from decimal import Decimal as D

import pytest
from django.core.cache import cache
from django.urls import reverse
from PIL import ExifTags, Image
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from inventory.models import Card, CardPhoto, CardStatus, PhotoLabel, Purchase
from sales.models import Listing, Sale
from tests.test_photos import gps_exif, image_bytes, upload

pytestmark = pytest.mark.django_db


@pytest.fixture
def api(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Token " + Token.objects.create(user=user).key)
    return client


@pytest.fixture
def other_api(other_user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Token " + Token.objects.create(user=other_user).key)
    return client


def url(name, *args):
    return reverse(f"api:{name}", args=args)


# --- authentication ------------------------------------------------------------

def test_requires_authentication(db):
    assert APIClient().get(url("card-list")).status_code == 401


def test_invalid_token_rejected(db):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Token fake")
    assert client.get(url("card-list")).status_code == 401


def test_obtain_token_and_use_it(user):
    resp = APIClient().post(url("token"), {"username": "alice", "password": "test-pass-123"})
    assert resp.status_code == 200
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Token " + resp.data["token"])
    assert client.get(url("card-list")).status_code == 200


def test_token_endpoint_is_throttled(user):
    cache.clear()
    client = APIClient()
    codes = [client.post(url("token"), {"username": "alice", "password": "wrong"}).status_code for _ in range(11)]
    assert codes[:10] == [400] * 10
    assert codes[10] == 429


def test_token_page_creates_and_revokes(user, client_for):
    client = client_for(user)
    client.post(reverse("api_token"), {"create": "1"})
    first = Token.objects.get(user=user).key
    client.post(reverse("api_token"), {"create": "1"})
    assert Token.objects.get(user=user).key != first
    client.post(reverse("api_token"), {"revoke": "1"})
    assert not Token.objects.filter(user=user).exists()


# --- cards and ownership -------------------------------------------------------

def test_card_crud(api, user):
    resp = api.post(url("card-list"), {"player": "Saka", "set_name": "Prizm", "year": 2022, "variant": "base"},
                    format="json")
    assert resp.status_code == 201
    card_id = resp.data["id"]
    assert Card.objects.get(pk=card_id).owner == user
    assert resp.data["total_cost"] == "0.00"

    api.post(url("purchase-list"), {"card": card_id, "price": "2.50", "shipping_in": "0.50", "date": "2026-01-02"},
             format="json")
    resp = api.get(url("card-detail", card_id))
    assert resp.data["total_cost"] == "3.00"
    assert resp.data["purchases"][0]["price"] == "2.50"

    assert api.patch(url("card-detail", card_id), {"condition": "Mint"}, format="json").data["condition"] == "Mint"
    assert api.delete(url("card-detail", card_id)).status_code == 204
    assert not Card.objects.exists()


def test_card_list_filters_and_isolation(api, user, other_user, make_card):
    make_card(user, player="Haaland", status=CardStatus.FOR_SALE)
    make_card(user, player="Saka", set_name="Prizm", year=2022)
    make_card(other_user, player="Haaland")
    resp = api.get(url("card-list"))
    assert resp.data["count"] == 2
    assert [c["player"] for c in api.get(url("card-list"), {"q": "haal"}).data["results"]] == ["Haaland"]
    assert [c["player"] for c in api.get(url("card-list"), {"status": "for_sale"}).data["results"]] == ["Haaland"]
    assert [c["player"] for c in api.get(url("card-list"), {"year": "2022"}).data["results"]] == ["Saka"]


@pytest.mark.parametrize("method", ["get", "patch", "put", "delete"])
def test_other_user_cannot_touch_card(method, other_api, user, make_card):
    card = make_card(user, player="Haaland")
    resp = getattr(other_api, method)(url("card-detail", card.pk), {"player": "Stolen"}, format="json")
    assert resp.status_code == 404
    card.refresh_from_db()
    assert card.player == "Haaland"


@pytest.mark.parametrize(
    "name, payload",
    [
        ("purchase-list", {"price": "1.00", "date": "2026-01-01"}),
        ("listing-list", {"title": "x", "asking_price": "1.00"}),
        ("sale-list", {"sale_price": "1.00", "sold_at": "2026-01-01"}),
    ],
)
def test_cannot_reference_other_users_card(name, payload, other_api, user, make_card):
    card = make_card(user)
    resp = other_api.post(url(name), {**payload, "card": card.pk}, format="json")
    assert resp.status_code == 400
    assert "card" in resp.data
    assert not Purchase.objects.exists() and not Listing.objects.exists() and not Sale.objects.exists()


def test_other_users_purchases_and_listings_invisible(api, other_user, make_card):
    card = make_card(other_user, cost="5.00")
    Listing.objects.create(card=card, title="x", asking_price=D("1"))
    assert api.get(url("purchase-list")).data["count"] == 0
    assert api.get(url("listing-list")).data["count"] == 0
    assert api.get(url("purchase-detail", card.purchases.get().pk)).status_code == 404


# --- photos ------------------------------------------------------------------

def test_photo_upload_download_and_exif(api, user, make_card):
    card = make_card(user)
    resp = api.post(url("photo-list"), {"card": card.pk, "label": "front",
                                        "file": upload(image_bytes(exif=gps_exif()))}, format="multipart")
    assert resp.status_code == 201, resp.data
    assert resp.data["is_main"] and resp.data["label"] == "front"
    assert resp.data["file_url"].endswith(url("photo-file", resp.data["id"]))

    file_resp = api.get(url("photo-file", resp.data["id"]))
    assert file_resp.status_code == 200 and file_resp["Content-Type"] == "image/jpeg"
    img = Image.open(io.BytesIO(b"".join(file_resp.streaming_content)))
    assert ExifTags.Base.Make not in img.getexif()


def test_photo_upload_rejects_fake_image(api, user, make_card):
    card = make_card(user)
    resp = api.post(url("photo-list"), {"card": card.pk, "file": upload(b"not a photo" * 50, "x.jpg")},
                    format="multipart")
    assert resp.status_code == 400
    assert "not a valid image" in resp.data["file"][0]


def test_photo_label_set_main_and_delete(api, user, make_card):
    card = make_card(user)
    ids = [api.post(url("photo-list"), {"card": card.pk, "file": upload(image_bytes(size=(50, 70)))},
                    format="multipart").data["id"] for _ in range(2)]
    assert api.patch(url("photo-detail", ids[1]), {"label": "back"}, format="json").data["label"] == "back"
    assert api.post(url("photo-set-main", ids[1])).data["is_main"]
    assert CardPhoto.objects.get(pk=ids[0]).is_main is False
    assert api.delete(url("photo-detail", ids[1])).status_code == 204
    assert CardPhoto.objects.get(pk=ids[0]).is_main  # the other one becomes the main photo


@pytest.mark.parametrize("name", ["photo-detail", "photo-file", "photo-thumbnail"])
def test_other_user_cannot_get_photo(name, other_api, user, make_card):
    from inventory import photos as svc

    photo = svc.add_photos(make_card(user), [upload(image_bytes())], PhotoLabel.FRONT)[0]
    assert other_api.get(url(name, photo.pk)).status_code == 404
    assert other_api.delete(url("photo-detail", photo.pk)).status_code == 404
    assert CardPhoto.objects.filter(pk=photo.pk).exists()


def test_cannot_upload_photo_to_other_users_card(other_api, user, make_card):
    card = make_card(user)
    resp = other_api.post(url("photo-list"), {"card": card.pk, "file": upload(image_bytes())}, format="multipart")
    assert resp.status_code == 400
    assert not CardPhoto.objects.exists()


# --- listings and sales --------------------------------------------------------

def test_generate_listing(api, user, make_card):
    card = make_card(user, variant="rookie", condition="Near Mint")
    resp = api.post(url("card-generate-listing", card.pk), {}, format="json")
    assert resp.data["title"] == "2023 Topps Chrome Erling Haaland #15 Rookie Near Mint"
    assert "There are no photos yet." in resp.data["warnings"]


def test_listing_cannot_be_marked_sold_via_api(api, user, make_card):
    card = make_card(user)
    resp = api.post(url("listing-list"), {"card": card.pk, "title": "x", "asking_price": "1", "status": "sold"},
                    format="json")
    assert resp.status_code == 400


def test_sale_create_uses_fee_profile(api, user, fee_profile, make_card):
    card = make_card(user, cost="3.00")
    resp = api.post(url("sale-list"), {"card": card.pk, "sale_price": "10.00", "shipping_income": "2.50",
                                       "shipping_cost": "1.95", "packaging_cost": "0.30", "sold_at": "2026-04-02"},
                    format="json")
    assert resp.status_code == 201, resp.data
    assert resp.data["ebay_commission"] == "2.01"
    assert resp.data["net_proceeds"] == "8.24"
    assert resp.data["profit"] == "5.24"
    card.refresh_from_db()
    assert card.status == CardStatus.SOLD
    # selling it again is not possible
    again = api.post(url("sale-list"), {"card": card.pk, "sale_price": "1", "sold_at": "2026-04-03"}, format="json")
    assert again.status_code == 400
    # a sold listing cannot be deleted
    assert api.delete(url("listing-detail", resp.data["listing"])).status_code == 400


def test_sale_without_fee_profile_is_400(api, user, make_card):
    resp = api.post(url("sale-list"), {"card": make_card(user).pk, "sale_price": "5", "sold_at": "2026-01-01"},
                    format="json")
    assert resp.status_code == 400 and "category" in resp.data


# --- calculator --------------------------------------------------------------

BASE = {"shipping_income": "2.50", "shipping_cost": "1.95", "packaging_cost": "0.30", "purchase_cost": "3.00"}


def test_calculator_forward_and_reverse(api, fee_profile):
    resp = api.post(url("calculator"), {**BASE, "fee_profile": fee_profile.pk, "sale_price": "10.00"}, format="json")
    assert resp.data["profit"] == "5.24" and resp.data["margin"] == "41.9" and resp.data["is_loss"] is False
    resp = api.post(url("calculator-reverse"), {**BASE, "fee_profile": fee_profile.pk, "target_profit": "5.24"},
                    format="json")
    assert resp.data["required_price"] == "9.99" and resp.data["profit"] == "5.24"


def test_calculator_rejects_floats_as_strings_and_negative(api, fee_profile):
    resp = api.post(url("calculator"), {"fee_profile": fee_profile.pk, "sale_price": "-1"}, format="json")
    assert resp.status_code == 400 and "sale_price" in resp.data


def test_calculator_cannot_use_other_users_profile(other_api, fee_profile):
    resp = other_api.post(url("calculator"), {"fee_profile": fee_profile.pk, "sale_price": "10"}, format="json")
    assert resp.status_code == 400 and "fee_profile" in resp.data


def test_fee_profiles_isolated(api, other_api, fee_profile):
    assert api.get(url("fee-profile-list")).data["count"] == 1
    assert other_api.get(url("fee-profile-list")).data["count"] == 0
    assert other_api.delete(url("fee-profile-detail", fee_profile.pk)).status_code == 404


def test_listing_template_validation(api):
    resp = api.post(url("listing-template-list"), {"name": "X", "title_pattern": "{playr}"}, format="json")
    assert resp.status_code == 400 and "title_pattern" in resp.data
    assert api.post(url("listing-template-list"), {"name": "X", "title_pattern": "{player}"},
                    format="json").status_code == 201
    assert api.post(url("listing-template-list"), {"name": "x", "title_pattern": "{player}"},
                    format="json").status_code == 400


# --- documentation -------------------------------------------------------------

def test_openapi_schema_and_docs(api, user, client_for):
    resp = api.get(url("schema"), {"format": "json"})
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    for p in ("/api/v1/cards/", "/api/v1/photos/{id}/file/", "/api/v1/sales/", "/api/v1/calculator/reverse/"):
        assert p in paths
    assert client_for(user).get(url("docs")).status_code == 200


def test_list_query_count_is_constant(api, user, make_card, django_assert_max_num_queries):
    for i in range(10):
        make_card(user, cost="1.00", player=f"P{i}")
    with django_assert_max_num_queries(6):
        assert api.get(url("card-list")).data["count"] == 10
