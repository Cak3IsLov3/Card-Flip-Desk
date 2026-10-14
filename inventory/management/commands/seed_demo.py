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


# speler, set, jaar, inkoop, te koop sinds (dagen geleden), verkocht (dagen geleden), prijs, land
SOLD = [
    ("Kylian Mbappé", "Topps Chrome UCL", 2023, "4.00", 340, 320, "11.50", "FR"),
    ("Florian Wirtz", "Topps Chrome UCL", 2023, "2.00", 300, 260, "6.00", "DE"),
    ("Cole Palmer", "Panini Prizm Premier League", 2023, "3.50", 280, 270, "9.99", "GB"),
    ("Xavi Simons", "Topps Chrome UCL", 2023, "1.50", 250, 190, "3.49", "NL"),
    ("Phil Foden", "Panini Prizm Premier League", 2022, "6.00", 220, 150, "5.00", "GB"),
    ("Jamal Musiala", "Topps Chrome", 2024, "5.00", 160, 120, "14.00", "DE"),
    ("Pedri", "Topps Chrome", 2024, "2.50", 130, 95, "7.50", "ES"),
    ("Rodri", "Topps Chrome UCL", 2023, "3.00", 110, 60, "8.25", "ES"),
    ("Declan Rice", "Panini Prizm Premier League", 2023, "1.00", 80, 45, "4.50", "GB"),
    ("Vinícius Júnior", "Topps Chrome UCL", 2023, "8.00", 70, 30, "19.99", "BR"),
    ("Martin Ødegaard", "Panini Prizm Premier League", 2023, "2.00", 40, 12, "6.75", "NO"),
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

        # Verkopen verspreid over het afgelopen jaar, voor het dashboard.
        for player, set_name, year, cost, listed_ago, sold_ago, price, country in SOLD:
            card = Card.objects.create(
                owner=user, player=player, sport="Soccer", set_name=set_name, year=year,
                variant="base", condition="Near Mint", status=CardStatus.FOR_SALE,
                listed_since=today - timedelta(days=listed_ago),
            )
            Purchase.objects.create(
                card=card, price=D(cost), shipping_in=D("0.50"),
                date=today - timedelta(days=listed_ago + 7), source="Beurs",
            )
            register_sale(
                card, sale_price=D(price), shipping_income=D("1.95"), shipping_cost=D("1.45"),
                packaging_cost=D("0.25"), sold_at=today - timedelta(days=sold_ago),
                buyer_country=country,
            )
        self.stdout.write(self.style.SUCCESS(f"Demo-account '{DEMO_USERNAME}' klaar."))
