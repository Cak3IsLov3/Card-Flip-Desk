"""Import of sales from an eBay Seller Hub orders export (CSV).

The export differs per eBay site and report, so nothing is hard-coded: the
header row is found by known column names (German and English), the user
confirms the column mapping, and then confirms which card each sale belongs
to. Every row is external input: amounts, dates and countries are parsed
strictly, rows that cannot be read end up in the report, and an order line
that was imported before is never imported twice.
"""

import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from django.db import transaction

from finance.amounts import FOREIGN_CURRENCY, parse_amount
from finance.models import DEFAULT_CATEGORY
from inventory.models import Card, CardStatus

from .models import Listing, Sale
from .services import NoFeeProfile, register_sale

MAX_ROWS = 500
ZERO = Decimal("0.00")

IMPORT_FIELDS = {
    "order_number": "Order number",
    "item_id": "Item number",
    "title": "Item title",
    "custom_label": "Custom label (SKU)",
    "quantity": "Quantity",
    "sold_at": "Sale date",
    "sale_price": "Sold for (item price)",
    "shipping_income": "Shipping charged",
    "buyer_country": "Buyer country",
}
REQUIRED_FIELDS = {"order_number", "title", "sold_at", "sale_price"}

# Known column names, most specific first (compared case-insensitively).
HEADER_ALIASES = {
    "order_number": ["bestellnummer", "order number", "order no.", "auftragsnummer",
                     "verkaufsprotokollnummer", "sales record number"],
    "item_id": ["artikelnummer", "item number", "item id", "artikel-nr."],
    "title": ["artikelbezeichnung", "item title", "angebotstitel", "titel", "title"],
    "custom_label": ["custom label (sku)", "custom label", "bestandseinheit (sku)", "bestandseinheit", "sku"],
    "quantity": ["anzahl", "menge", "stückzahl", "quantity"],
    "sold_at": ["verkauft am", "verkaufsdatum", "bestelldatum", "sale date", "sold date", "order date",
                "datum"],
    "sale_price": ["verkaufspreis", "artikelpreis", "sold for", "item price", "sold price", "preis", "price"],
    "shipping_income": ["verpackung und versand", "versand und verpackung", "shipping and handling",
                        "versandkosten", "shipping", "versand"],
    "buyer_country": ["käuferland", "land des käufers", "lieferadresse land", "lieferland", "buyer country",
                      "ship to country", "land", "country"],
}

COUNTRIES = {
    "deutschland": "DE", "germany": "DE", "niederlande": "NL", "netherlands": "NL", "nederland": "NL",
    "österreich": "AT", "austria": "AT", "belgien": "BE", "belgium": "BE", "belgië": "BE",
    "frankreich": "FR", "france": "FR", "italien": "IT", "italy": "IT", "spanien": "ES", "spain": "ES",
    "schweiz": "CH", "switzerland": "CH", "polen": "PL", "poland": "PL", "luxemburg": "LU",
    "luxembourg": "LU", "dänemark": "DK", "denmark": "DK", "schweden": "SE", "sweden": "SE",
    "tschechien": "CZ", "czech republic": "CZ", "czechia": "CZ", "portugal": "PT", "irland": "IE",
    "ireland": "IE", "vereinigtes königreich": "GB", "großbritannien": "GB", "united kingdom": "GB",
    "vereinigte staaten": "US", "usa": "US", "united states": "US",
}

GERMAN_MONTHS = {
    "jan": "Jan", "januar": "Jan", "feb": "Feb", "februar": "Feb", "mär": "Mar", "mrz": "Mar", "märz": "Mar",
    "apr": "Apr", "april": "Apr", "mai": "May", "jun": "Jun", "juni": "Jun", "jul": "Jul", "juli": "Jul",
    "aug": "Aug", "august": "Aug", "sep": "Sep", "sept": "Sep", "september": "Sep", "okt": "Oct",
    "oktober": "Oct", "nov": "Nov", "november": "Nov", "dez": "Dec", "dezember": "Dec",
}
DATE_FORMATS = [
    "%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y",
    "%b-%d-%y", "%b-%d-%Y", "%b %d, %Y", "%b %d %Y", "%d %b %Y", "%d-%b-%y", "%d-%b-%Y",
]


# --- reading the file --------------------------------------------------------

def _normal(header: str) -> str:
    return " ".join((header or "").replace("﻿", "").strip().lower().split())


def _known(header: str) -> bool:
    key = _normal(header)
    return any(key in aliases for aliases in HEADER_ALIASES.values())


