from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Count, ExpressionWrapper, F, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce, TruncMonth

from finance.calculator import ZERO
from inventory.models import Card, Purchase

MONEY = dict(max_digits=10, decimal_places=2)
DEC = models.DecimalField(max_digits=14, decimal_places=2)


class ListingStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    SOLD = "sold", "Sold"
    WITHDRAWN = "withdrawn", "Withdrawn"


class Listing(models.Model):
    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name="listings")
    title = models.CharField(max_length=80)
    description = models.TextField(blank=True)
    asking_price = models.DecimalField("asking price", **MONEY)
    ebay_item_id = models.CharField(max_length=40, blank=True)
    status = models.CharField(
        max_length=20, choices=ListingStatus.choices, default=ListingStatus.DRAFT
    )
    listed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return self.title


class ListingTemplate(models.Model):
    """Title and description patterns, with placeholders such as {player}.

    The valid placeholders are listed in `sales.listing_generator.PLACEHOLDERS`.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="listing_templates"
    )
    name = models.CharField(max_length=60)
    title_pattern = models.CharField(max_length=200)
    description_pattern = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["user", "name"], name="unique_template_name_per_user")
        ]

    def __str__(self):
        return self.name


class SaleQuerySet(models.QuerySet):
    def owned_by(self, user):
        return self.filter(listing__card__owner=user)

    def with_profit(self):
        """Annotate net proceeds; profit = net - the card's purchase cost.

        Purchase cost comes from a subquery so that several purchases per
        card do not multiply the sale amounts.
        """
        cost = (
            Purchase.objects.filter(card=OuterRef("listing__card"))
            .values("card")
            .annotate(t=Sum(F("price") + F("shipping_in")))
            .values("t")
        )
        dec = models.DecimalField(max_digits=12, decimal_places=2)
        return self.annotate(
            net=ExpressionWrapper(
                F("sale_price")
                + F("shipping_income")
                - F("ebay_commission")
                - F("payment_fee")
                - F("shipping_cost")
                - F("packaging_cost"),
                output_field=dec,
            ),
            cost=Coalesce(Subquery(cost, output_field=dec), Value(ZERO), output_field=dec),
        ).annotate(profit=ExpressionWrapper(F("net") - F("cost"), output_field=dec))

    def in_period(self, start=None, end=None):
        qs = self
        if start:
            qs = qs.filter(sold_at__gte=start)
        if end:
            qs = qs.filter(sold_at__lte=end)
        return qs

    def profit_per_month(self):
        return (
            self.with_profit()
            .annotate(month=TruncMonth("sold_at"))
            .values("month")
            .annotate(
                revenue=Sum(F("sale_price") + F("shipping_income"), output_field=DEC),
                profit_total=Sum("profit", output_field=DEC),
            )
            .order_by("month")
        )

    def totals(self):
        """Count, revenue (gross), net and profit. One query."""
        return self.with_profit().aggregate(
            count=Count("id"),
            revenue=Coalesce(Sum(F("sale_price") + F("shipping_income"), output_field=DEC), Value(ZERO)),
            net_total=Coalesce(Sum("net", output_field=DEC), Value(ZERO)),
            profit_total=Coalesce(Sum("profit", output_field=DEC), Value(ZERO)),
        )

    def per_set(self):
        return (
            self.with_profit()
            .values("listing__card__set_name", "listing__card__year")
            .annotate(
                count=Count("id"),
                revenue=Sum(F("sale_price") + F("shipping_income"), output_field=DEC),
                profit_total=Sum("profit", output_field=DEC),
            )
            .order_by("-profit_total", "listing__card__set_name")
        )

    def with_days_to_sale(self):
        """Days to sale: from 'listed since', otherwise from the first purchase
        date. Without either, the value is None."""
        first_purchase = (
            Purchase.objects.filter(card=OuterRef("listing__card"))
            .order_by("date")
            .values("date")[:1]
        )
        return self.annotate(
            start_date=Coalesce(
                F("listing__card__listed_since"),
                Subquery(first_purchase, output_field=models.DateField()),
                output_field=models.DateField(),
            )
        ).annotate(
            days_to_sale=ExpressionWrapper(
                F("sold_at") - F("start_date"), output_field=models.DurationField()
            )
        )


class Sale(models.Model):
    """A sale. Fee amounts are recorded at the moment of sale, so a later
    change in rates does not alter past profits."""

    listing = models.OneToOneField(Listing, on_delete=models.CASCADE, related_name="sale")
    sale_price = models.DecimalField("sale price", **MONEY)
    shipping_income = models.DecimalField("shipping charged", default=ZERO, **MONEY)
    ebay_commission = models.DecimalField("eBay commission", default=ZERO, **MONEY)
    payment_fee = models.DecimalField(default=ZERO, **MONEY)
    shipping_cost = models.DecimalField(default=ZERO, **MONEY)
    packaging_cost = models.DecimalField(default=ZERO, **MONEY)
    sold_at = models.DateField("sold on")
    buyer_country = models.CharField(max_length=2, blank=True)

    objects = SaleQuerySet.as_manager()

    class Meta:
        ordering = ["-sold_at"]

    def __str__(self):
        return f"{self.listing.card} – €{self.sale_price}"

    @property
    def gross(self) -> Decimal:
        return self.sale_price + self.shipping_income

    @property
    def net_proceeds(self) -> Decimal:
        return (
            self.gross
            - self.ebay_commission
            - self.payment_fee
            - self.shipping_cost
            - self.packaging_cost
        )
