from decimal import Decimal

from django.db import models
from django.db.models import Count, ExpressionWrapper, F, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce, TruncMonth

from finance.calculator import ZERO
from inventory.models import Card, Purchase

MONEY = dict(max_digits=10, decimal_places=2)
DEC = models.DecimalField(max_digits=14, decimal_places=2)


class ListingStatus(models.TextChoices):
    DRAFT = "draft", "Concept"
    ACTIVE = "active", "Actief"
    SOLD = "sold", "Verkocht"
    WITHDRAWN = "withdrawn", "Ingetrokken"


class Listing(models.Model):
    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name="listings")
    title = models.CharField("titel", max_length=80)
    description = models.TextField("beschrijving", blank=True)
    asking_price = models.DecimalField("vraagprijs", **MONEY)
    ebay_item_id = models.CharField(max_length=40, blank=True)
    status = models.CharField(
        max_length=20, choices=ListingStatus.choices, default=ListingStatus.DRAFT
    )
    listed_at = models.DateTimeField("geplaatst op", null=True, blank=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return self.title


class SaleQuerySet(models.QuerySet):
    def owned_by(self, user):
        return self.filter(listing__card__owner=user)

    def with_profit(self):
        """Annoteert netto-opbrengst; winst = netto - inkoop van de kaart.

        Inkoop wordt via een subquery opgehaald zodat meerdere aankopen per
        kaart de verkoopbedragen niet vermenigvuldigen.
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
        """Aantal, omzet (bruto), netto, winst. Eén query."""
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
        """Dagen tot verkoop: vanaf 'te koop sinds', anders vanaf de eerste
        inkoopdatum. Zonder beide is de waarde None."""
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
    """Een verkoop. Kostenbedragen worden vastgelegd op het moment van
    verkoop, zodat een latere tariefwijziging oude winsten niet verandert."""

    listing = models.OneToOneField(Listing, on_delete=models.CASCADE, related_name="sale")
    sale_price = models.DecimalField("verkoopprijs", **MONEY)
    shipping_income = models.DecimalField("verzendopbrengst", default=ZERO, **MONEY)
    ebay_commission = models.DecimalField("eBay-commissie", default=ZERO, **MONEY)
    payment_fee = models.DecimalField("betaalkosten", default=ZERO, **MONEY)
    shipping_cost = models.DecimalField("verzendkosten uit", default=ZERO, **MONEY)
    packaging_cost = models.DecimalField("verpakkingskosten", default=ZERO, **MONEY)
    sold_at = models.DateField("verkocht op")
    buyer_country = models.CharField("land koper", max_length=2, blank=True)

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
