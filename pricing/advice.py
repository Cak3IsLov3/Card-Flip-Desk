"""Price advice: sold prices, your own sales history and active eBay listings.

Sold prices are what buyers really paid. They need no API: the app links to
eBay's own search with the "sold items" filter, and you paste the prices you
see. Active listings (Browse API) are **asking prices**, not sale prices:
whatever is priced too high just sits there, so they weigh the least.
Data from eBay is external input: amounts are read as Decimal, invalid rows
are skipped, and links only go to eBay.
"""

import re
import statistics
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from urllib.parse import urlencode, urlparse

from django.conf import settings

from ebay.client import EbayClient, EbayError, EbayNotConfigured, EbayRateLimited, EbayUnavailable
from finance.calculator import CENT, CostInput, calculate
from finance.models import DEFAULT_CATEGORY
from inventory.models import Card, Variant, normalise_variants
from sales.models import Sale
from sales.services import NoFeeProfile, fees_for

from .models import PriceSnapshot, PriceSource

MIN_OWN_SALES_FOR_ADVICE = 2
MIN_SOLD_PRICES_FOR_ADVICE = 2
MAX_SOLD_PRICES = 200
MAX_PRICE = Decimal("100000")

# Marketplace → eBay site, for the "sold items" link.
MARKETPLACE_SITES = {
    "EBAY_DE": "www.ebay.de", "EBAY_NL": "www.ebay.nl", "EBAY_BE": "www.benl.ebay.be",
    "EBAY_FR": "www.ebay.fr", "EBAY_IT": "www.ebay.it", "EBAY_ES": "www.ebay.es",
    "EBAY_AT": "www.ebay.at", "EBAY_GB": "www.ebay.co.uk", "EBAY_IE": "www.ebay.ie",
    "EBAY_US": "www.ebay.com",
}


@dataclass(frozen=True)
class PriceStats:
    count: int
    minimum: Decimal
    median: Decimal
    maximum: Decimal

    @classmethod
    def of(cls, prices) -> "PriceStats | None":
        prices = sorted(prices)
        if not prices:
            return None
        median = Decimal(statistics.median(prices)).quantize(CENT, rounding=ROUND_HALF_UP)
        return cls(len(prices), prices[0], median, prices[-1])


@dataclass
class ActiveItem:
    title: str
    price: Decimal
    url: str
    condition: str
    image: str


@dataclass
class ActiveListings:
    stats: PriceStats | None = None
    items: list[ActiveItem] = field(default_factory=list)
    total: int = 0
    excluded_currency: int = 0
    excluded_irrelevant: int = 0
    fetched_at: datetime | None = None
    from_cache: bool = False
    stale: bool = False
    error: str = ""
    not_configured: bool = False


@dataclass
class OwnHistory:
    stats: PriceStats | None
    sales: list


@dataclass
class SoldPrices:
    """Sold prices the user copied from eBay's "sold items" search."""

    stats: PriceStats | None = None
    prices: list[Decimal] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)


@dataclass
class Advice:
    card: Card
    query: str
    active: ActiveListings | None
    own: OwnHistory
    summary: list[str]
    suggested_price: Decimal | None
    basis: str
    preview: object = None  # CostResult at the suggested price
    sold: SoldPrices | None = None


def search_query(card: Card) -> str:
    parts = [str(card.year), card.set_name, card.player, card.card_number]
    labels = dict(Variant.choices)
    for variant in normalise_variants(card.variants):
        if variant == Variant.PARALLEL:
            # Search on the print run (/50), not the exact copy (23/50): eBay would find almost nothing.
            run = card.parallel_serial.partition("/")[2]
            parts += [card.parallel_name or labels[variant], f"/{run}" if run else ""]
        elif variant == Variant.INSERT:
            parts.append(card.insert_name or labels[variant])
        else:
            parts.append(labels[variant])
    return " ".join(p for p in parts if p).strip()


