import os
import re
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Case, Count, F, Min, OuterRef, Q, Subquery, Sum, When
from django.db.models.functions import Coalesce, TruncDate

from .storage import photo_storage


class CardStatus(models.TextChoices):
    IN_STOCK = "in_stock", "In stock"
    FOR_SALE = "for_sale", "For sale"
    SOLD = "sold", "Sold"


class Variant(models.TextChoices):
    """Card variants. A card can have several (e.g. a rookie auto); none means base.

    The order here is the order they appear in titles ("Rookie Auto").
    """

    ROOKIE = "rookie", "Rookie"
    AUTO = "auto", "Auto"
    PARALLEL = "parallel", "Parallel"
    INSERT = "insert", "Insert"


class Condition(models.TextChoices):
    """Raw (ungraded) card condition, best first."""

    MINT = "mint", "Mint"
    NEAR_MINT = "near_mint", "Near Mint"
    EXCELLENT = "excellent", "Excellent"
    VERY_GOOD = "very_good", "Very Good"
    GOOD = "good", "Good"
    FAIR = "fair", "Fair"
    POOR = "poor", "Poor"


# Free-text conditions and common abbreviations, used by the CSV import and the
# data migration. Keys are lower case without punctuation.
CONDITION_ALIASES = {
    "mint": Condition.MINT, "m": Condition.MINT, "mt": Condition.MINT, "gem mint": Condition.MINT,
    "near mint": Condition.NEAR_MINT, "nm": Condition.NEAR_MINT, "nm mt": Condition.NEAR_MINT,
    "near mint or better": Condition.NEAR_MINT,
    "excellent": Condition.EXCELLENT, "ex": Condition.EXCELLENT, "ex mt": Condition.EXCELLENT,
    "very good": Condition.VERY_GOOD, "vg": Condition.VERY_GOOD, "vg ex": Condition.VERY_GOOD,
    "good": Condition.GOOD, "g": Condition.GOOD,
    "fair": Condition.FAIR, "f": Condition.FAIR,
    "poor": Condition.POOR, "p": Condition.POOR,
}


def parse_condition(value) -> str | None:
    """Map free text such as 'NM-MT' or 'Near Mint' to a Condition; '' stays ''.

    Returns None when the text cannot be recognised.
    """
    text = " ".join("".join(c if c.isalnum() else " " for c in str(value or "").lower()).split())
    if not text:
        return ""
    if text.replace(" ", "_") in Condition.values:
        return text.replace(" ", "_")
    return CONDITION_ALIASES.get(text)


SERIAL_RE = re.compile(r"^\s*(\d*)\s*/\s*(\d+)\s*$")


def normalise_serial(value: str) -> str:
    """'23 / 50' -> '23/50', ' /99' -> '/99'. Raises ValueError for anything else."""
    if not (value or "").strip():
        return ""
    match = SERIAL_RE.match(value)
    if not match or (match.group(1) and int(match.group(1)) > int(match.group(2))):
        raise ValueError("Use the format 23/50, or /50 when you only know the print run.")
    return f"{match.group(1)}/{match.group(2)}"


def validate_serial(value):
    try:
        normalise_serial(value)
    except ValueError as exc:
        raise ValidationError(str(exc)) from None


VARIANT_ORDER = [v.value for v in Variant]
# Words that mean "no special variant" in imports and old data.
BASE_WORDS = {"", "base"}


def normalise_variants(values) -> list[str]:
    """Lower-case, drop "base", remove duplicates and sort in the fixed order.

    Raises ValueError for unknown variants, so bad data never ends up stored.
    """
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    cleaned = {str(v).strip().lower() for v in values} - BASE_WORDS
    unknown = sorted(cleaned - set(VARIANT_ORDER))
    if unknown:
        raise ValueError("Unknown variant(s): " + ", ".join(unknown))
    return sorted(cleaned, key=VARIANT_ORDER.index)


