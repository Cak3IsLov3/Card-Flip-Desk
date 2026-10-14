"""Rewrite saved listing templates to the English placeholder names.

The mapping is copied here (not imported) so the migration keeps working even
if the app code changes later.
"""

import re

from django.db import migrations

RENAMES = {
    "jaar": "year",
    "speler": "player",
    "nummer": "number",
    "conditie": "condition",
    "opmerkingen": "notes",
    "defecten": "defects",
}
PLACEHOLDER = re.compile(r"\{([^{}]*)\}")


def _rewrite(text, mapping):
    return PLACEHOLDER.sub(lambda m: "{" + mapping.get(m.group(1), m.group(1)) + "}", text or "")


def _convert(apps, mapping):
    Template = apps.get_model("sales", "ListingTemplate")
    for tpl in Template.objects.all():
        title = _rewrite(tpl.title_pattern, mapping)
        description = _rewrite(tpl.description_pattern, mapping)
        if (title, description) != (tpl.title_pattern, tpl.description_pattern):
            tpl.title_pattern, tpl.description_pattern = title, description
            tpl.save(update_fields=["title_pattern", "description_pattern"])


def forwards(apps, schema_editor):
    _convert(apps, RENAMES)


def backwards(apps, schema_editor):
    _convert(apps, {new: old for old, new in RENAMES.items()})


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0003_english_labels"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
