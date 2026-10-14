"""Verstuurt het wekelijkse overzicht van oude voorraad.

    python manage.py send_stale_digest            # normaal, vanuit de planner
    python manage.py send_stale_digest --dry-run  # laat zien wie iets zou krijgen
    python manage.py send_stale_digest --today 2026-10-19 --force

Gebruikers krijgen hooguit één overzicht per 7 dagen (tenzij --force), en
niets als er niets te melden is.
"""

from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from inventory.digest import send_digests


class Command(BaseCommand):
    help = "Verstuurt het wekelijkse e-mailoverzicht van oude voorraad."

    def add_arguments(self, parser):
        parser.add_argument("--today", help="Doe alsof het deze datum is (JJJJ-MM-DD).")
        parser.add_argument("--force", action="store_true", help="Negeer de 7-dagenregel.")
        parser.add_argument("--dry-run", action="store_true", help="Niets versturen.")

    def handle(self, *args, today=None, force=False, dry_run=False, **options):
        try:
            day = date.fromisoformat(today) if today else timezone.localdate()
        except ValueError:
            raise CommandError("--today moet JJJJ-MM-DD zijn.") from None

        result = send_digests(day, force=force, dry_run=dry_run)
        verb = "Zou versturen naar" if dry_run else "Verstuurd naar"
        self.stdout.write(f"{verb}: {', '.join(result.sent) or 'niemand'}")
        if result.skipped_nothing_to_report:
            self.stdout.write(f"Niets te melden: {', '.join(result.skipped_nothing_to_report)}")
        if result.skipped_recently_sent:
            self.stdout.write(f"Deze week al gehad: {', '.join(result.skipped_recently_sent)}")
