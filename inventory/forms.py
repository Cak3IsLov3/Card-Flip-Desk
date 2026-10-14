from decimal import Decimal

from django import forms
from django.utils import timezone

from .csv_import import IMPORT_FIELDS, REQUIRED_FIELDS
from .models import Card, CardStatus, Condition, PhotoLabel, Purchase, StaleThreshold, Variant


class DateInput(forms.DateInput):
    input_type = "date"


class VariantField(forms.MultipleChoiceField):
    """Checkboxes; nothing ticked means a base card."""

    def __init__(self, **kwargs):
        kwargs.setdefault("label", "Variants")
        kwargs.setdefault("help_text", "Tick all that apply; leave empty for a base card.")
        super().__init__(
            choices=Variant.choices, required=False, widget=forms.CheckboxSelectMultiple, **kwargs
        )


class CardForm(forms.ModelForm):
    variants = VariantField()

    class Meta:
        model = Card
        fields = [
            "player", "sport", "set_name", "year", "card_number", "variants", "parallel_name",
            "parallel_serial", "insert_name", "condition", "status", "listed_since", "held_until", "notes",
        ]
        labels = {
            "parallel_name": "Which parallel?",
            "parallel_serial": "Serial number",
            "insert_name": "Which insert?",
        }
        help_texts = {
            "parallel_name": "Optional, e.g. Gold Refractor. Used in the listing title.",
            "parallel_serial": "Optional, for numbered parallels: 23/50, or /50 if you only know the print run.",
            "insert_name": "Optional, e.g. Future Stars. Used in the listing title.",
        }
        widgets = {
            "listed_since": DateInput,
            "held_until": DateInput,
            "notes": forms.Textarea(attrs={"rows": 3}),
            # card_form.js shows these only while the matching variant is ticked.
            "parallel_name": forms.TextInput(attrs={"data-show-with-variant": "parallel"}),
            "parallel_serial": forms.TextInput(
                attrs={"data-show-with-variant": "parallel", "placeholder": "23/50", "inputmode": "numeric"}
            ),
            "insert_name": forms.TextInput(attrs={"data-show-with-variant": "insert"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["condition"].choices = [("", "Not specified"), *Condition.choices]

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
    q = forms.CharField(required=False, label="Search")
    status = forms.ChoiceField(
        required=False, choices=[("", "All statuses"), *CardStatus.choices]
    )
    set_name = forms.CharField(required=False, label="Set")
    year = forms.IntegerField(required=False, label="Year")
    variant = forms.ChoiceField(
        required=False, label="Variant", choices=[("", "Any"), ("base", "Base"), *Variant.choices]
    )

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
        if data.get("variant") == "base":
            qs = qs.filter(variants=[])
        elif data.get("variant"):
            # The JSON text contains the quoted code, e.g. ["rookie", "auto"].
            qs = qs.filter(variants__icontains=f'"{data["variant"]}"')
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
    """Only the shape of the input is checked here; type, size and dimensions
    are checked by photos.process_image based on the file contents."""

    files = MultipleFileField(label="Photos")
    label = forms.ChoiceField(label="Type", choices=PhotoLabel.choices, initial=PhotoLabel.FRONT)


class PhotoReplaceForm(forms.Form):
    file = forms.FileField(
        label="New photo", widget=forms.ClearableFileInput(attrs={"accept": IMAGE_ACCEPT})
    )


class PhotoLabelForm(forms.Form):
    label = forms.ChoiceField(choices=PhotoLabel.choices)


class StaleThresholdForm(forms.ModelForm):
    email = forms.EmailField(label="Email address for the digest", required=False)

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
            raise forms.ValidationError("Thresholds must increase: warning < action < critical.")
        if cleaned.get("weekly_email") and not cleaned.get("email"):
            self.add_error("email", "Enter an email address to receive the weekly digest.")
        pct = cleaned.get("price_drop_percentage")
        if pct is not None and not (0 < pct < 100):
            self.add_error("price_drop_percentage", "Choose a percentage between 0 and 100.")
        return cleaned


class PinForm(forms.Form):
    held_until = forms.DateField(label="Pin until", widget=DateInput)

    def __init__(self, *args, today=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.today = today or timezone.localdate()

    def clean_held_until(self):
        value = self.cleaned_data["held_until"]
        if value <= self.today:
            raise forms.ValidationError("Choose a date after today.")
        return value


class PriceDropForm(forms.Form):
    percentage = forms.DecimalField(
        label="Lower by %", min_value=Decimal("0.1"), max_value=Decimal("90"), decimal_places=1
    )


class CsvUploadForm(forms.Form):
    file = forms.FileField(label="CSV file")

    MAX_BYTES = 2 * 1024 * 1024

    def clean_file(self):
        f = self.cleaned_data["file"]
        if f.size > self.MAX_BYTES:
            raise forms.ValidationError("File is larger than 2 MB.")
        return f


class CsvMappingForm(forms.Form):
    """One choice field per import field; the choices are the CSV columns."""

    def __init__(self, headers, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [("", "— do not import —")] + [(h, h) for h in headers]
        for name, label in IMPORT_FIELDS.items():
            self.fields[name] = forms.ChoiceField(
                label=label + (" *" if name in REQUIRED_FIELDS else ""),
                choices=choices,
                required=name in REQUIRED_FIELDS,
            )

    def mapping(self):
        return {k: v for k, v in self.cleaned_data.items() if v}
