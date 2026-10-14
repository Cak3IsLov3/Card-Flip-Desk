"""What a new account starts with: a fee profile and shipping methods.

Both are for a private seller on eBay.de who ships within Germany. Users can
edit or delete everything; these are only sensible defaults.
"""

from datetime import date
from decimal import Decimal as D

from .models import DEFAULT_CATEGORY, FeeProfile, ShippingMethod

# Domestic sales by private sellers in Germany carry no final value fee and no
# per-order fee (shipping abroad yourself adds 5%).
STARTER_FEES = {"commission_percentage": D("0.00"), "fixed_fee": D("0.00"), "payment_percentage": D("0.00")}

# Deutsche Post / DHL private customer prices (dhl.de and deutschepost.de, 2026).
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


def create_starter_costs(user, valid_from=None):
    """Give `user` the starter fee profile and shipping methods."""
    FeeProfile.objects.create(
        user=user, category=DEFAULT_CATEGORY, valid_from=valid_from or date.today(), **STARTER_FEES
    )
    ShippingMethod.objects.bulk_create(
        ShippingMethod(user=user, name=name, cost=D(cost), note=note) for name, cost, note in STARTER_SHIPPING
    )
