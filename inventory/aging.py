"""Inventory age and suggested actions.

Every function takes `today` as an argument, so the boundaries (exactly on
the threshold, a day before, a day after) can be tested without touching the
clock. A card is **on** the threshold when it is exactly that many days old,
and it already counts at that point.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Prefetch

from finance.calculator import ZERO, CostInput, CostResult, calculate, money

from .models import Card, CardStatus, StaleThreshold

WARNING, ACTION, CRITICAL = "warning", "action", "critical"
LEVEL_LABELS = {WARNING: "Warning", ACTION: "Action", CRITICAL: "Critical"}


def _pct(value: Decimal) -> str:
    """10.0 -> '10%', 12.5 -> '12.5%'."""
    return f"{value.normalize():f}%"


def level_for(age_days: int | None, t: StaleThreshold) -> str | None:
    if age_days is None:
        return None
    if age_days >= t.critical_days:
        return CRITICAL
    if age_days >= t.action_days:
        return ACTION
    if age_days >= t.warning_days:
        return WARNING
    return None


def age_in_days(age_start: date | None, today: date) -> int | None:
    return (today - age_start).days if age_start else None


@dataclass
class PriceSuggestion:
    current_price: Decimal
    new_price: Decimal
    percentage: Decimal
    current: CostResult | None
    new: CostResult | None

    @property
    def is_loss(self) -> bool:
        return self.new is not None and self.new.is_loss


@dataclass
class StaleItem:
    card: Card
    age_days: int
    level: str
    cost: Decimal
    advice: str
    price: PriceSuggestion | None = None
    bundle_with: int = 0  # number of other unsold cards from the same set

    @property
    def level_label(self) -> str:
        return LEVEL_LABELS[self.level]


def suggest_price(asking_price, cost, percentage, fees) -> PriceSuggestion | None:
    if not asking_price:
        return None
    new_price = money(Decimal(asking_price) * (1 - Decimal(percentage) / 100))
    current = new = None
    if fees is not None:
        current = calculate(CostInput(sale_price=asking_price, purchase_cost=cost), fees)
        new = calculate(CostInput(sale_price=new_price, purchase_cost=cost), fees)
    return PriceSuggestion(asking_price, new_price, Decimal(percentage), current, new)


def stale_queryset(user, today: date, thresholds: StaleThreshold):
    """Unsold, unpinned cards that have reached at least the first threshold."""
    from sales.models import Listing, ListingStatus

    cutoff = today - timedelta(days=thresholds.warning_days)
    open_listings = Listing.objects.filter(
        status__in=[ListingStatus.ACTIVE, ListingStatus.DRAFT]
    ).order_by("-id")
    return (
        Card.objects.owned_by(user)
        .exclude(status=CardStatus.SOLD)
        .not_pinned(today)
        .with_age_start()
        .filter(age_start__lte=cutoff)
        .with_cost()
        .prefetch_related(Prefetch("listings", open_listings, to_attr="open_listings"))
        .order_by("age_start", "id")
    )


def stale_items(user, today: date, thresholds: StaleThreshold | None = None) -> list[StaleItem]:
    from finance.models import DEFAULT_CATEGORY
    from sales.services import NoFeeProfile, fees_for

    thresholds = thresholds or StaleThreshold.for_user(user)
    cards = list(stale_queryset(user, today, thresholds))
    if not cards:
        return []

    try:
        fees = fees_for(user, DEFAULT_CATEGORY, today)
    except NoFeeProfile:
        fees = None

    unsold_per_set = Counter(
        Card.objects.owned_by(user)
        .exclude(status=CardStatus.SOLD)
        .values_list("set_name", "year")
    )

    items = []
    for card in cards:
        age = age_in_days(card.age_start, today)
        level = level_for(age, thresholds)
        listing = card.open_listings[0] if card.open_listings else None
        item = StaleItem(card=card, age_days=age, level=level, cost=card.cost_total, advice="")
        if level == WARNING:
            item.advice = "Improve the photos or the title."
        elif level == ACTION:
            item.price = suggest_price(
                listing.asking_price if listing else None,
                card.cost_total,
                thresholds.price_drop_percentage,
                fees,
            )
            item.advice = (
                f"Lower the price by {_pct(thresholds.price_drop_percentage)}."
                if item.price
                else "List the card for sale with an asking price."
            )
        else:
            item.bundle_with = unsold_per_set[(card.set_name, card.year)] - 1
            others = "card" if item.bundle_with == 1 else "cards"
            item.advice = (
                f"Bundle with {item.bundle_with} other {others} from {card.set_name} {card.year}."
                if item.bundle_with
                else "Write it off or offer it as a bargain."
            )
        items.append(item)
    return items


@dataclass
class AttentionSummary:
    items: list[StaleItem]

    @property
    def total(self) -> Decimal:
        return sum((i.cost for i in self.items), ZERO)

    @property
    def counts(self) -> dict[str, int]:
        c = Counter(i.level for i in self.items)
        return {lvl: c.get(lvl, 0) for lvl in (WARNING, ACTION, CRITICAL)}

    @property
    def losses(self) -> list[StaleItem]:
        return [i for i in self.items if i.price and i.price.is_loss]


def attention(user, today: date) -> AttentionSummary:
    return AttentionSummary(stale_items(user, today))