def sold_search_url(query: str) -> str:
    """eBay's own search for this card with the "sold items" filter, on the configured marketplace.

    Opened in the user's browser: the app itself never fetches eBay pages.
    """
    site = MARKETPLACE_SITES.get(settings.EBAY_MARKETPLACE_ID, "www.ebay.de")
    return f"https://{site}/sch/i.html?" + urlencode({"_nkw": query, "LH_Sold": "1", "LH_Complete": "1"})


_PRICE_TOKEN = re.compile(r"^\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?$|^\d+(?:[.,]\d{1,2})?$")


def _parse_price(token: str) -> Decimal | None:
    """One amount in German or English notation: 12,50 · 12.50 · 1.234,56 · 1,234.56 · 15."""
    if not _PRICE_TOKEN.match(token):
        return None
    last = max(token.rfind(","), token.rfind("."))
    # A separator followed by exactly 1 or 2 digits is the decimal point; others group thousands.
    if last != -1 and len(token) - last - 1 in (1, 2):
        whole, cents = token[:last], token[last + 1:]
    else:
        whole, cents = token, ""
    whole = whole.replace(",", "").replace(".", "")
    try:
        value = Decimal(f"{whole}.{cents or '0'}").quantize(CENT)
    except InvalidOperation:
        return None
    return value if 0 < value < MAX_PRICE else None


def parse_sold_prices(text: str) -> SoldPrices:
    """Prices pasted from eBay, separated by spaces, new lines or semicolons.

    Currency marks (€, EUR) are ignored; a comma followed by a space separates
    prices ("12,50, 14"), otherwise it is a decimal comma.
    """
    text = (text or "")[:5000]
    text = re.sub(r"(?i)eur|€", " ", text)
    text = re.sub(r",(\s)", r" \1", text)
    result = SoldPrices()
    for token in re.split(r"[\s;|]+", text):
        token = token.strip()
        if not token:
            continue
        value = _parse_price(token)
        if value is None:
            if len(result.ignored) < 10:
                result.ignored.append(token[:20])
            continue
        if len(result.prices) < MAX_SOLD_PRICES:
            result.prices.append(value)
    result.prices.sort()
    result.stats = PriceStats.of(result.prices)
    return result


