from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from finance.calculator import ZERO, CostInput, Fees, calculate, money
from finance.models import FeeProfile
from inventory.models import Card, CardStatus

from .models import Listing, ListingStatus, Sale


class NoFeeProfile(Exception):
    pass


def fees_for(user, category: str, on_date: date) -> Fees:
    profile = FeeProfile.objects.current_for(user, category, on_date)
    if profile is None:
        raise NoFeeProfile(
            f"Geen kostenprofiel voor categorie '{category}' op {on_date:%d-%m-%Y}."
        )
    return profile.to_fees()


@transaction.atomic
def register_sale(
    card: Card,
    *,
    sale_price: Decimal,
    sold_at: date,
    shipping_income: Decimal = ZERO,
    shipping_cost: Decimal = ZERO,
    packaging_cost: Decimal = ZERO,
    buyer_country: str = "",
    category: str = "Sportkaarten",
    title: str = "",
) -> Sale:
    """Legt een verkoop vast en berekent de kosten met het geldende profiel.

    Gebruikt de actieve listing van de kaart; bestaat die niet, dan wordt
    er een aangemaakt (handmatige verkoop buiten de generator om).
    """
    fees = fees_for(card.owner, category, sold_at)
    result = calculate(
        CostInput(
            sale_price=sale_price,
            shipping_income=shipping_income,
            shipping_cost=shipping_cost,
            packaging_cost=packaging_cost,
        ),
        fees,
    )

    listing = (
        card.listings.filter(status__in=[ListingStatus.ACTIVE, ListingStatus.DRAFT])
        .order_by("-id")
        .first()
    )
    if listing is None:
        listing = Listing.objects.create(
            card=card,
            title=(title or str(card))[:80],
            asking_price=money(sale_price),
            status=ListingStatus.ACTIVE,
            listed_at=timezone.now(),
        )
    listing.status = ListingStatus.SOLD
    listing.save(update_fields=["status"])

    sale = Sale.objects.create(
        listing=listing,
        sale_price=money(sale_price),
        shipping_income=result.gross - money(sale_price),
        ebay_commission=result.commission,
        payment_fee=result.payment_fee,
        shipping_cost=result.shipping_cost,
        packaging_cost=result.packaging_cost,
        sold_at=sold_at,
        buyer_country=buyer_country.upper()[:2],
    )
    card.status = CardStatus.SOLD
    card.save(update_fields=["status", "updated_at"])
    return sale


def card_profit(card: Card) -> Decimal | None:
    """Winst op een kaart: netto-opbrengst van de verkoop min alle inkoop."""
    sale = Sale.objects.filter(listing__card=card).first()
    if sale is None:
        return None
    return sale.net_proceeds - card.total_cost
