"""Prijsadvies: actieve eBay-listings naast je eigen verkoophistorie.

Actieve listings zijn **vraagprijzen**, geen verkoopprijzen: wat te duur
staat, blijft staan. Daarom weegt de eigen historie zwaarder zodra er
genoeg is. Gegevens van eBay zijn externe invoer: bedragen worden als
Decimal gelezen en ongeldige regels overgeslagen, links alleen naar eBay.
"""

import statistics
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from urllib.parse import urlparse

from django.conf import settings

from ebay.client import EbayClient, EbayError, EbayNotConfigured, EbayRateLimited, EbayUnavailable
from finance.calculator import CENT, CostInput, calculate
from inventory.models import Card, Variant
from sales.models import Sale
from sales.services import NoFeeProfile, fees_for

from .models import PriceSnapshot, PriceSource

MIN_OWN_SALES_FOR_ADVICE = 2


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
class Advice:
    card: Card
    query: str
    active: ActiveListings | None
    own: OwnHistory
    summary: list[str]
    suggested_price: Decimal | None
    basis: str
    preview: object = None  # CostResult bij de richtprijs


def search_query(card: Card) -> str:
    parts = [str(card.year), card.set_name, card.player, card.card_number]
    if card.variant != Variant.BASE:
        parts.append(card.get_variant_display())
    return " ".join(p for p in parts if p).strip()


def _fold(text: str) -> str:
    """Kleine letters zonder accenten, voor een ruwe titelvergelijking."""
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
        # Zoekresultaten bevatten ruis (lots, andere spelers); de achternaam moet in de titel staan.
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


LINK_DOMAINS = ("ebay.com", "ebay.nl", "ebay.be", "ebay.de", "ebay.fr", "ebay.it", "ebay.es", "ebay.co.uk", "ebay.at", "ebay.ie")
IMAGE_DOMAINS = ("ebayimg.com",)


def _safe_url(url, domains) -> str:
    """Alleen https-links naar (subdomeinen van) de opgegeven domeinen."""
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
        return ActiveListings(not_configured=True, error="eBay is niet gekoppeld (geen applicatiesleutels).")
    try:
        result = client.search_items(query, limit=100, category_ids=settings.EBAY_CATEGORY_IDS)
    except EbayNotConfigured as exc:
        return ActiveListings(not_configured=True, error=str(exc))
    except EbayRateLimited as exc:
        return ActiveListings(error=f"{exc} Gebruik voorlopig je eigen historie.")
    except EbayUnavailable as exc:
        return ActiveListings(error=f"eBay is nu niet bereikbaar ({exc}). Gebruik je eigen historie of vul handmatig een prijs in.")
    except EbayError as exc:
        return ActiveListings(error=f"eBay gaf een fout: {exc}")
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
    whole, cents = f"{value:.2f}".split(".")
    return f"€ {int(whole):,}".replace(",", ".") + f",{cents}"


def build_advice(card: Card, *, query: str | None = None, fetch: bool, today, client=None) -> Advice:
    query = (query or search_query(card)).strip()[:200]
    active = fetch_active(card, query, client) if fetch else None
    own = own_history(card)

    summary = []
    if active and active.stats:
        s = active.stats
        summary.append(
            f"{s.count} actieve listing{'s' if s.count != 1 else ''}, mediaan {euro(s.median)} "
            f"(laagste {euro(s.minimum)}, hoogste {euro(s.maximum)})."
        )
    elif active and not active.error:
        summary.append("Geen vergelijkbare actieve listings gevonden.")
    if own.stats:
        summary.append(
            f"Zelf {own.stats.count}× verkocht (zelfde speler en set), mediaan {euro(own.stats.median)}."
        )

    suggested, basis = None, ""
    if own.stats and own.stats.count >= MIN_OWN_SALES_FOR_ADVICE:
        suggested, basis = own.stats.median, "mediaan van je eigen verkopen"
    elif active and active.stats:
        suggested, basis = active.stats.median, "mediaan van de actieve vraagprijzen (geen verkoopprijzen!)"
    elif own.stats:
        suggested, basis = own.stats.median, "je enige eerdere verkoop"

    preview = None
    if suggested is not None:
        try:
            fees = fees_for(card.owner, "Sportkaarten", today)
            preview = calculate(CostInput(sale_price=suggested, purchase_cost=card.total_cost), fees)
        except NoFeeProfile:
            pass

    if fetch and active and active.stats and not active.stale:
        PriceSnapshot.objects.create(
            card=card, source=PriceSource.EBAY_ACTIVE, price=active.stats.median,
            minimum=active.stats.minimum, maximum=active.stats.maximum,
            listing_count=active.stats.count, query=query,
        )
    if fetch and own.stats:
        PriceSnapshot.objects.create(
            card=card, source=PriceSource.OWN_HISTORY, price=own.stats.median,
            minimum=own.stats.minimum, maximum=own.stats.maximum, listing_count=own.stats.count,
        )
    return Advice(card, query, active, own, summary, suggested, basis, preview)