def find_header(content: str) -> tuple[int, str]:
    """Index of the header line and its delimiter.

    Seller Hub exports can start with a few lines of text before the header.
    The header is the first of the first 15 lines with at least two known
    column names; failing that, the first line.
    """
    lines = content.splitlines()
    for index, line in enumerate(lines[:15]):
        delimiter = max(";,\t", key=line.count)
        cells = next(csv.reader([line], delimiter=delimiter), [])
        if sum(_known(c) for c in cells) >= 2:
            return index, delimiter
    first = lines[0] if lines else ""
    return 0, max(";,\t", key=first.count) if first else ","


def _table(content: str) -> tuple[list[str], csv.DictReader, int]:
    index, delimiter = find_header(content)
    text = "\n".join(content.splitlines()[index:])
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    headers = [h for h in (reader.fieldnames or []) if h is not None]
    return headers, reader, index


def read_header(content: str) -> list[str]:
    return _table(content)[0]


def suggest_mapping(headers: list[str]) -> dict[str, str]:
    """Import field -> column, choosing the most specific known name per field."""
    by_key = {}
    for header in headers:
        by_key.setdefault(_normal(header), header)
    mapping, used = {}, set()
    for target, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            header = by_key.get(alias)
            if header and header not in used:
                mapping[target] = header
                used.add(header)
                break
    return mapping


def parse_date(text: str) -> date | None:
    text = (text or "").strip()
    # Drop a time and time zone: "14.10.2026 18:03:11 MESZ", "2026-10-14T18:03:11Z".
    text = re.sub(r"[T\s]+\d{1,2}:\d{2}.*$", "", text)
    text = re.sub(
        r"(?i)\b([a-zä]{3,9})\.?(?=[\s\-,\d]|$)",
        lambda m: GERMAN_MONTHS.get(m.group(1).lower(), m.group(1)),
        text,
    ).replace(". ", " ").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_country(text: str) -> str:
    key = _normal(text)
    if len(key) == 2 and key.isalpha():
        return key.upper()
    return COUNTRIES.get(key, "")


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


@dataclass
class SellerHubRow:
    line: int
    order_number: str = ""
    item_id: str = ""
    title: str = ""
    custom_label: str = ""
    quantity: int = 1
    sold_at: date | None = None
    sale_price: Decimal | None = None
    shipping_income: Decimal = ZERO
    buyer_country: str = ""
    errors: list[str] = field(default_factory=list)
    already_imported: bool = False

    @property
    def ref(self) -> str:
        """Identifies one order line: an order can hold several cards."""
        return f"{self.order_number}:{self.item_id or _fold(self.title)[:60]}"[:120]

    @property
    def importable(self) -> bool:
        return not self.errors and not self.already_imported


def _money(raw: str, label: str, row: SellerHubRow, required: bool) -> Decimal | None:
    raw = (raw or "").strip()
    if not raw:
        if required:
            row.errors.append(f"{label} is empty.")
        return None if required else ZERO
    if FOREIGN_CURRENCY.search(raw):
        row.errors.append(f"{label} is not in euros ({raw[:20]}).")
        return None
    value = parse_amount(raw)
    if value is None:
        row.errors.append(f"{label} is not an amount ({raw[:20]}).")
    return value


def parse_rows(content: str, mapping: dict[str, str]) -> list[SellerHubRow]:
    """Order lines from the export. Summary and order-total lines are skipped."""
    missing = REQUIRED_FIELDS - {k for k, v in mapping.items() if v}
    if missing:
        labels = ", ".join(IMPORT_FIELDS[m] for m in sorted(missing))
        raise ValueError(f"Required fields not mapped: {labels}.")

    _, reader, offset = _table(content)
    rows = []
    for raw in reader:
        def cell(name, raw=raw):
            column = mapping.get(name)
            return str(raw.get(column) or "").strip() if column else ""

        # No order number or no title: a summary line ("12 records downloaded")
        # or the total line of an order with several items.
        if not cell("order_number") or not cell("title"):
            continue
        row = SellerHubRow(
            line=reader.line_num + offset,
            order_number=cell("order_number")[:60],
            item_id=re.sub(r"\D", "", cell("item_id"))[:40],
            title=cell("title")[:200],
            custom_label=cell("custom_label")[:60],
        )
        quantity = cell("quantity") or "1"
        if not quantity.isdigit() or int(quantity) < 1:
            row.errors.append(f"Quantity is not a number ({quantity[:10]}).")
        elif int(quantity) > 1:
            row.quantity = int(quantity)
            row.errors.append(f"Quantity {quantity}: one sale is one card, so record these by hand.")
        row.sold_at = parse_date(cell("sold_at"))
        if row.sold_at is None:
            row.errors.append(f"Sale date not recognised ({cell('sold_at')[:30]}).")
        row.sale_price = _money(cell("sale_price"), "Sale price", row, required=True)
        if row.sale_price is not None and row.sale_price <= 0:
            row.errors.append("Sale price must be more than 0.")
        row.shipping_income = _money(cell("shipping_income"), "Shipping", row, required=False) or ZERO
        row.buyer_country = parse_country(cell("buyer_country"))
        rows.append(row)
        if len(rows) >= MAX_ROWS:
            break
    return rows


