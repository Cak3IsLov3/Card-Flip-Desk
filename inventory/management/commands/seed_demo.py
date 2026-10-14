"""Maakt een demo-account met voorbeeldkaarten, alleen voor lokale ontwikkeling.

    python manage.py seed_demo
"""

from datetime import date, timedelta
from decimal import Decimal as D

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from finance.models import FeeProfile
from inventory.models import Card, CardStatus, Purchase
from sales.services import register_sale

DEMO_USERNAME = "demo"
DEMO_PASSWORD = "demo-kaarten-2026"  # alleen lokaal; nooit in productie gebruiken

CARDS = [
    ("Erling Haaland", "Soccer", "Topps Chrome UCL", 2023, "15", "base", "Near Mint", "2.50"),
    ("Jude Bellingham", "Soccer", "Topps Chrome UCL", 2023, "50", "parallel", "Near Mint", "6.00"),
    ("Lamine Yamal", "Soccer", "Topps Chrome", 2024, "1", "rookie", "Mint", "12.00"),
    ("Bukayo Saka", "Soccer", "Panini Prizm Premier League", 2022, "88", "base", "Excellent", "0.80"),
    ("Victor Wembanyama", "Basketball", "Panini Prizm", 2023, "136", "rookie", "Near Mint", "25.00"),
    ("Max Verstappen", "F1", "Topps Chrome F1", 2024, "1", "base", "Near Mint", "3.00"),
]


class Command(BaseCommand):
    help = "Maakt een demo-gebruiker met voorbeelddata (alleen DEBUG)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo draait alleen met DEBUG aan.")
        User = get_user_model()
        user, created = User.objects.get_or_create(username=DEMO_USERNAME)
        user.set_password(DEMO_PASSWORD)
        user.save()
        if not created:
            user.cards.all().delete()
            user.fee_profiles.all().delete()

        FeeProfile.objects.create(
            user=user,
            category="Sportkaarten",
            commission_percentage=D("13.25"),
            fixed_fee=D("0.35"),
            valid_from=date(2024, 1, 1),
        )
        today = date.today()
        for i, (player, sport, set_name, year, nr, variant, cond, cost) in enumerate(CARDS):
            card = Card.objects.create(
                owner=user, player=player, sport=sport, set_name=set_name, year=year,
                card_number=nr, variant=variant, condition=cond,
                status=CardStatus.FOR_SALE if i % 2 else CardStatus.IN_STOCK,
                listed_since=today - timedelta(days=20 * i) if i % 2 else None,
            )
            Purchase.objects.create(
                card=card, price=D(cost), shipping_in=D("1.00"),
                date=today - timedelta(days=30 * i + 10), source="Cardmarket",
            )
        register_sale(
            Card.objects.get(owner=user, player="Bukayo Saka"),
            sale_price=D("4.99"), shipping_income=D("1.95"), shipping_cost=D("1.45"),
            packaging_cost=D("0.25"), sold_at=today - timedelta(days=5), buyer_country="DE",
        )
        self.stdout.write(self.style.SUCCESS(f"Demo-account '{DEMO_USERNAME}' klaar."))