def _fold(text: str) -> str:
    """Lower case without accents, for a rough title comparison."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def parse_items(data: dict, card: Card) -> ActiveListings:
    result = ActiveListings(total=int(data.get("total") or 0))
    surname = _fold(card.player.split()[-1]) if card.player.split() else ""
    for raw in data.get("itemSummaries") or []:
        price = raw.get("price") or {}
        if price.get("currency") != settings.EBAY_CURRENCY:
            result.excluded_currency += 1
            continue
        try:
            value = Decimal(str(price.get("value"))).quantize(CENT)
        except (InvalidOperation, TypeError):
            continue
        if value <= 0:
            continue
        title = str(raw.get("title") or "")[:200]
        # Search results are noisy (lots, other players); the surname must be in the title.
        if surname and surname not in _fold(title):
            result.excluded_irrelevant += 1
            continue
        result.items.append(
            ActiveItem(
                title=title,
                price=value,
                url=_safe_url(raw.get("itemWebUrl"), LINK_DOMAINS),
                condition=str(raw.get("condition") or ""),
                image=_safe_url((raw.get("image") or {}).get("imageUrl"), IMAGE_DOMAINS),
            )
        )
    result.items.sort(key=lambda i: i.price)
    result.stats = PriceStats.of(i.price for i in result.items)
    return result


LINK_DOMAINS = (
    "ebay.com", "ebay.nl", "ebay.be", "ebay.de", "ebay.fr",
    "ebay.it", "ebay.es", "ebay.co.uk", "ebay.at", "ebay.ie",
)
IMAGE_DOMAINS = ("ebayimg.com",)


def _safe_url(url, domains) -> str:
    """Only https links to (subdomains of) the given domains."""
    if not isinstance(url, str):
        return ""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not any(host == d or host.endswith("." + d) for d in domains):
        return ""
    return url


def fetch_active(card: Card, query: str, client: EbayClient | None = None) -> ActiveListings:
    client = client or EbayClient()
    if not client.configured:
        return ActiveListings(not_configured=True, error="eBay is not configured (no application keys).")
    try:
        result = client.search_items(query, limit=100, category_ids=settings.EBAY_CATEGORY_IDS)
    except EbayNotConfigured as exc:
        return ActiveListings(not_configured=True, error=str(exc))
    except EbayRateLimited as exc:
        return ActiveListings(error=f"{exc} Use your own history for now.")
    except EbayUnavailable as exc:
        return ActiveListings(
            error=f"eBay is unreachable right now ({exc}). Use your own history or enter a price manually."
        )
    except EbayError as exc:
        return ActiveListings(error=f"eBay returned an error: {exc}")
    active = parse_items(result.data, card)
    active.fetched_at, active.from_cache, active.stale = result.fetched_at, result.from_cache, result.stale
    return active


def own_history(card: Card) -> OwnHistory:
    sales = list(
        Sale.objects.owned_by(card.owner)
        .filter(listing__card__set_name__iexact=card.set_name, listing__card__player__iexact=card.player)
        .select_related("listing__card")
        .order_by("-sold_at")
    )
    return OwnHistory(PriceStats.of(s.sale_price for s in sales), sales)


def euro(value: Decimal) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}€{abs(value):,.2f}"


def build_advice(
    card: Card, *, query: str | None = None, fetch: bool, today, client=None, sold: SoldPrices | None = None
) -> Advice:
    query = (query or search_query(card)).strip()[:200]
    active = fetch_active(card, query, client) if fetch else None
    own = own_history(card)

    summary = []
    if sold and sold.stats:
        s = sold.stats
        summary.append(
            f"{s.count} sold price{'s' if s.count != 1 else ''} entered, median {euro(s.median)} "
            f"(lowest {euro(s.minimum)}, highest {euro(s.maximum)})."
        )
    if active and active.stats:
        s = active.stats
        summary.append(
            f"{s.count} active listing{'s' if s.count != 1 else ''}, median {euro(s.median)} "
            f"(lowest {euro(s.minimum)}, highest {euro(s.maximum)})."
        )
    elif active and not active.error:
        summary.append("No comparable active listings found.")
    if own.stats:
        summary.append(
            f"You sold {own.stats.count} yourself (same player and set), median {euro(own.stats.median)}."
        )

    # What buyers really paid comes first; asking prices come last.
    suggested, basis = None, ""
    if sold and sold.stats and sold.stats.count >= MIN_SOLD_PRICES_FOR_ADVICE:
        suggested, basis = sold.stats.median, "median of the sold prices you entered"
    elif own.stats and own.stats.count >= MIN_OWN_SALES_FOR_ADVICE:
        suggested, basis = own.stats.median, "median of your own sales"
    elif sold and sold.stats:
        suggested, basis = sold.stats.median, "the only sold price you entered"
    elif active and active.stats:
        suggested, basis = active.stats.median, "median of the active asking prices (not sale prices!)"
    elif own.stats:
        suggested, basis = own.stats.median, "your only previous sale"

    preview = None
    if suggested is not None:
        try:
            fees = fees_for(card.owner, DEFAULT_CATEGORY, today)
            preview = calculate(CostInput(sale_price=suggested, purchase_cost=card.total_cost), fees)
        except NoFeeProfile:
            pass

    if fetch and active and active.stats and not active.stale:
        PriceSnapshot.objects.create(
            card=card, source=PriceSource.EBAY_ACTIVE, price=active.stats.median,
            minimum=active.stats.minimum, maximum=active.stats.maximum,
            listing_count=active.stats.count, query=query,
        )
    if sold and sold.stats:
        PriceSnapshot.objects.create(
            card=card, source=PriceSource.MANUAL_SOLD, price=sold.stats.median,
            minimum=sold.stats.minimum, maximum=sold.stats.maximum,
            listing_count=sold.stats.count, query=query,
        )
    if (fetch or sold) and own.stats:
        PriceSnapshot.objects.create(
            card=card, source=PriceSource.OWN_HISTORY, price=own.stats.median,
            minimum=own.stats.minimum, maximum=own.stats.maximum, listing_count=own.stats.count,
        )
    return Advice(card, query, active, own, summary, suggested, basis, preview, sold)
