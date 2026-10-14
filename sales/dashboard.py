"""Cijfers voor het dashboard.

De query's zelf staan in de querysets; dit bestand voegt ze samen en doet
de afgeleide berekeningen (marge, ontbrekende maanden, leeftijd). `today`
wordt altijd meegegeven, zodat tests geen klok hoeven te manipuleren.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from finance.calculator import ZERO
from inventory import aging
from inventory.models import Card

from .models import Sale

PERIODS = {
    "30": ("30 dagen", 30),
    "90": ("90 dagen", 90),
    "365": ("12 maanden", 365),
    "all": ("Alles", None),
}
DEFAULT_PERIOD = "365"
MONTHS_IN_CHART = 12
TENTH = Decimal("0.1")


def margin(profit, revenue):
    """Marge = winst / omzet × 100 (gewogen), of None bij geen omzet."""
    if not revenue:
        return None
    return (Decimal(profit) / Decimal(revenue) * 100).quantize(TENTH, rounding=ROUND_HALF_UP)


@dataclass
class Dashboard:
    period: str
    start: date | None
    today: date
    sales_count: int
    revenue: Decimal
    profit: Decimal
    margin: Decimal | None
    stock_value: Decimal
    stock_count: int
    months: list[dict] = field(default_factory=list)
    sets: list[dict] = field(default_factory=list)
    best_cards: list = field(default_factory=list)
    worst_cards: list = field(default_factory=list)
    fastest: list = field(default_factory=list)
    slowest: list = field(default_factory=list)
    oldest_stock: list = field(default_factory=list)
    attention: aging.AttentionSummary | None = None


def build_dashboard(user, *, today: date, period: str = DEFAULT_PERIOD, limit: int = 5) -> Dashboard:
    if period not in PERIODS:
        period = DEFAULT_PERIOD
    days = PERIODS[period][1]
    start = today - timedelta(days=days - 1) if days else None

    sales = Sale.objects.owned_by(user).in_period(start, today)
    totals = sales.totals()

    by_card = sales.with_profit().select_related("listing__card")
    timed = (
        sales.with_days_to_sale()
        .filter(days_to_sale__isnull=False)
        .select_related("listing__card")
    )

    unsold = Card.objects.owned_by(user).unsold_by_age()
    stock = list(unsold)

    return Dashboard(
        period=period,
        start=start,
        today=today,
        sales_count=totals["count"],
        revenue=totals["revenue"],
        profit=totals["profit_total"],
        margin=margin(totals["profit_total"], totals["revenue"]),
        stock_value=sum((c.cost_total for c in stock), ZERO),
        stock_count=len(stock),
        months=_months(sales, today, start),
        sets=[
            {
                "set_name": row["listing__card__set_name"],
                "year": row["listing__card__year"],
                "count": row["count"],
                "revenue": row["revenue"],
                "profit": row["profit_total"],
                "margin": margin(row["profit_total"], row["revenue"]),
            }
            for row in sales.per_set()
        ],
        best_cards=list(by_card.order_by("-profit", "-sold_at")[:limit]),
        worst_cards=list(by_card.order_by("profit", "-sold_at")[:limit]),
        fastest=list(timed.order_by("days_to_sale", "-sold_at")[:limit]),
        slowest=list(timed.order_by("-days_to_sale", "-sold_at")[:limit]),
        oldest_stock=[_with_age(c, today) for c in stock[:10]],
        attention=aging.attention(user, today),
    )


def _months(sales, today, start):
    """Omzet en winst per maand, inclusief maanden zonder verkoop."""
    first = _month_start(today)
    for _ in range(MONTHS_IN_CHART - 1):
        first = _month_start(first - timedelta(days=1))
    if start and _month_start(start) > first:
        first = _month_start(start)

    found = {
        _month_start(row["month"]): row
        for row in sales.filter(sold_at__gte=first).profit_per_month()
    }
    months, cursor = [], first
    while cursor <= today:
        row = found.get(cursor, {})
        months.append(
            {
                "month": cursor,
                "revenue": row.get("revenue") or ZERO,
                "profit": row.get("profit_total") or ZERO,
            }
        )
        cursor = _month_start(cursor + timedelta(days=32))
    return months


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _with_age(card, today):
    card.age_days = (today - card.acquired_on).days if card.acquired_on else None
    return card
