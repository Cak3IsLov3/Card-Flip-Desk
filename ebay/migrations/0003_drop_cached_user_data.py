"""Remove cached Browse API responses stored before they were trimmed.

They could contain seller names and other eBay user data. It is only a
cache: the next price check fetches fresh, trimmed data.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    apps.get_model("ebay", "CachedResponse").objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("ebay", "0002_english_labels"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
