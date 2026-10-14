"""Create a demo account with sample cards, for local development only.

    python manage.py seed_demo
"""

import io
from datetime import date, timedelta
from decimal import Decimal as D

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from PIL import Image, ImageDraw, ImageFont

from finance.models import DEFAULT_CATEGORY, FeeProfile
from inventory import photos
from inventory.models import Card, CardStatus, PhotoLabel, Purchase
from sales.models import Listing, ListingStatus
from sales.services import register_sale

DEMO_USERNAME = "demo"
DEMO_PASSWORD = "demo-cards-2026"  # local only; never use in production

CARDS = [
    ("Erling Haaland", "Soccer", "Topps Chrome UCL", 2023, "15", "base", "Near Mint", "2.50"),
    ("Jude Bellingham", "Soccer", "Topps Chrome UCL", 2023, "50", "parallel", "Near Mint", "6.00"),
    ("Lamine Yamal", "Soccer", "Topps Chrome", 2024, "1", "rookie", "Mint", "12.00"),
    ("Bukayo Saka", "Soccer", "Panini Prizm Premier League", 2022, "88", "base", "Excellent", "0.80"),
    ("Victor Wembanyama", "Basketball", "Panini Prizm", 2023, "136", "rookie", "Near Mint", "25.00"),
    ("Max Verstappen", "F1", "Topps Chrome F1", 2024, "1", "base", "Near Mint", "3.00"),
]


# player, set, year, cost, listed (days ago), sold (days ago), price, country
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


SET_COLOURS = {
    "Topps Chrome UCL": ("#1b3a8a", "#8fb3ff"),
    "Topps Chrome": ("#5b1e86", "#d6b4ff"),
    "Panini Prizm": ("#8a1b1b", "#ffb0a8"),
    "Panini Prizm Premier League": ("#11624a", "#9ee6c8"),
    "Topps Chrome F1": ("#202020", "#ff5a36"),
}


def card_image(card, side):
    """A simple, recognisable card as a stand-in for real photos."""
    dark, light = SET_COLOURS.get(card.set_name, ("#333333", "#cccccc"))
    img = Image.new("RGB", (500, 700), dark if side == "front" else "#e9e4d8")
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((18, 18, 482, 682), radius=22, outline=light, width=8)
    big, small = ImageFont.load_default(size=40), ImageFont.load_default(size=26)
    if side == "front":
        draw.rectangle((50, 70, 450, 520), fill=light)
        draw.text((250, 295), card.player.split()[-1].upper(), font=big, fill=dark, anchor="mm")
        draw.text((250, 580), card.player, font=small, fill="#ffffff", anchor="mm")
        draw.text((250, 625), f"{card.year} {card.set_name}", font=small, fill=light, anchor="mm")
    else:
        draw.text((250, 120), f"#{card.card_number or '-'}", font=big, fill="#222222", anchor="mm")
        for i, line in enumerate([card.player, card.set_name, str(card.year), card.get_variant_display()]):
            draw.text((250, 230 + i * 60), line, font=small, fill="#333333", anchor="mm")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return SimpleUploadedFile(f"{side}.jpg", buf.getvalue(), content_type="image/jpeg")


class Command(BaseCommand):
    help = "Create a demo user with sample data (DEBUG only)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo only runs with DEBUG enabled.")
        User = get_user_model()
        user, created = User.objects.get_or_create(username=DEMO_USERNAME)
        user.set_password(DEMO_PASSWORD)
        user.email = "demo@example.com"
        user.save()
        if not created:
            user.cards.all().delete()
            user.fee_profiles.all().delete()

        FeeProfile.objects.create(
            user=user,
            category=DEFAULT_CATEGORY,
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
        # Each stale level once: action with an asking price (and a loss when
        # lowered), warning, and critical with a bundle opportunity.
        bellingham = Card.objects.get(owner=user, player="Jude Bellingham")
        bellingham.listed_since = today - timedelta(days=65)
        bellingham.save()
        Listing.objects.create(card=bellingham, title=str(bellingham), asking_price=D("7.99"),
                               status=ListingStatus.ACTIVE)
        verstappen = Card.objects.get(owner=user, player="Max Verstappen")
        verstappen.listed_since = today - timedelta(days=35)
        verstappen.save()
        Listing.objects.create(card=verstappen, title=str(verstappen), asking_price=D("6.50"),
                               status=ListingStatus.ACTIVE)
        perez = Card.objects.create(
            owner=user, player="Sergio Pérez", sport="F1", set_name="Topps Chrome F1", year=2024,
            card_number="11", condition="Near Mint",
        )
        Purchase.objects.create(card=perez, price=D("1.50"), date=today - timedelta(days=120))

        register_sale(
            Card.objects.get(owner=user, player="Bukayo Saka"),
            sale_price=D("4.99"), shipping_income=D("1.95"), shipping_cost=D("1.45"),
            packaging_cost=D("0.25"), sold_at=today - timedelta(days=5), buyer_country="DE",
        )

        # Sales spread over the past year, for the dashboard.
        for player, set_name, year, cost, listed_ago, sold_ago, price, country in SOLD:
            card = Card.objects.create(
                owner=user, player=player, sport="Soccer", set_name=set_name, year=year,
                variant="base", condition="Near Mint", status=CardStatus.FOR_SALE,
                listed_since=today - timedelta(days=listed_ago),
            )
            Purchase.objects.create(
                card=card, price=D(cost), shipping_in=D("0.50"),
                date=today - timedelta(days=listed_ago + 7), source="Card show",
            )
            register_sale(
                card, sale_price=D(price), shipping_income=D("1.95"), shipping_cost=D("1.45"),
                packaging_cost=D("0.25"), sold_at=today - timedelta(days=sold_ago),
                buyer_country=country,
            )
        # Photos: most cards get a front and back; Verstappen only a front (so
        # the photo checklist has something to report), Pérez none.
        for card in Card.objects.filter(owner=user).exclude(player="Sergio Pérez"):
            photos.add_photos(card, [card_image(card, "front")], PhotoLabel.FRONT)
            if card.player != "Max Verstappen":
                photos.add_photos(card, [card_image(card, "back")], PhotoLabel.BACK)

        self.stdout.write(self.style.SUCCESS(f"Demo account '{DEMO_USERNAME}' is ready."))
