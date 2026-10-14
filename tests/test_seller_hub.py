"""Seller Hub import: reading the export, matching cards, importing once."""

from datetime import date
from decimal import Decimal as D

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from finance.models import ShippingMethod
from inventory.models import CardStatus
from sales import seller_hub as sh
from sales.models import Listing, ListingStatus, Sale
from sales.services import register_sale

HEADER = ("Verkaufsprotokollnummer;Bestellnummer;Käufername;Artikelnummer;Artikelbezeichnung;Bestandseinheit;"
          "Anzahl;Verkaufspreis;Verpackung und Versand;Verkauft am;Lieferadresse Land")
EXPORT = "\n".join([
    "Seller Hub – Bestellungen",
    "",
    HEADER,
    "1001;14-11111-22222;Käufer A;256447106225;2024 Topps Chrome Lamine Yamal #1 Rookie Gold Refractor 23/50;"
    ";1;EUR 24,99;1,95;14.10.2026;Deutschland",
    "1002;14-33333-44444;Käufer B;111;Wembanyama Prizm 2023 #136 Rookie Auto;CFD-{wemby};1;12,50 €;0,00;"
    "Okt 12, 2026;Niederlande",
    "1003;14-55555-66666;Käufer C;222;Max Verstappen 2024 Topps Chrome F1 #1;;1;8,00;1,95;10.10.2026;AT",
    "1004;14-77777-88888;Käufer D;;;;;;;;",  # total line of an order with several items
    "1004;14-77777-88888;Käufer D;333;Some other player 2020;;2;5,00;0;09.10.2026;Deutschland",
    "1005;14-99999-00000;Käufer E;444;Haaland Topps Chrome 2023 #15;;1;$9.00;0;09.10.2026;USA",
    "1006;14-12121-12121;Käufer F;555;Haaland Topps Chrome 2023 #15;;1;9,00;0;gestern;Deutschland",
    "5 Datensätze heruntergeladen",
])


@pytest.fixture
def cards(user, make_card):
    yamal = make_card(user, cost="13.00", player="Lamine Yamal", set_name="Topps Chrome", year=2024, card_number="1",
                      variants=["rookie", "parallel"], parallel_name="Gold Refractor", parallel_serial="23/50")
    wemby = make_card(user, cost="26.00", player="Victor Wembanyama", set_name="Panini Prizm", year=2023,
                      card_number="136")
    max_v = make_card(user, cost="4.00", player="Max Verstappen", set_name="Topps Chrome F1", year=2024,
                      card_number="1")
    Listing.objects.create(card=yamal, title="Yamal", asking_price=D("24.99"), ebay_item_id="256447106225",
                           status=ListingStatus.ACTIVE)
    return {"yamal": yamal, "wemby": wemby, "max": max_v}


def export_for(cards):
    return EXPORT.replace("{wemby}", str(cards["wemby"].pk))


def mapping():
    headers = sh.read_header(EXPORT)
    return sh.suggest_mapping(headers)


# --- reading -----------------------------------------------------------------

def test_header_is_found_after_the_preamble():
    assert sh.find_header(EXPORT) == (2, ";")
    assert sh.read_header(EXPORT)[:2] == ["Verkaufsprotokollnummer", "Bestellnummer"]


def test_suggested_mapping_prefers_the_order_number():
    assert mapping() == {
        "order_number": "Bestellnummer", "item_id": "Artikelnummer", "title": "Artikelbezeichnung",
        "custom_label": "Bestandseinheit", "quantity": "Anzahl", "sold_at": "Verkauft am",
        "sale_price": "Verkaufspreis", "shipping_income": "Verpackung und Versand",
        "buyer_country": "Lieferadresse Land",
    }


def test_parse_rows_reads_values_and_reports_problems():
    rows = {r.order_number: r for r in sh.parse_rows(EXPORT, mapping())}
    yamal = rows["14-11111-22222"]
    assert (yamal.line, yamal.item_id, yamal.sold_at) == (4, "256447106225", date(2026, 10, 14))
    assert (yamal.sale_price, yamal.shipping_income, yamal.buyer_country) == (D("24.99"), D("1.95"), "DE")
    assert yamal.ref == "14-11111-22222:256447106225"
    assert rows["14-33333-44444"].sold_at == date(2026, 10, 12)
    assert rows["14-33333-44444"].buyer_country == "NL"
    assert rows["14-55555-66666"].buyer_country == "AT"
    assert "one sale is one card" in rows["14-77777-88888"].errors[0]
    assert "not in euros" in rows["14-99999-00000"].errors[0]
    assert "Sale date not recognised" in rows["14-12121-12121"].errors[0]
    assert len(rows) == 6  # the order total line and the summary line are skipped


