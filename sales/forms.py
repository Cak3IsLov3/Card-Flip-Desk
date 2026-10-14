from django import forms
from django.utils import timezone

from finance.calculator import ZERO
from finance.forms import money_field
from finance.models import FeeProfile


class SaleForm(forms.Form):
    sale_price = money_field("Verkoopprijs", required=True)
    shipping_income = money_field("Verzendopbrengst")
    shipping_cost = money_field("Verzendkosten uit")
    packaging_cost = money_field("Verpakkingskosten")
    sold_at = forms.DateField(
        label="Verkocht op", widget=forms.DateInput(attrs={"type": "date"})
    )
    buyer_country = forms.CharField(
        label="Land koper (ISO, bv. NL)", max_length=2, required=False
    )
    category = forms.ChoiceField(label="Kostenprofiel (categorie)")

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sold_at"].initial = timezone.localdate()
        categories = (
            FeeProfile.objects.filter(user=user)
            .order_by("category")
            .values_list("category", flat=True)
            .distinct()
        )
        self.fields["category"].choices = [(c, c) for c in categories]

    def clean(self):
        cleaned = super().clean()
        for name in ("shipping_income", "shipping_cost", "packaging_cost"):
            if cleaned.get(name) is None:
                cleaned[name] = ZERO
        return cleaned
