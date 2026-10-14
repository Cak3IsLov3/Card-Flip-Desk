"""Send the weekly stale-inventory digest.

    python manage.py send_stale_digest            # normal run, from the scheduler
    python manage.py send_stale_digest --dry-run  # show who would get one
    python manage.py send_stale_digest --today 2026-10-19 --force

Users get at most one digest per 7 days (unless --force), and nothing when
there is nothing to report.
"""

from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from inventory.digest import send_digests


class Command(BaseCommand):
    help = "Send the weekly stale-inventory email digest."

    def add_arguments(self, parser):
        parser.add_argument("--today", help="Pretend it is this date (YYYY-MM-DD).")
        parser.add_argument("--force", action="store_true", help="Ignore the 7-day rule.")
        parser.add_argument("--dry-run", action="store_true", help="Do not send anything.")

    def handle(self, *args, today=None, force=False, dry_run=False, **options):
        try:
            day = date.fromisoformat(today) if today else timezone.localdate()
        except ValueError:
            raise CommandError("--today must be YYYY-MM-DD.") from None

        result = send_digests(day, force=force, dry_run=dry_run)
        verb = "Would send to" if dry_run else "Sent to"
        self.stdout.write(f"{verb}: {', '.join(result.sent) or 'nobody'}")
        if result.skipped_nothing_to_report:
            self.stdout.write(f"Nothing to report: {', '.join(result.skipped_nothing_to_report)}")
        if result.skipped_recently_sent:
            self.stdout.write(f"Already sent this week: {', '.join(result.skipped_recently_sent)}")