# --- matching rows to cards --------------------------------------------------

SKU_RE = re.compile(r"(?i)^(?:cfd-?)?(\d{1,9})$")


def sku_for(card: Card) -> str:
    """The custom label (SKU) to put on the eBay listing, so imports find the card."""
    return f"CFD-{card.pk}"


def _keys(card: Card) -> set[str]:
    text = " ".join([card.player, card.set_name, str(card.year), card.card_number, card.parallel_name,
                     card.insert_name])
    return {t for t in re.split(r"[^0-9a-z]+", _fold(text)) if t}


@dataclass
class Suggestion:
    card: Card
    reason: str


def mark_imported(rows: list[SellerHubRow], owner) -> None:
    refs = set(
        Sale.objects.filter(listing__card__owner=owner, ebay_order_ref__in=[r.ref for r in rows])
        .values_list("ebay_order_ref", flat=True)
    )
    for row in rows:
        row.already_imported = row.ref in refs


def suggest_cards(rows: list[SellerHubRow], cards: list[Card]) -> dict[int, Suggestion]:
    """Line number -> suggested card, by eBay item number, custom label, then title.

    A card is suggested for at most one row.
    """
    by_pk = {c.pk: c for c in cards}
    by_item = {
        listing.ebay_item_id: by_pk[listing.card_id]
        for listing in Listing.objects.filter(card__in=cards).exclude(ebay_item_id="")
    }
    taken, result = set(), {}

    def take(row, card, reason):
        if card is not None and card.pk not in taken:
            taken.add(card.pk)
            result[row.line] = Suggestion(card, reason)
            return True
        return False

    open_rows = [r for r in rows if r.importable]
    for row in list(open_rows):
        match = SKU_RE.match(row.custom_label)
        if take(row, by_item.get(row.item_id), "eBay item number") or (
            match and take(row, by_pk.get(int(match.group(1))), "custom label")
        ):
            open_rows.remove(row)

    candidates = []
    for row in open_rows:
        words = {t for t in re.split(r"[^0-9a-z]+", _fold(row.title)) if t}
        for card in cards:
            surname = _fold(card.player.split()[-1]) if card.player.split() else ""
            if card.pk in taken or not surname or surname not in words:
                continue
            keys = _keys(card)
            score = len(keys & words) / len(keys)
            if score >= 0.5:
                candidates.append((score, row.line, card))
    rows_by_line = {r.line: r for r in open_rows}
    for _score, line, card in sorted(candidates, key=lambda c: (-c[0], c[1])):
        if line not in result:
            take(rows_by_line[line], card, "title")
    return result


def open_cards(owner) -> list[Card]:
    return list(Card.objects.owned_by(owner).exclude(status=CardStatus.SOLD).order_by("player", "year"))


# --- importing ---------------------------------------------------------------

@dataclass
class SaleImportReport:
    created: list[Sale] = field(default_factory=list)
    skipped: int = 0
    errors: list[tuple[int, str]] = field(default_factory=list)


def import_sales(rows, choices: dict[int, Card], owner, *, shipping_cost=ZERO, packaging_cost=ZERO):
    """Record a sale for each row with a chosen card. Each row stands on its own."""
    report = SaleImportReport()
    mark_imported(rows, owner)
    used = set()
    for row in rows:
        card = choices.get(row.line)
        if card is None:
            report.skipped += 1
            continue
        if row.already_imported:
            report.errors.append((row.line, "This order line was imported before."))
            continue
        if row.errors:
            report.errors.append((row.line, " ".join(row.errors)))
            continue
        if card.owner_id != owner.pk or card.status == CardStatus.SOLD or card.pk in used:
            report.errors.append((row.line, f"{card} is already sold or chosen for another row."))
            continue
        try:
            with transaction.atomic():
                sale = register_sale(
                    card, sale_price=row.sale_price, sold_at=row.sold_at, shipping_income=row.shipping_income,
                    shipping_cost=shipping_cost, packaging_cost=packaging_cost, buyer_country=row.buyer_country,
                    category=DEFAULT_CATEGORY, title=row.title,
                )
                sale.ebay_order_ref = row.ref
                sale.save(update_fields=["ebay_order_ref"])
                if row.item_id and not sale.listing.ebay_item_id:
                    sale.listing.ebay_item_id = row.item_id
                    sale.listing.save(update_fields=["ebay_item_id"])
        except NoFeeProfile as exc:
            report.errors.append((row.line, str(exc)))
            continue
        used.add(card.pk)
        report.created.append(sale)
    return report
