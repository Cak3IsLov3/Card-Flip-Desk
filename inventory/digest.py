"""Wekelijks overzicht van oude voorraad per e-mail.

Los van de planner: `send_digests(today=...)` doet het werk, het
management-command `send_stale_digest` roept het aan, en een cronjob of de
Windows Taakplanner roept het command aan.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from . import aging
from .models import StaleThreshold

MIN_DAYS_BETWEEN_DIGESTS = 7


@dataclass
class DigestResult:
    sent: list[str] = field(default_factory=list)
    skipped_nothing_to_report: list[str] = field(default_factory=list)
    skipped_recently_sent: list[str] = field(default_factory=list)


def build_message(user, today: date) -> EmailMultiAlternatives | None:
    """Het bericht voor één gebruiker, of None als er niets te melden is."""
    thresholds = StaleThreshold.for_user(user)
    summary = aging.AttentionSummary(aging.stale_items(user, today, thresholds))
    if not summary.items:
        return None
    context = {
        "user": user,
        "summary": summary,
        "thresholds": thresholds,
        "today": today,
        "site_url": settings.SITE_URL.rstrip("/"),
    }
    n = len(summary.items)
    subject = f"Card Flip Desk: {n} kaart{'en' if n != 1 else ''} vragen aandacht"
    message = EmailMultiAlternatives(
        subject=subject,
        body=render_to_string("inventory/email/digest.txt", context),
        to=[user.email],
    )
    message.attach_alternative(render_to_string("inventory/email/digest.html", context), "text/html")
    return message


def send_digests(today: date, *, force: bool = False, dry_run: bool = False) -> DigestResult:
    result = DigestResult()
    users = (
        get_user_model()
        .objects.filter(is_active=True, stale_threshold__weekly_email=True)
        .exclude(email="")
        .select_related("stale_threshold")
    )
    for user in users:
        thresholds = user.stale_threshold
        last = thresholds.last_digest_sent_on
        if not force and last and today - last < timedelta(days=MIN_DAYS_BETWEEN_DIGESTS):
            result.skipped_recently_sent.append(user.username)
            continue
        message = build_message(user, today)
        if message is None:
            result.skipped_nothing_to_report.append(user.username)
            continue
        if not dry_run:
            message.send()
            thresholds.last_digest_sent_on = today
            thresholds.save(update_fields=["last_digest_sent_on"])
        result.sent.append(user.username)
    return result