def test_missing_required_mapping_is_an_error():
    with pytest.raises(ValueError, match="Order number"):
        sh.parse_rows(EXPORT, {"title": "Artikelbezeichnung"})


@pytest.mark.parametrize(
    "text, expected",
    [
        ("14.10.2026", date(2026, 10, 14)),
        ("14.10.26 18:03", date(2026, 10, 14)),
        ("2026-10-14T18:03:11Z", date(2026, 10, 14)),
        ("Okt 14, 2026", date(2026, 10, 14)),
        ("14. Okt. 2026", date(2026, 10, 14)),
        ("3. März 2026", date(2026, 3, 3)),
        ("Mai 2, 2026", date(2026, 5, 2)),
        ("Oct-14-26", date(2026, 10, 14)),
        ("14/10/2026", date(2026, 10, 14)),
        ("gestern", None),
        ("", None),
    ],
)
def test_parse_date(text, expected):
    assert sh.parse_date(text) == expected


@pytest.mark.parametrize("text, code", [("Deutschland", "DE"), ("germany", "DE"), ("nl", "NL"),
                                        ("Österreich", "AT"), ("Atlantis", "")])
def test_parse_country(text, code):
    assert sh.parse_country(text) == code


# --- matching ----------------------------------------------------------------

def test_suggestions_by_item_number_sku_and_title(user, other_user, make_card, cards):
    make_card(other_user, player="Max Verstappen", set_name="Topps Chrome F1", year=2024, card_number="1")
    rows = sh.parse_rows(export_for(cards), mapping())
    found = sh.suggest_cards(rows, sh.open_cards(user))
    by_order = {r.order_number: found.get(r.line) for r in rows}
    assert (by_order["14-11111-22222"].card, by_order["14-11111-22222"].reason) == (cards["yamal"], "eBay item number")
    assert (by_order["14-33333-44444"].card, by_order["14-33333-44444"].reason) == (cards["wemby"], "custom label")
    assert (by_order["14-55555-66666"].card, by_order["14-55555-66666"].reason) == (cards["max"], "title")
    assert by_order["14-77777-88888"] is None  # rows with problems get no suggestion


def test_a_card_is_suggested_once(user, make_card):
    card = make_card(user, player="Erling Haaland", set_name="Topps Chrome", year=2023, card_number="15")
    content = "\n".join([HEADER, "1;A;x;1;Haaland Topps Chrome 2023 #15;;1;9;0;01.10.2026;DE",
                         "2;B;x;2;Haaland Topps Chrome 2023 #15;;1;9;0;01.10.2026;DE"])
    rows = sh.parse_rows(content, mapping())
    assert [s.card for s in sh.suggest_cards(rows, [card]).values()] == [card]


def test_sku_for_card(user, make_card, client_for):
    card = make_card(user)
    assert sh.sku_for(card) == f"CFD-{card.pk}"
    html = client_for(user).get(reverse("sales:listing_generator", args=[card.pk])).content.decode()
    assert f"<code>CFD-{card.pk}</code>" in html


# --- the whole flow ----------------------------------------------------------

def upload(client, content):
    return client.post(reverse("sales:seller_hub_upload"),
                       {"file": SimpleUploadedFile("orders.csv", content.encode("cp1252"), "text/csv")})


