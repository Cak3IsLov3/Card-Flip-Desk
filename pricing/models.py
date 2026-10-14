from django.db import models

from inventory.models import Card


class PriceSource(models.TextChoices):
    EBAY_ACTIVE = "ebay_active", "eBay actieve listings"
    OWN_HISTORY = "own_history", "Eigen verkoophistorie"


class PriceSnapshot(models.Model):
    """Momentopname van een prijsbeeld (mediaan), zodat je het verloop ziet."""

    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name="price_snapshots")
    source = models.CharField("bron", max_length=20, choices=PriceSource.choices)
    price = models.DecimalField("mediaan", max_digits=10, decimal_places=2)
    minimum = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    maximum = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    listing_count = models.PositiveIntegerField("aantal")
    query = models.CharField("zoekterm", max_length=200, blank=True)
    taken_at = models.DateTimeField("genomen op", auto_now_add=True)

    class Meta:
        ordering = ["-taken_at", "-id"]

    def __str__(self):
        return f"{self.card} – {self.get_source_display()}: €{self.price}"
