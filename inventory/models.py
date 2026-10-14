from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce


class CardStatus(models.TextChoices):
    IN_STOCK = "in_stock", "In voorraad"
    FOR_SALE = "for_sale", "Te koop"
    SOLD = "sold", "Verkocht"


class Variant(models.TextChoices):
    BASE = "base", "Base"
    PARALLEL = "parallel", "Parallel"
    ROOKIE = "rookie", "Rookie"
    AUTO = "auto", "Auto"
    INSERT = "insert", "Insert"


class CardQuerySet(models.QuerySet):
    def owned_by(self, user):
        return self.filter(owner=user)

    def search(self, term):
        if not term:
            return self
        return self.filter(
            Q(player__icontains=term)
            | Q(set_name__icontains=term)
            | Q(card_number__iexact=term)
            | Q(notes__icontains=term)
        )

    def with_cost(self):
        """Annoteert de totale inkoopkosten (prijs + verzending in)."""
        zero = models.Value(Decimal("0.00"), output_field=models.DecimalField())
        return self.annotate(
            cost_total=Coalesce(
                Sum(models.F("purchases__price") + models.F("purchases__shipping_in")),
                zero,
                output_field=models.DecimalField(max_digits=10, decimal_places=2),
            )
        )

    def inventory_value(self):
        """Totale inkoopwaarde van alles wat nog niet verkocht is."""
        return self.exclude(status=CardStatus.SOLD).aggregate(
            total=Coalesce(
                Sum(models.F("purchases__price") + models.F("purchases__shipping_in")),
                models.Value(Decimal("0.00")),
                output_field=models.DecimalField(max_digits=12, decimal_places=2),
            )
        )["total"]

    def count_per_set(self):
        return (
            self.values("set_name", "year")
            .annotate(n=Count("id"))
            .order_by("-n", "set_name")
        )


class Card(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cards"
    )
    player = models.CharField("speler", max_length=120)
    sport = models.CharField(max_length=60, blank=True)
    set_name = models.CharField("set", max_length=120)
    year = models.PositiveSmallIntegerField("jaar")
    card_number = models.CharField("kaartnummer", max_length=30, blank=True)
    variant = models.CharField(
        max_length=20, choices=Variant.choices, default=Variant.BASE
    )
    condition = models.CharField("conditie", max_length=60, blank=True)
    notes = models.TextField("notities", blank=True)
    status = models.CharField(
        max_length=20, choices=CardStatus.choices, default=CardStatus.IN_STOCK
    )
    listed_since = models.DateField("te koop sinds", null=True, blank=True)
    held_until = models.DateField("vastgehouden tot", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = CardQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "status"]),
            models.Index(fields=["owner", "set_name", "year"]),
        ]

    def __str__(self):
        number = f" #{self.card_number}" if self.card_number else ""
        return f"{self.year} {self.set_name} {self.player}{number}"

    @property
    def total_cost(self) -> Decimal:
        if hasattr(self, "cost_total"):
            return self.cost_total
        return sum(
            (p.price + p.shipping_in for p in self.purchases.all()), Decimal("0.00")
        )


class Purchase(models.Model):
    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name="purchases")
    price = models.DecimalField("inkoopprijs", max_digits=10, decimal_places=2)
    shipping_in = models.DecimalField(
        "verzendkosten in", max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    date = models.DateField("datum")
    source = models.CharField("bron", max_length=120, blank=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"{self.card} – €{self.price}"
