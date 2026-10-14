"""Give existing accounts the starter shipping methods that new accounts get."""

from decimal import Decimal

from django.conf import settings
from django.db import migrations

# Copied (not imported) so the migration keeps working if the app code changes.
STARTER_SHIPPING = [
    ("Deutsche Post Standardbrief", "0.95", "Up to 20 g and 0.5 cm thick. No tracking."),
    ("Deutsche Post Kompaktbrief", "1.10", "Up to 50 g and 1 cm thick. No tracking."),
    ("Deutsche Post Großbrief", "1.80", "Up to 500 g and 2 cm thick. No tracking."),
    ("Deutsche Post Warensendung", "2.70", "Up to 1 kg and 5 cm thick. No tracking."),
    ("Deutsche Post Maxibrief", "2.90", "Up to 1 kg and 5 cm thick. No tracking."),
    ("Großbrief + Einschreiben Einwurf", "4.15", "Großbrief with tracking (1.80 + 2.35)."),
    ("DHL Päckchen S", "4.19", "Up to 2 kg, 35 x 25 x 10 cm. No tracking, no liability."),
    ("DHL Päckchen M", "5.19", "Up to 2 kg, 60 x 30 x 15 cm. No tracking, no liability."),
    ("DHL Paket 2 kg", "6.19", "Online only, 60 x 30 x 15 cm. Tracking, liability up to €500."),
    ("DHL Paket 5 kg", "7.69", "120 x 60 x 60 cm. Tracking, liability up to €500."),
]


def forwards(apps, schema_editor):
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    ShippingMethod = apps.get_model("finance", "ShippingMethod")
    for user in User.objects.filter(shipping_methods__isnull=True):
        ShippingMethod.objects.bulk_create(
            ShippingMethod(user=user, name=name, cost=Decimal(cost), note=note)
            for name, cost, note in STARTER_SHIPPING
        )


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0004_shipping_method"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
