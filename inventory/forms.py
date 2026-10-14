from decimal import Decimal

from django import forms
from django.utils import timezone

from .csv_import import IMPORT_FIELDS, REQUIRED_FIELDS
from .models import Card, CardStatus, PhotoLabel, Purchase, StaleThreshold


class DateInput(forms.DateInput):
    input_type = "date"


class CardForm(forms.ModelForm):
    class Meta:
        model = Card
        fields = [
            "player", "sport", "set_name", "year", "card_number", "variant",
            "condition", "status", "listed_since", "held_until", "notes",
        ]
        widgets = {
            "listed_since": DateInput,
            "held_until": DateInput,
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("status") == CardStatus.FOR_SALE and not cleaned.get("listed_since"):
            cleaned["listed_since"] = timezone.localdate()
        return cleaned


class PurchaseForm(forms.ModelForm):
    class Meta:
        model = Purchase
        fields = ["price", "shipping_in", "date", "source"]
        widgets = {"date": DateInput}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date"].initial = timezone.localdate()
        self.fields["price"].widget.attrs["min"] = "0"


class CardFilterForm(forms.Form):
    q = forms.CharField(required=False, label="Zoeken")
    status = forms.ChoiceField(
        required=False, choices=[("", "Alle statussen"), *CardStatus.choices]
    )
    set_name = forms.CharField(required=False, label="Set")
    year = forms.IntegerField(required=False, label="Jaar")

    def apply(self, qs):
        if not self.is_valid():
            return qs
        data = self.cleaned_data
        qs = qs.search(data.get("q"))
        if data.get("status"):
            qs = qs.filter(status=data["status"])
        if data.get("set_name"):
            qs = qs.filter(set_name__icontains=data["set_name"])
        if data.get("year"):
            qs = qs.filter(year=data["year"])
        return qs


IMAGE_ACCEPT = "image/jpeg,image/png,image/webp"


class MultipleImageInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleImageInput(attrs={"accept": IMAGE_ACCEPT}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        if isinstance(data, (list, tuple)):
            return [single(d, initial) for d in data]
        return [single(data, initial)]


class PhotoUploadForm(forms.Form):
    """Alleen de vorm wordt hier gecontroleerd; type, grootte en afmetingen
    controleert photos.process_image op basis van de inhoud."""

    files = MultipleFileField(label="Foto's")
    label = forms.ChoiceField(label="Soort", choices=PhotoLabel.choices, initial=PhotoLabel.FRONT)


class PhotoReplaceForm(forms.Form):
    file = forms.FileField(
        label="Nieuwe foto", widget=forms.ClearableFileInput(attrs={"accept": IMAGE_ACCEPT})
    )


class PhotoLabelForm(forms.Form):
    label = forms.ChoiceField(choices=PhotoLabel.choices)


class StaleThresholdForm(forms.ModelForm):
    email = forms.EmailField(label="E-mailadres voor het overzicht", required=False)

    class Meta:
        model = StaleThreshold
        fields = ["warning_days", "action_days", "critical_days", "price_drop_percentage", "weekly_email"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].initial = self.instance.user.email

    def save(self, commit=True):
        obj = super().save(commit)
        user = obj.user
        user.email = self.cleaned_data.get("email", "")
        if commit:
            user.save(update_fields=["email"])
        return obj

    def clean(self):
        cleaned = super().clean()
        w, a, c = (cleaned.get(k) for k in ("warning_days", "action_days", "critical_days"))
        if None not in (w, a, c) and not (0 < w < a < c):
            raise forms.ValidationError("De drempels moeten oplopen: waarschuwing < actie < kritiek.")
        if cleaned.get("weekly_email") and not cleaned.get("email"):
            self.add_error("email", "Vul een e-mailadres in om het wekelijkse overzicht te ontvangen.")
        pct = cleaned.get("price_drop_percentage")
        if pct is not None and not (0 < pct < 100):
            self.add_error("price_drop_percentage", "Kies een percentage tussen 0 en 100.")
        return cleaned


class PinForm(forms.Form):
    held_until = forms.DateField(label="Vastzetten tot", widget=DateInput)

    def __init__(self, *args, today=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.today = today or timezone.localdate()

    def clean_held_until(self):
        value = self.cleaned_data["held_until"]
        if value <= self.today:
            raise forms.ValidationError("Kies een datum na vandaag.")
        return value


class PriceDropForm(forms.Form):
    percentage = forms.DecimalField(
        label="Verlagen met %", min_value=Decimal("0.1"), max_value=Decimal("90"), decimal_places=1
    )


class CsvUploadForm(forms.Form):
    file = forms.FileField(label="CSV-bestand")

    MAX_BYTES = 2 * 1024 * 1024

    def clean_file(self):
        f = self.cleaned_data["file"]
        if f.size > self.MAX_BYTES:
            raise forms.ValidationError("Bestand is groter dan 2 MB.")
        return f


class CsvMappingForm(forms.Form):
    """Eén keuzeveld per importveld; de keuzes zijn de CSV-kolommen."""

    def __init__(self, headers, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [("", "— niet importeren —")] + [(h, h) for h in headers]
        for name, label in IMPORT_FIELDS.items():
            self.fields[name] = forms.ChoiceField(
                label=label + (" *" if name in REQUIRED_FIELDS else ""),
                choices=choices,
                required=name in REQUIRED_FIELDS,
            )

    def mapping(self):
        return {k: v for k, v in self.cleaned_data.items() if v}