def validate_variants(value):
    if not isinstance(value, list):
        raise ValidationError("Variants must be a list.")
    try:
        normalise_variants(value)
    except ValueError as exc:
        raise ValidationError(str(exc)) from None


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
        """Annotate the total purchase cost (price + inbound shipping)."""
        zero = models.Value(Decimal("0.00"), output_field=models.DecimalField())
        return self.annotate(
            cost_total=Coalesce(
                Sum(models.F("purchases__price") + models.F("purchases__shipping_in")),
                zero,
                output_field=models.DecimalField(max_digits=10, decimal_places=2),
            )
        )

    def inventory_value(self):
        """Total purchase value of everything not yet sold."""
        return self.exclude(status=CardStatus.SOLD).aggregate(
            total=Coalesce(
                Sum(models.F("purchases__price") + models.F("purchases__shipping_in")),
                models.Value(Decimal("0.00")),
                output_field=models.DecimalField(max_digits=12, decimal_places=2),
            )
        )["total"]

    def with_age_start(self):
        """Annotate `age_start`: the date from which a card's age is counted.

        For sale: from 'listed since'. Otherwise (or if that is missing): from
        the first purchase, and without a purchase from when it was entered.
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
        """Unsold cards with their purchase cost, oldest purchase first."""
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
    player = models.CharField(max_length=120)
    sport = models.CharField(max_length=60, blank=True)
    set_name = models.CharField("set", max_length=120)
    year = models.PositiveSmallIntegerField()
    card_number = models.CharField("card number", max_length=30, blank=True)
    variants = models.JSONField(default=list, blank=True, validators=[validate_variants])
    # Which parallel or insert it is, e.g. "Gold Refractor /50" or "Future Stars".
    parallel_name = models.CharField("parallel", max_length=80, blank=True)
    parallel_serial = models.CharField(
        "serial number", max_length=20, blank=True, validators=[validate_serial]
    )
    insert_name = models.CharField("insert", max_length=80, blank=True)
    condition = models.CharField(max_length=20, choices=Condition.choices, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=CardStatus.choices, default=CardStatus.IN_STOCK
    )
    listed_since = models.DateField(null=True, blank=True)
    held_until = models.DateField("held until", null=True, blank=True)
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

    def save(self, *args, **kwargs):
        self.variants = normalise_variants(self.variants)
        # A name only means something while its variant is ticked.
        if Variant.PARALLEL not in self.variants:
            self.parallel_name = ""
            self.parallel_serial = ""
        else:
            self.parallel_serial = normalise_serial(self.parallel_serial)
        if Variant.INSERT not in self.variants:
            self.insert_name = ""
        super().save(*args, **kwargs)

    def _names(self) -> dict[str, str]:
        parallel = " ".join(p for p in (self.parallel_name.strip(), self.parallel_serial.strip()) if p)
        return {Variant.PARALLEL: parallel, Variant.INSERT: self.insert_name.strip()}

    @property
    def variant_labels(self) -> list[str]:
        """Labels for titles: the parallel/insert name when known, e.g. ['Rookie', 'Gold Refractor 23/50']."""
        labels, names = dict(Variant.choices), self._names()
        return [names.get(v) or labels[v] for v in normalise_variants(self.variants)]

    @property
    def variant_display(self) -> str:
        """'Rookie, Parallel (Gold Refractor /50)', or 'Base' when there is no special variant."""
        labels, names = dict(Variant.choices), self._names()
        parts = []
        for v in normalise_variants(self.variants):
            name = names.get(v)
            parts.append(f"{labels[v]} ({name})" if name else labels[v])
        return ", ".join(parts) or "Base"

    @property
    def total_cost(self) -> Decimal:
        if hasattr(self, "cost_total"):
            return self.cost_total
        return sum(
            (p.price + p.shipping_in for p in self.purchases.all()), Decimal("0.00")
        )


class PhotoLabel(models.TextChoices):
    FRONT = "front", "Front"
    BACK = "back", "Back"
    CORNER = "corner", "Corner"
    DEFECT = "defect", "Defect"
    OTHER = "other", "Other"


def photo_upload_to(instance, filename):
    # The name passed in comes from us (e.g. "upload.jpg"), never from the
    # user; only the extension is kept.
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
    position = models.PositiveSmallIntegerField(default=0)
    is_main = models.BooleanField("main photo", default=False)
    label = models.CharField(max_length=10, choices=PhotoLabel.choices, default=PhotoLabel.OTHER)
    uploaded_at = models.DateTimeField(auto_now_add=True)

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
    """Stale-inventory thresholds, configurable per user."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="stale_threshold"
    )
    warning_days = models.PositiveSmallIntegerField("warning after (days)", default=30)
    action_days = models.PositiveSmallIntegerField("action after (days)", default=60)
    critical_days = models.PositiveSmallIntegerField("critical after (days)", default=90)
    price_drop_percentage = models.DecimalField(
        "suggested price drop %", max_digits=4, decimal_places=1, default=Decimal("10.0")
    )
    weekly_email = models.BooleanField("weekly email digest", default=True)
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
        return f"{self.warning_days}/{self.action_days}/{self.critical_days} days"

    @classmethod
    def for_user(cls, user):
        obj, _ = cls.objects.get_or_create(user=user)
        return obj


class NoteKind(models.TextChoices):
    PINNED = "pinned", "Pinned"
    UNPINNED = "unpinned", "Unpinned"
    PRICE_LOWERED = "price_lowered", "Price lowered"
    BUNDLED = "bundled", "Bundled"


class InventoryNote(models.Model):
    """Log of actions taken on stale inventory."""

    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name="inventory_notes")
    kind = models.CharField(max_length=20, choices=NoteKind.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.get_kind_display()} – {self.card}"


class Purchase(models.Model):
    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name="purchases")
    price = models.DecimalField("purchase price", max_digits=10, decimal_places=2)
    shipping_in = models.DecimalField(
        "inbound shipping", max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    date = models.DateField()
    source = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"{self.card} – €{self.price}"
