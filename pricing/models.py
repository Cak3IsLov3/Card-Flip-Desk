from django.db import models

from inventory.models import Card


class PriceSource(models.TextChoices):
    EBAY_ACTIVE = "ebay_active", "eBay active listings"
    OWN_HISTORY = "own_history", "Own sales history"
    MANUAL_SOLD = "manual_sold", "eBay sold prices (entered)"


class PriceSnapshot(models.Model):
    """Snapshot of a price picture (median), so you can see how it changes."""

    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name="price_snapshots")
    source = models.CharField(max_length=20, choices=PriceSource.choices)
    price = models.DecimalField("median", max_digits=10, decimal_places=2)
    minimum = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    maximum = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    listing_count = models.PositiveIntegerField("count")
    query = models.CharField("search query", max_length=200, blank=True)
    taken_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-taken_at", "-id"]

    def __str__(self):
        return f"{self.card} – {self.get_source_display()}: €{self.price}"
