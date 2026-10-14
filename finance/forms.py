from decimal import Decimal

from django import forms

from .models import FeeProfile, ShippingMethod

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


class ShippingMethodSelect(forms.Select):
    """Each option carries its cost, so shipping.js can fill in the cost field."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        method = getattr(value, "instance", None)
        if method is not None:
            option["attrs"]["data-cost"] = str(method.cost)
        return option


def shipping_method_field(user):
    return forms.ModelChoiceField(
        queryset=ShippingMethod.objects.filter(user=user),
        required=False,
        label="Shipping method",
        empty_label="Other (enter the cost yourself)",
        help_text="Fills in the shipping cost; you can still change it.",
        widget=ShippingMethodSelect(attrs={"data-fills": "shipping_cost"}),
    )


def apply_shipping_method(cleaned):
    """Without JavaScript: a chosen method fills a shipping cost left at 0.

    The method itself is removed; only the amount is used and stored.
    """
    method = cleaned.pop("shipping_method", None)
    if method is not None and not cleaned.get("shipping_cost"):
        cleaned["shipping_cost"] = method.cost


class ShippingMethodForm(forms.ModelForm):
    class Meta:
        model = ShippingMethod
        fields = ["name", "cost", "note"]
        widgets = {"cost": forms.NumberInput(attrs={"step": "0.01", "min": "0"})}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        clash = ShippingMethod.objects.filter(user=self.user, name__iexact=name)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError("You already have a shipping method with this name.")
        return name


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
    shipping_method = forms.ModelChoiceField(queryset=ShippingMethod.objects.none(), required=False)
    shipping_cost = money_field("Shipping cost")
    packaging_cost = money_field("Packaging cost")
    purchase_cost = money_field("Purchase cost")

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fee_profile"].queryset = FeeProfile.objects.filter(user=user)
        self.fields["shipping_method"] = shipping_method_field(user)

    def clean(self):
        cleaned = super().clean()
        for name in ("shipping_income", "shipping_cost", "packaging_cost", "purchase_cost"):
            if cleaned.get(name) is None:
                cleaned[name] = ZERO
        apply_shipping_method(cleaned)
        mode = cleaned.get("mode")
        if mode == self.MODE_FORWARD and cleaned.get("sale_price") is None:
            self.add_error("sale_price", "Enter a sale price.")
        if mode == self.MODE_REVERSE and cleaned.get("target_profit") is None:
            self.add_error("target_profit", "Enter the target profit.")
        return cleaned