def test_upload_map_review_and_import(user, fee_profile, cards, client_for):
    client = client_for(user)
    kompakt = ShippingMethod.objects.create(user=user, name="Kompaktbrief", cost=D("1.10"))
    assert upload(client, export_for(cards)).url == reverse("sales:seller_hub_map")
    page = client.get(reverse("sales:seller_hub_map")).content.decode()
    assert '<option value="Bestellnummer" selected>' in page
    assert client.post(reverse("sales:seller_hub_map"), mapping()).url == reverse("sales:seller_hub_review")

    review = client.get(reverse("sales:seller_hub_review")).content.decode()
    assert f'<option value="{cards["yamal"].pk}" selected>' in review
    assert "Suggested by eBay item number" in review
    assert "not in euros" in review

    rows = sh.parse_rows(export_for(cards), mapping())
    line = {r.order_number: r.line for r in rows}
    resp = client.post(reverse("sales:seller_hub_review"), {
        f"card_{line['14-11111-22222']}": cards["yamal"].pk,
        f"card_{line['14-33333-44444']}": cards["wemby"].pk,
        f"card_{line['14-55555-66666']}": "",  # do not import
        "shipping_method": kompakt.pk, "shipping_cost": "0", "packaging_cost": "0.25",
    })
    assert resp.status_code == 200
    assert len(resp.context["report"].created) == 2

    sale = Sale.objects.get(listing__card=cards["yamal"])
    assert (sale.sale_price, sale.shipping_income, sale.shipping_cost, sale.packaging_cost) == (
        D("24.99"), D("1.95"), D("1.10"), D("0.25"))
    assert (sale.sold_at, sale.buyer_country, sale.ebay_order_ref) == (
        date(2026, 10, 14), "DE", "14-11111-22222:256447106225")
    assert sale.ebay_commission == D("3.92")  # the 13.25% + 0.35 test profile, on price + shipping
    cards["wemby"].refresh_from_db()
    assert cards["wemby"].status == CardStatus.SOLD
    assert Sale.objects.get(listing__card=cards["wemby"]).listing.ebay_item_id == "111"
    assert not Sale.objects.filter(listing__card=cards["max"]).exists()
    assert "seller_hub_content" not in client.session


def test_importing_the_same_file_again_skips_known_order_lines(user, fee_profile, cards, client_for):
    client = client_for(user)
    sale = register_sale(cards["yamal"], sale_price=D("24.99"), sold_at=date(2026, 10, 14))
    sale.ebay_order_ref = "14-11111-22222:256447106225"
    sale.save()
    upload(client, export_for(cards))
    client.post(reverse("sales:seller_hub_map"), mapping())
    review = client.get(reverse("sales:seller_hub_review")).content.decode()
    assert "Imported before" in review
    rows = sh.parse_rows(export_for(cards), mapping())
    yamal_line = next(r.line for r in rows if r.order_number == "14-11111-22222")
    # Even a forged choice for a known order line is refused.
    resp = client.post(reverse("sales:seller_hub_review"), {f"card_{yamal_line}": cards["max"].pk})
    assert resp.context["report"].created == []
    assert Sale.objects.count() == 1


def test_other_users_card_cannot_be_chosen(user, other_user, fee_profile, make_card, cards, client_for):
    theirs = make_card(other_user, player="Lamine Yamal", set_name="Topps Chrome", year=2024)
    client = client_for(user)
    upload(client, export_for(cards))
    client.post(reverse("sales:seller_hub_map"), mapping())
    rows = sh.parse_rows(export_for(cards), mapping())
    resp = client.post(reverse("sales:seller_hub_review"), {f"card_{rows[0].line}": theirs.pk})
    assert resp.context["report"].created == []
    assert not Sale.objects.exists()
    theirs.refresh_from_db()
    assert theirs.status != CardStatus.SOLD


def test_review_lists_only_own_unsold_cards(user, other_user, make_card, cards, client_for):
    make_card(other_user, player="Hidden Person", set_name="Secret Set", year=2020)
    client = client_for(user)
    upload(client, export_for(cards))
    client.post(reverse("sales:seller_hub_map"), mapping())
    html = client.get(reverse("sales:seller_hub_review")).content.decode()
    assert "Hidden Person" not in html


def test_steps_without_an_upload_go_back_to_the_start(user, client_for):
    client = client_for(user)
    for name in ("sales:seller_hub_map", "sales:seller_hub_review"):
        assert client.get(reverse(name)).url == reverse("sales:seller_hub_upload")


def test_upload_rejects_unreadable_files(user, client_for):
    resp = client_for(user).post(reverse("sales:seller_hub_upload"),
                                 {"file": SimpleUploadedFile("x.csv", b"\xff\xfe\x00\x81\x8d", "text/csv")})
    assert resp.status_code == 200
    assert "seller_hub_content" not in resp.wsgi_request.session
