"""Turn the free-text condition into a choice and add the parallel serial number.

Existing text is mapped to a choice where it can be recognised ("Near Mint",
"NM-MT", "ex" …). Anything else is moved to the notes, so no information is
lost, and the condition is left empty. The conversion runs before the column
is shortened, so long texts never hit the new length limit.
"""

from django.db import migrations, models

import inventory.models

# Copied (not imported) so the migration keeps working if the app code changes.
CODES = {"mint", "near_mint", "excellent", "very_good", "good", "fair", "poor"}
ALIASES = {
    "mint": "mint", "m": "mint", "mt": "mint", "gem mint": "mint",
    "near mint": "near_mint", "nm": "near_mint", "nm mt": "near_mint", "near mint or better": "near_mint",
    "excellent": "excellent", "ex": "excellent", "ex mt": "excellent",
    "very good": "very_good", "vg": "very_good", "vg ex": "very_good",
    "good": "good", "g": "good",
    "fair": "fair", "f": "fair",
    "poor": "poor", "p": "poor",
}
LABELS = {
    "mint": "Mint", "near_mint": "Near Mint", "excellent": "Excellent", "very_good": "Very Good",
    "good": "Good", "fair": "Fair", "poor": "Poor",
}


def _parse(value):
    text = " ".join("".join(c if c.isalnum() else " " for c in (value or "").lower()).split())
    if not text:
        return ""
    if text.replace(" ", "_") in CODES:
        return text.replace(" ", "_")
    return ALIASES.get(text)


def forwards(apps, schema_editor):
    Card = apps.get_model("inventory", "Card")
    for card in Card.objects.exclude(condition=""):
        code = _parse(card.condition)
        if code is None:
            note = f"Condition (before it became a choice): {card.condition}"
            card.notes = f"{card.notes}\n{note}".strip()
            code = ""
        card.condition = code
        card.save(update_fields=["condition", "notes"])


def backwards(apps, schema_editor):
    Card = apps.get_model("inventory", "Card")
    for card in Card.objects.exclude(condition=""):
        card.condition = LABELS.get(card.condition, card.condition)
        card.save(update_fields=["condition"])


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0006_card_variant_names"),
    ]

    operations = [
        migrations.AddField(
            model_name="card",
            name="parallel_serial",
            field=models.CharField(
                blank=True, max_length=20, validators=[inventory.models.validate_serial], verbose_name="serial number"
            ),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.AlterField(
            model_name="card",
            name="condition",
            field=models.CharField(
                blank=True,
                choices=[
                    ("mint", "Mint"), ("near_mint", "Near Mint"), ("excellent", "Excellent"),
                    ("very_good", "Very Good"), ("good", "Good"), ("fair", "Fair"), ("poor", "Poor"),
                ],
                max_length=20,
            ),
        ),
    ]
