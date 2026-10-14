from decimal import Decimal

from django import forms

from .models import FeeProfile

ZERO = Decimal("0.00")


def money_field(label, required=False):
    return forms.DecimalField(
        label=label,
        max_digits=10,
        decimal_places=2,
        min_value=ZERO,
        required=required,
        initial=None if required else ZERO,
        widget=forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
    )


class FeeProfileForm(forms.ModelForm):
    class Meta:
        model = FeeProfile
        fields = ["category", "commission_percentage", "fixed_fee", "payment_percentage", "valid_from"]
        widgets = {"valid_from": forms.DateInput(attrs={"type": "date"})}


class CalculatorForm(forms.Form):
    MODE_FORWARD = "forward"
    MODE_REVERSE = "reverse"

    mode = forms.ChoiceField(
        choices=[(MODE_FORWARD, "Profit at a price"), (MODE_REVERSE, "Price for a profit")],
        initial=MODE_FORWARD,
        widget=forms.RadioSelect,
        label="Calculate",
    )
    fee_profile = forms.ModelChoiceField(
        queryset=FeeProfile.objects.none(), label="Fee profile", empty_label=None
    )
    sale_price = forms.DecimalField(
        label="Sale price",
        max_digits=10,
        decimal_places=2,
        min_value=ZERO,
        required=False,
        widget=forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
    )
    target_profit = forms.DecimalField(
        label="Target profit",
        max_digits=10,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={"step": "0.01"}),
    )
    shipping_income = money_field("Shipping charged")
    shipping_cost = money_field("Shipping cost")
    packaging_cost = money_field("Packaging cost")
    purchase_cost = money_field("Purchase cost")

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fee_profile"].queryset = FeeProfile.objects.filter(user=user)

    def clean(self):
        cleaned = super().clean()
        for name in ("shipping_income", "shipping_cost", "packaging_cost", "purchase_cost"):
            if cleaned.get(name) is None:
                cleaned[name] = ZERO
        mode = cleaned.get("mode")
        if mode == self.MODE_FORWARD and cleaned.get("sale_price") is None:
            self.add_error("sale_price", "Enter a sale price.")
        if mode == self.MODE_REVERSE and cleaned.get("target_profit") is None:
            self.add_error("target_profit", "Enter the target profit.")
        return cleaned
