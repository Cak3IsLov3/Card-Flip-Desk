"""Batch import of cards from CSV.

Each row is validated on its own and saved in its own savepoint: a bad row
ends up in the report but does not block the others.
"""

import csv
import io
import re
from dataclasses import dataclass, field

from django import forms
from django.db import transaction
from django.utils import timezone

from .models import Card, Purchase, normalise_serial, normalise_variants, parse_condition

# Fields that can be mapped from a CSV, with their display label.
IMPORT_FIELDS = {
    "player": "Player",
    "sport": "Sport",
    "set_name": "Set",
    "year": "Year",
    "card_number": "Card number",
    "variants": "Variants",
    "parallel_name": "Parallel name",
    "parallel_serial": "Serial number",
    "insert_name": "Insert name",
    "condition": "Condition",
    "notes": "Notes",
    "purchase_price": "Purchase price",
    "shipping_in": "Inbound shipping",
    "purchase_date": "Purchase date",
    "source": "Source",
}
REQUIRED_FIELDS = {"player", "set_name", "year"}

# Common column names (English and Dutch) used to suggest a mapping.
HEADER_ALIASES = {
    "player": {"player", "speler", "naam", "name"},
    "sport": {"sport"},
    "set_name": {"set", "set_name", "serie"},
    "year": {"year", "jaar"},
    "card_number": {"card_number", "card number", "number", "no", "nummer", "kaartnummer", "#"},
    "variants": {"variant", "variants", "type"},
    "parallel_name": {"parallel", "parallel_name", "parallel name"},
    "parallel_serial": {"serial", "serial number", "parallel_serial", "numbered"},
    "insert_name": {"insert", "insert_name", "insert name"},
    "condition": {"condition", "conditie", "staat"},
    "notes": {"notes", "notities", "opmerkingen"},
    "purchase_price": {"purchase_price", "purchase price", "price", "cost", "inkoopprijs", "prijs", "inkoop"},
    "shipping_in": {"shipping_in", "shipping", "verzendkosten", "verzending"},
    "purchase_date": {"purchase_date", "purchase date", "date", "datum", "inkoopdatum"},
    "source": {"source", "bron"},
}


class CardRowForm(forms.ModelForm):
    purchase_price = forms.DecimalField(max_digits=10, decimal_places=2, required=False, min_value=0)
    shipping_in = forms.DecimalField(max_digits=10, decimal_places=2, required=False, min_value=0)
    purchase_date = forms.DateField(
        required=False, input_formats=["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"]
    )
    source = forms.CharField(max_length=120, required=False)
    # One cell can hold several variants: "Rookie, Auto", "rookie/auto", "Rookie Auto".
    variants = forms.CharField(required=False)
    # Accept "Near Mint", "NM", "nm-mt" … as well as the codes.
    condition = forms.CharField(required=False)
    parallel_serial = forms.CharField(required=False)

    def clean_condition(self):
        code = parse_condition(self.cleaned_data.get("condition"))
        if code is None:
            raise forms.ValidationError("Unknown condition; use e.g. Mint, Near Mint, Excellent, Very Good.")
        return code

    def clean_parallel_serial(self):
        try:
            return normalise_serial(self.cleaned_data.get("parallel_serial") or "")
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from None

    class Meta:
        model = Card
        fields = [
            "player", "sport", "set_name", "year", "card_number", "variants", "parallel_name",
            "parallel_serial", "insert_name", "condition", "notes",
        ]

    def clean_variants(self):
        raw = self.cleaned_data.get("variants") or ""
        try:
            # An empty cell (or "base") means a base card, not an error.
            return normalise_variants(re.split(r"[,/+|\s]+", raw))
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from None

    def clean(self):
        cleaned = super().clean()
        has_purchase_details = cleaned.get("shipping_in") or cleaned.get("purchase_date")
        if has_purchase_details and cleaned.get("purchase_price") is None:
            self.add_error("purchase_price", "Purchase price is missing while other purchase details are filled in.")
        return cleaned


@dataclass
class RowError:
    row: int  # line number in the file (header = 1)
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
    """Suggest a mapping of import field -> CSV column."""
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
    raise ValueError("File is not readable text (UTF-8 or Windows-1252).")


def import_cards(content: str, mapping: dict[str, str], owner) -> ImportReport:
    """Import cards. `mapping` maps import field -> CSV column name."""
    missing = REQUIRED_FIELDS - {k for k, v in mapping.items() if v}
    if missing:
        labels = ", ".join(IMPORT_FIELDS[m] for m in sorted(missing))
        raise ValueError(f"Required fields not mapped: {labels}.")

    report = ImportReport()
    reader = csv.DictReader(io.StringIO(content), dialect=_sniff(content))
    for row in reader:
        # line_num counts real file lines, including blank ones DictReader skips.
        line_no = reader.line_num
        if not any((v or "").strip() for v in row.values() if isinstance(v, str)):
            continue  # blank line
        data = {
            target: (row.get(column) or "").strip()
            for target, column in mapping.items()
            if column
        }
        for money_field in ("purchase_price", "shipping_in"):
            if data.get(money_field):
                # Accept "€ 4,50" as well as "4.50" (European exports use a decimal comma).
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
        except Exception as exc:  # a database error on one row must not stop the rest
            report.errors.append(RowError(line_no, {"__all__": [str(exc)]}))
            continue
        report.created += 1
    return report


def _plain_errors(form) -> dict[str, list[str]]:
    return {
        IMPORT_FIELDS.get(name, "Row"): [str(e) for e in errs]
        for name, errs in form.errors.items()
    }


class _Dialect(csv.excel):
    pass


def _sniff(content: str):
    # Pick the delimiter from the header row: it has no amounts with decimal
    # commas that would confuse csv.Sniffer.
    header = content.lstrip("﻿").splitlines()[0] if content else ""
    dialect = type("Detected", (_Dialect,), {})
    dialect.delimiter = max(";,\t", key=header.count) if header else ","
    return dialect
