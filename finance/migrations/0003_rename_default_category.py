"""Rename the default fee category from Dutch to English.

The category is also used as a lookup key (fees_for(user, DEFAULT_CATEGORY, ...)),
so existing profiles must follow the new name.
"""

from django.db import migrations

OLD, NEW = "Sportkaarten", "Sports cards"


def forwards(apps, schema_editor):
    apps.get_model("finance", "FeeProfile").objects.filter(category=OLD).update(category=NEW)


def backwards(apps, schema_editor):
    apps.get_model("finance", "FeeProfile").objects.filter(category=NEW).update(category=OLD)


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0002_english_labels"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
