from django import forms
from django.utils import timezone

from finance.calculator import ZERO
from finance.forms import money_field
from finance.models import FeeProfile

from .listing_generator import PLACEHOLDERS, TITLE_MAX_LENGTH, unknown_placeholders
from .models import ListingTemplate


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


PLACEHOLDER_HELP = "Plaatshouders: " + " ".join("{" + p + "}" for p in PLACEHOLDERS)


class ListingTemplateForm(forms.ModelForm):
    class Meta:
        model = ListingTemplate
        fields = ["name", "title_pattern", "description_pattern"]
        widgets = {"description_pattern": forms.Textarea(attrs={"rows": 8})}
        help_texts = {"title_pattern": PLACEHOLDER_HELP, "description_pattern": PLACEHOLDER_HELP}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def _check(self, name):
        value = self.cleaned_data.get(name, "")
        unknown = unknown_placeholders(value)
        if unknown:
            raise forms.ValidationError(
                "Onbekende plaatshouder(s): " + ", ".join("{" + u + "}" for u in unknown)
            )
        return value

    def clean_title_pattern(self):
        return self._check("title_pattern")

    def clean_description_pattern(self):
        return self._check("description_pattern")

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        clash = ListingTemplate.objects.filter(user=self.user, name__iexact=name)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError("Je hebt al een template met deze naam.")
        return name


class ListingDraftForm(forms.Form):
    title = forms.CharField(
        label="Titel",
        max_length=TITLE_MAX_LENGTH,
        widget=forms.TextInput(attrs={"maxlength": TITLE_MAX_LENGTH, "data-counter": "title"}),
    )
    description = forms.CharField(
        label="Beschrijving", required=False, widget=forms.Textarea(attrs={"rows": 10})
    )
    asking_price = money_field("Vraagprijs", required=True)
