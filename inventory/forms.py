from django import forms
from django.utils import timezone

from .csv_import import IMPORT_FIELDS, REQUIRED_FIELDS
from .models import Card, CardStatus, PhotoLabel, Purchase


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
