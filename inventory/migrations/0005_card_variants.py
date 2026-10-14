"""Replace the single `variant` with a list of `variants`.

"base" becomes an empty list; any other value becomes a one-item list.
Going back keeps the first variant (or "base"), which loses extra variants
by necessity.
"""

from django.db import migrations, models

import inventory.models

ORDER = ["rookie", "auto", "parallel", "insert"]


def forwards(apps, schema_editor):
    Card = apps.get_model("inventory", "Card")
    for card in Card.objects.only("id", "variant"):
        card.variants = [] if card.variant in ("", "base") else [card.variant]
        card.save(update_fields=["variants"])


def backwards(apps, schema_editor):
    Card = apps.get_model("inventory", "Card")
    for card in Card.objects.only("id", "variants"):
        values = sorted(card.variants or [], key=lambda v: ORDER.index(v) if v in ORDER else len(ORDER))
        card.variant = values[0] if values else "base"
        card.save(update_fields=["variant"])


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0004_english_labels"),
    ]

    operations = [
        migrations.AddField(
            model_name="card",
            name="variants",
            field=models.JSONField(blank=True, default=list, validators=[inventory.models.validate_variants]),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.RemoveField(model_name="card", name="variant"),
    ]
