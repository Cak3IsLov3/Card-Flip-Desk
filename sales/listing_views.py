from django.contrib import messages
from django.core.exceptions import ValidationError
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET

from finance.calculator import CostInput, calculate
from finance.forms import money_field
from finance.models import DEFAULT_CATEGORY
from inventory.models import Card, CardStatus

from . import listing_generator as gen
from .forms import ListingDraftForm, ListingTemplateForm
from .models import Listing, ListingStatus, ListingTemplate
from .services import NoFeeProfile, fees_for

DEFAULT_TEMPLATE = "default"


def _patterns(request, key):
    """(key, title pattern, description pattern) for the chosen template."""
    if key and key != DEFAULT_TEMPLATE:
        tpl = get_object_or_404(ListingTemplate, pk=key, user=request.user)
        return str(tpl.pk), tpl.title_pattern, tpl.description_pattern
    return DEFAULT_TEMPLATE, gen.DEFAULT_TITLE_PATTERN, gen.DEFAULT_DESCRIPTION_PATTERN


def _open_listing(card):
    return (
        card.listings.filter(status__in=[ListingStatus.DRAFT, ListingStatus.ACTIVE])
        .order_by("-id")
        .first()
    )


def profit_preview(user, card, price):
    """Profit at an asking price, using today's fee profile."""
    if price is None:
        return None
    try:
        fees = fees_for(user, DEFAULT_CATEGORY, timezone.localdate())
    except NoFeeProfile:
        return None
    return calculate(CostInput(sale_price=price, purchase_cost=card.total_cost), fees)


@login_required
def listing_generator(request, card_pk):
    card = get_object_or_404(Card, pk=card_pk, owner=request.user)
    if card.status == CardStatus.SOLD:
        messages.info(request, "This card has already been sold.")
        return redirect("inventory:card_detail", pk=card.pk)

    listing = _open_listing(card)
    template_key, title_pattern, description_pattern = _patterns(request, request.GET.get("template"))
    generated = gen.generate(card, title_pattern, description_pattern)

    showing_saved = False
    if request.method == "POST":
        form = ListingDraftForm(request.POST)
        if form.is_valid():
            listing = _save(card, listing, form.cleaned_data, activate="activate" in request.POST)
            if listing.status == ListingStatus.ACTIVE:
                messages.success(request, "Listing saved and marked as active.")
            else:
                messages.success(request, "Draft saved.")
            return redirect("sales:listing_generator", card_pk=card.pk)
    else:
        regenerate = "template" in request.GET or listing is None
        showing_saved = not regenerate
        initial = {
            "title": generated.title if regenerate else listing.title,
            "description": generated.description if regenerate else listing.description,
            "asking_price": listing.asking_price if listing else None,
        }
        form = ListingDraftForm(initial=initial)

    context = {
        "card": card,
        "listing": listing,
        "form": form,
        "generated": generated,
        "template_key": template_key,
        "showing_saved": showing_saved,
        "templates": ListingTemplate.objects.filter(user=request.user),
        "photos": sorted(card.photos.all(), key=lambda p: (not p.is_main, p.position, p.id)),
        "title_max": gen.TITLE_MAX_LENGTH,
        "preview": profit_preview(request.user, card, form.initial.get("asking_price")),
    }
    if request.htmx and request.method == "GET":
        return render(request, "sales/_listing_form.html", context)
    return render(request, "sales/listing_generator.html", context)


@transaction.atomic
def _save(card, listing, data, *, activate):
    if listing is None:
        listing = Listing(card=card)
    listing.title = data["title"]
    listing.description = data["description"]
    listing.asking_price = data["asking_price"]
    if activate and listing.status != ListingStatus.ACTIVE:
        listing.status = ListingStatus.ACTIVE
        listing.listed_at = timezone.now()
        card.status = CardStatus.FOR_SALE
        card.listed_since = card.listed_since or timezone.localdate()
        card.save(update_fields=["status", "listed_since", "updated_at"])
    listing.save()
    return listing


@login_required
@require_GET
def listing_profit(request, card_pk):
    card = get_object_or_404(Card, pk=card_pk, owner=request.user)
    field = money_field("Asking price")
    try:
        price = field.clean(request.GET.get("asking_price") or None)
    except ValidationError:
        price = None
    return render(request, "sales/_listing_profit.html", {"preview": profit_preview(request.user, card, price)})


@login_required
def template_list(request):
    form = ListingTemplateForm(
        request.POST or None,
        user=request.user,
        initial={
            "title_pattern": gen.DEFAULT_TITLE_PATTERN,
            "description_pattern": gen.DEFAULT_DESCRIPTION_PATTERN,
        },
    )
    if request.method == "POST" and form.is_valid():
        tpl = form.save(commit=False)
        tpl.user = request.user
        tpl.save()
        messages.success(request, f"Template saved: {tpl}")
        return redirect("sales:template_list")
    return render(
        request,
        "sales/templates.html",
        {
            "form": form,
            "templates": ListingTemplate.objects.filter(user=request.user),
            "placeholders": gen.PLACEHOLDERS,
        },
    )


@login_required
def template_edit(request, pk):
    tpl = get_object_or_404(ListingTemplate, pk=pk, user=request.user)
    form = ListingTemplateForm(request.POST or None, instance=tpl, user=request.user)
    if request.method == "POST":
        if "delete" in request.POST:
            tpl.delete()
            messages.success(request, "Template deleted.")
            return redirect("sales:template_list")
        if form.is_valid():
            form.save()
            messages.success(request, "Template updated.")
            return redirect("sales:template_list")
    return render(
        request, "sales/template_edit.html", {"form": form, "template": tpl, "placeholders": gen.PLACEHOLDERS}
    )
