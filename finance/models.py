from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from .calculator import Fees

PERCENT_VALIDATORS = [MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("99.99"))]


class FeeProfileQuerySet(models.QuerySet):
    def current_for(self, user, category, on_date=None):
        """Het meest recente profiel dat op `on_date` geldig is, of None."""
        on_date = on_date or timezone.localdate()
        return (
            self.filter(user=user, category=category, valid_from__lte=on_date)
            .order_by("-valid_from", "-id")
            .first()
        )


class FeeProfile(models.Model):
    """Kostenstructuur van eBay per categorie.

    Tarieven veranderen; daarom staan ze hier en niet in de code. Een nieuw
    tarief is een nieuw profiel met een latere `valid_from`, zodat oude
    verkopen met het oude tarief herleidbaar blijven.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="fee_profiles"
    )
    category = models.CharField("categorie", max_length=80, default="Sportkaarten")
    commission_percentage = models.DecimalField(
        "commissie %", max_digits=5, decimal_places=2, validators=PERCENT_VALIDATORS
    )
    fixed_fee = models.DecimalField(
        "vaste kosten per order",
        max_digits=8,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    payment_percentage = models.DecimalField(
        "betaalkosten %",
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=PERCENT_VALIDATORS,
    )
    valid_from = models.DateField("geldig vanaf", default=timezone.localdate)

    objects = FeeProfileQuerySet.as_manager()

    class Meta:
        ordering = ["category", "-valid_from"]

    def __str__(self):
        return f"{self.category} vanaf {self.valid_from:%d-%m-%Y}"

    def to_fees(self) -> Fees:
        return Fees(
            commission_percentage=self.commission_percentage,
            fixed_fee=self.fixed_fee,
            payment_percentage=self.payment_percentage,
        )
