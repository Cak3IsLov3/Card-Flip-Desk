from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from .calculator import Fees

DEFAULT_CATEGORY = "Sports cards"
PERCENT_VALIDATORS = [MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("99.99"))]


class FeeProfileQuerySet(models.QuerySet):
    def current_for(self, user, category, on_date=None):
        """The most recent profile valid on `on_date`, or None."""
        on_date = on_date or timezone.localdate()
        return (
            self.filter(user=user, category=category, valid_from__lte=on_date)
            .order_by("-valid_from", "-id")
            .first()
        )


class FeeProfile(models.Model):
    """eBay fee structure per category.

    Rates change; that is why they live here and not in the code. A new rate
    is a new profile with a later `valid_from`, so older sales stay
    traceable to the rate that applied at the time.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="fee_profiles"
    )
    category = models.CharField(max_length=80, default=DEFAULT_CATEGORY)
    commission_percentage = models.DecimalField(
        "commission %", max_digits=5, decimal_places=2, validators=PERCENT_VALIDATORS
    )
    fixed_fee = models.DecimalField(
        "fixed fee per order",
        max_digits=8,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    payment_percentage = models.DecimalField(
        "payment fee %",
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=PERCENT_VALIDATORS,
    )
    valid_from = models.DateField(default=timezone.localdate)

    objects = FeeProfileQuerySet.as_manager()

    class Meta:
        ordering = ["category", "-valid_from"]

    def __str__(self):
        return f"{self.category} from {self.valid_from:%d-%m-%Y}"

    def to_fees(self) -> Fees:
        return Fees(
            commission_percentage=self.commission_percentage,
            fixed_fee=self.fixed_fee,
            payment_percentage=self.payment_percentage,
        )


class ShippingMethod(models.Model):
    """A way of sending a card and what it costs you, e.g. "Deutsche Post Großbrief".

    Choosing one fills in the shipping cost. Rates change, so they live here
    and are editable; a sale stores the amount itself, so changing a rate
    never alters past sales.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shipping_methods"
    )
    name = models.CharField(max_length=80)
    cost = models.DecimalField(
        max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )
    note = models.CharField(max_length=120, blank=True, help_text="Limits, tracking, insurance …")

    class Meta:
        ordering = ["cost", "name"]
        constraints = [
            models.UniqueConstraint(fields=["user", "name"], name="unique_shipping_method_name_per_user"),
        ]

    def __str__(self):
        return f"{self.name} (€{self.cost})"
