"""Batch-import van kaarten uit CSV.

Elke rij wordt los gevalideerd en in een eigen savepoint opgeslagen: een
foute rij komt in het rapport, maar blokkeert de rest niet.
"""

import csv
import io
from dataclasses import dataclass, field

from django import forms
from django.db import transaction
from django.utils import timezone

from .models import Card, Purchase

# Velden die in een CSV gekoppeld kunnen worden, met de Nederlandse label.
IMPORT_FIELDS = {
    "player": "Speler",
    "sport": "Sport",
    "set_name": "Set",
    "year": "Jaar",
    "card_number": "Kaartnummer",
    "variant": "Variant",
    "condition": "Conditie",
    "notes": "Notities",
    "purchase_price": "Inkoopprijs",
    "shipping_in": "Verzendkosten in",
    "purchase_date": "Inkoopdatum",
    "source": "Bron",
}
REQUIRED_FIELDS = {"player", "set_name", "year"}

# Herkenning van veelgebruikte kolomnamen voor de voorgestelde koppeling.
HEADER_ALIASES = {
    "player": {"player", "speler", "naam", "name"},
    "sport": {"sport"},
    "set_name": {"set", "set_name", "serie"},
    "year": {"year", "jaar"},
    "card_number": {"card_number", "number", "nummer", "kaartnummer", "#"},
    "variant": {"variant", "type"},
    "condition": {"condition", "conditie", "staat"},
    "notes": {"notes", "notities", "opmerkingen"},
    "purchase_price": {"purchase_price", "price", "inkoopprijs", "prijs", "inkoop"},
    "shipping_in": {"shipping_in", "verzendkosten", "verzending"},
    "purchase_date": {"purchase_date", "date", "datum", "inkoopdatum"},
    "source": {"source", "bron"},
}


class CardRowForm(forms.ModelForm):
    purchase_price = forms.DecimalField(max_digits=10, decimal_places=2, required=False, min_value=0)
    shipping_in = forms.DecimalField(max_digits=10, decimal_places=2, required=False, min_value=0)
    purchase_date = forms.DateField(
        required=False, input_formats=["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"]
    )
    source = forms.CharField(max_length=120, required=False)

    class Meta:
        model = Card
        fields = ["player", "sport", "set_name", "year", "card_number", "variant", "condition", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Een lege variant betekent "base", niet "fout".
        self.fields["variant"].required = False

    def clean_variant(self):
        return (self.cleaned_data.get("variant") or "base").lower()

    def clean(self):
        cleaned = super().clean()
        has_purchase_details = cleaned.get("shipping_in") or cleaned.get("purchase_date")
        if has_purchase_details and cleaned.get("purchase_price") is None:
            self.add_error("purchase_price", "Inkoopprijs ontbreekt bij inkoopgegevens.")
        return cleaned


@dataclass
class RowError:
    row: int  # regelnummer in het bestand (kopregel = 1)
    errors: dict[str, list[str]]


@dataclass
class ImportReport:
    created: int = 0
    errors: list[RowError] = field(default_factory=list)

    @property
    def total(self):
        return self.created + len(self.errors)


def read_header(content: str) -> list[str]:
    reader = csv.reader(io.StringIO(content), dialect=_sniff(content))
    return next(reader, [])


def suggest_mapping(headers: list[str]) -> dict[str, str]:
    """Stelt een koppeling voor van importveld -> CSV-kolom."""
    mapping = {}
    for header in headers:
        key = header.strip().lower()
        for target, aliases in HEADER_ALIASES.items():
            if key in aliases and target not in mapping:
                mapping[target] = header
    return mapping


def decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Bestand is geen leesbare tekst (UTF-8 of Windows-1252).")


def import_cards(content: str, mapping: dict[str, str], owner) -> ImportReport:
    """Importeert kaarten. `mapping` koppelt importveld -> CSV-kolomnaam."""
    missing = REQUIRED_FIELDS - {k for k, v in mapping.items() if v}
    if missing:
        labels = ", ".join(IMPORT_FIELDS[m] for m in sorted(missing))
        raise ValueError(f"Verplichte velden niet gekoppeld: {labels}.")

    report = ImportReport()
    reader = csv.DictReader(io.StringIO(content), dialect=_sniff(content))
    for row in reader:
        # line_num telt echte bestandsregels, ook de lege die DictReader overslaat.
        line_no = reader.line_num
        if not any((v or "").strip() for v in row.values() if isinstance(v, str)):
            continue  # lege regel
        data = {
            target: (row.get(column) or "").strip()
            for target, column in mapping.items()
            if column
        }
        for money_field in ("purchase_price", "shipping_in"):
            if data.get(money_field):
                data[money_field] = data[money_field].replace("€", "").replace(",", ".").strip()

        form = CardRowForm(data)
        if not form.is_valid():
            report.errors.append(RowError(line_no, _plain_errors(form)))
            continue

        try:
            with transaction.atomic():
                card = form.save(commit=False)
                card.owner = owner
                card.save()
                price = form.cleaned_data.get("purchase_price")
                if price is not None:
                    Purchase.objects.create(
                        card=card,
                        price=price,
                        shipping_in=form.cleaned_data.get("shipping_in") or 0,
                        date=form.cleaned_data.get("purchase_date") or timezone.localdate(),
                        source=form.cleaned_data.get("source") or "",
                    )
        except Exception as exc:  # databasefout op één rij mag de rest niet stoppen
            report.errors.append(RowError(line_no, {"__all__": [str(exc)]}))
            continue
        report.created += 1
    return report


def _plain_errors(form) -> dict[str, list[str]]:
    return {
        IMPORT_FIELDS.get(name, "Rij"): [str(e) for e in errs]
        for name, errs in form.errors.items()
    }


class _Dialect(csv.excel):
    pass


def _sniff(content: str):
    # Kies het scheidingsteken op basis van de kopregel: daar staan geen
    # bedragen met decimale komma's die csv.Sniffer in de war brengen.
    header = content.lstrip("﻿").splitlines()[0] if content else ""
    dialect = type("Detected", (_Dialect,), {})
    dialect.delimiter = max(";,\t", key=header.count) if header else ","
    return dialect
