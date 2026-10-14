import os
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Case, Count, F, Min, OuterRef, Q, Subquery, Sum, When
from django.db.models.functions import Coalesce, TruncDate

from .storage import photo_storage


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

    def with_age_start(self):
        """Annoteert `age_start`: de datum vanaf waar de leeftijd telt.

        Te koop: vanaf 'te koop sinds'. Anders (of als die ontbreekt): vanaf
        de eerste inkoop, en zonder inkoop vanaf het moment van invoeren.
        """
        first_purchase = (
            Purchase.objects.filter(card=OuterRef("pk")).order_by("date").values("date")[:1]
        )
        return self.annotate(
            age_start=Coalesce(
                Case(When(status=CardStatus.FOR_SALE, then=F("listed_since"))),
                Subquery(first_purchase, output_field=models.DateField()),
                TruncDate("created_at"),
                output_field=models.DateField(),
            )
        )

    def not_pinned(self, today):
        return self.filter(Q(held_until__isnull=True) | Q(held_until__lt=today))

    def unsold_by_age(self):
        """Onverkochte kaarten met inkoopkosten, oudste inkoop eerst."""
        return (
            self.exclude(status=CardStatus.SOLD)
            .with_cost()
            .annotate(acquired_on=Min("purchases__date"))
            .order_by(F("acquired_on").asc(nulls_last=True), "id")
        )

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


class PhotoLabel(models.TextChoices):
    FRONT = "front", "Voorkant"
    BACK = "back", "Achterkant"
    CORNER = "corner", "Hoek"
    DEFECT = "defect", "Defect"
    OTHER = "other", "Overig"


def photo_upload_to(instance, filename):
    # De naam die hier binnenkomt komt van ons (bijv. "upload.jpg"), nooit
    # van de gebruiker; alleen de extensie wordt overgenomen.
    ext = os.path.splitext(filename)[1].lower()
    return f"cards/{uuid.uuid4().hex}{ext}"


def thumb_upload_to(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"cards/thumbs/{uuid.uuid4().hex}{ext}"


class CardPhoto(models.Model):
    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to=photo_upload_to, storage=photo_storage)
    thumbnail = models.ImageField(upload_to=thumb_upload_to, storage=photo_storage)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    content_type = models.CharField(max_length=20)
    position = models.PositiveSmallIntegerField("volgorde", default=0)
    is_main = models.BooleanField("hoofdfoto", default=False)
    label = models.CharField(max_length=10, choices=PhotoLabel.choices, default=PhotoLabel.OTHER)
    uploaded_at = models.DateTimeField("geüpload op", auto_now_add=True)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["card"], condition=Q(is_main=True), name="one_main_photo_per_card"
            )
        ]

    def __str__(self):
        return f"{self.get_label_display()} – {self.card}"


class StaleThreshold(models.Model):
    """Drempels voor oude voorraad, per gebruiker instelbaar."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="stale_threshold"
    )
    warning_days = models.PositiveSmallIntegerField("waarschuwing na (dagen)", default=30)
    action_days = models.PositiveSmallIntegerField("actie na (dagen)", default=60)
    critical_days = models.PositiveSmallIntegerField("kritiek na (dagen)", default=90)
    price_drop_percentage = models.DecimalField(
        "voorgestelde prijsverlaging %", max_digits=4, decimal_places=1, default=Decimal("10.0")
    )
    weekly_email = models.BooleanField("wekelijks overzicht per e-mail", default=True)
    last_digest_sent_on = models.DateField(null=True, blank=True, editable=False)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(warning_days__gt=0)
                & Q(action_days__gt=F("warning_days"))
                & Q(critical_days__gt=F("action_days")),
                name="stale_thresholds_increasing",
            )
        ]

    def __str__(self):
        return f"{self.warning_days}/{self.action_days}/{self.critical_days} dagen"

    @classmethod
    def for_user(cls, user):
        obj, _ = cls.objects.get_or_create(user=user)
        return obj


class NoteKind(models.TextChoices):
    PINNED = "pinned", "Vastgezet"
    UNPINNED = "unpinned", "Losgemaakt"
    PRICE_LOWERED = "price_lowered", "Prijs verlaagd"
    BUNDLED = "bundled", "Gebundeld"


class InventoryNote(models.Model):
    """Logboek van acties op oude voorraad."""

    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name="inventory_notes")
    kind = models.CharField("type", max_length=20, choices=NoteKind.choices)
    created_at = models.DateTimeField("gemaakt op", auto_now_add=True)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.get_kind_display()} – {self.card}"


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
