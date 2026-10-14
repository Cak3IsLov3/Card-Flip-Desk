from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from . import aging
from .forms import PinForm, PriceDropForm, StaleThresholdForm
from .models import Card, CardStatus, InventoryNote, NoteKind, StaleThreshold


def _own_unsold_card(request, pk):
    return get_object_or_404(Card, pk=pk, owner=request.user, status__in=[CardStatus.IN_STOCK, CardStatus.FOR_SALE])


def _next_url(request):
    """Alleen een terugverwijzing naar onze eigen site (geen open redirect)."""
    url = request.POST.get("next", "")
    if url and url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return url
    return "inventory:attention"


def _open_listing(card):
    from sales.models import ListingStatus

    return (
        card.listings.filter(status__in=[ListingStatus.ACTIVE, ListingStatus.DRAFT]).order_by("-id").first()
    )


@login_required
def attention_list(request):
    today = timezone.localdate()
    thresholds = StaleThreshold.for_user(request.user)
    summary = aging.AttentionSummary(aging.stale_items(request.user, today, thresholds))
    return render(
        request,
        "inventory/attention.html",
        {
            "summary": summary,
            "thresholds": thresholds,
            "today": today,
            "default_pin_until": today + timedelta(days=thresholds.warning_days),
            "pinned": Card.objects.owned_by(request.user)
            .exclude(status=CardStatus.SOLD)
            .filter(held_until__gte=today)
            .order_by("held_until"),
        },
    )


@login_required
def threshold_settings(request):
    thresholds = StaleThreshold.for_user(request.user)
    form = StaleThresholdForm(request.POST or None, instance=thresholds)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Drempels opgeslagen.")
        return redirect("inventory:attention")
    return render(request, "inventory/threshold_settings.html", {"form": form})


@login_required
@require_POST
def pin_card(request, pk):
    card = _own_unsold_card(request, pk)
    form = PinForm(request.POST, today=timezone.localdate())
    if form.is_valid():
        card.held_until = form.cleaned_data["held_until"]
        card.save(update_fields=["held_until", "updated_at"])
        InventoryNote.objects.create(card=card, kind=NoteKind.PINNED, details={"until": card.held_until.isoformat()})
        messages.success(request, f"{card} vastgezet tot {card.held_until:%d-%m-%Y}.")
    else:
        messages.error(request, " ".join(form.errors["held_until"]))
    return redirect(_next_url(request))


@login_required
@require_POST
def unpin_card(request, pk):
    card = _own_unsold_card(request, pk)
    if card.held_until:
        card.held_until = None
        card.save(update_fields=["held_until", "updated_at"])
        InventoryNote.objects.create(card=card, kind=NoteKind.UNPINNED)
        messages.success(request, f"{card} is niet meer vastgezet.")
    return redirect(_next_url(request))


def _suggestion(request, card, percentage):
    from sales.services import NoFeeProfile, fees_for

    listing = _open_listing(card)
    try:
        fees = fees_for(request.user, "Sportkaarten", timezone.localdate())
    except NoFeeProfile:
        fees = None
    return listing, aging.suggest_price(
        listing.asking_price if listing else None, card.total_cost, percentage, fees
    )


@login_required
@require_GET
def price_preview(request, pk):
    card = _own_unsold_card(request, pk)
    form = PriceDropForm(request.GET)
    suggestion = None
    if form.is_valid():
        _, suggestion = _suggestion(request, card, form.cleaned_data["percentage"])
    return render(
        request, "inventory/_price_suggestion.html", {"card": card, "price": suggestion, "form": form}
    )


@login_required
@require_POST
def price_apply(request, pk):
    card = _own_unsold_card(request, pk)
    form = PriceDropForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Ongeldig percentage.")
        return redirect("inventory:attention")
    listing, suggestion = _suggestion(request, card, form.cleaned_data["percentage"])
    if suggestion is None:
        messages.error(request, "Deze kaart heeft nog geen listing met een vraagprijs.")
        return redirect("inventory:attention")
    with transaction.atomic():
        listing.asking_price = suggestion.new_price
        listing.save(update_fields=["asking_price"])
        InventoryNote.objects.create(
            card=card,
            kind=NoteKind.PRICE_LOWERED,
            details={
                "old": str(suggestion.current_price),
                "new": str(suggestion.new_price),
                "percentage": str(suggestion.percentage),
            },
        )
    msg = f"Vraagprijs verlaagd naar € {suggestion.new_price}. Vergeet niet de prijs ook op eBay aan te passen."
    if suggestion.is_loss:
        messages.warning(request, msg + " Let op: bij deze prijs maak je verlies.")
    else:
        messages.success(request, msg)
    return redirect("inventory:attention")
