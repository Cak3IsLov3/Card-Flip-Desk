from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from sales.models import Sale
from sales.services import card_profit

from . import aging, csv_import
from .forms import CardFilterForm, CardForm, CsvMappingForm, CsvUploadForm, PinForm, PurchaseForm
from .models import Card, CardPhoto, CardStatus, StaleThreshold
from .photo_views import photo_panel_context

CSV_SESSION_KEY = "csv_import_content"


def _own_card(request, pk):
    # 404 in plaats van 403: een ander mag niet eens weten dat de kaart bestaat.
    return get_object_or_404(Card, pk=pk, owner=request.user)


@login_required
def card_list(request):
    cards = Card.objects.owned_by(request.user)
    filter_form = CardFilterForm(request.GET or None)
    filtered = (
        filter_form.apply(cards)
        .with_cost()
        .with_age_start()
        .prefetch_related(
            Prefetch("photos", CardPhoto.objects.filter(is_main=True), to_attr="main_photos")
        )
        .order_by("-created_at")
    )
    page = Paginator(filtered, 25).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    page.object_list = list(page.object_list)
    _annotate_age(page.object_list, request.user)

    context = {
        "page": page,
        "querystring_without_page": f"{params.urlencode()}&" if params else "",
        "filter_form": filter_form,
        "inventory_value": cards.inventory_value(),
        "per_set": cards.exclude(status=CardStatus.SOLD).count_per_set()[:8],
        "counts": {
            s.label: cards.filter(status=s.value).count() for s in CardStatus
        },
    }
    if request.htmx:
        return render(request, "inventory/_card_table.html", context)
    return render(request, "inventory/card_list.html", context)


def _annotate_age(cards, user, today=None):
    """Zet age_days en stale_level op elke kaart (voor de kleurcode)."""
    today = today or timezone.localdate()
    thresholds = StaleThreshold.for_user(user)
    for card in cards:
        pinned = card.held_until is not None and card.held_until >= today
        card.age_days = None if card.status == CardStatus.SOLD else aging.age_in_days(card.age_start, today)
        card.stale_level = None if pinned else aging.level_for(card.age_days, thresholds)
        card.is_pinned = pinned


@login_required
def card_detail(request, pk):
    card = get_object_or_404(Card.objects.with_age_start(), pk=pk, owner=request.user)
    _annotate_age([card], request.user)
    return render(
        request,
        "inventory/card_detail.html",
        {
            **photo_panel_context(card),
            "purchases": card.purchases.all(),
            "purchase_form": PurchaseForm(),
            "sale": Sale.objects.filter(listing__card=card).first(),
            "profit": card_profit(card),
            "pin_form": PinForm(initial={"held_until": timezone.localdate() + timedelta(days=30)}),
        },
    )


@login_required
def card_create(request):
    form = CardForm(request.POST or None)
    purchase_form = PurchaseForm(request.POST or None, prefix="purchase")
    purchase_form.fields["price"].required = False
    purchase_form.fields["date"].required = False

    if request.method == "POST" and form.is_valid() and purchase_form.is_valid():
        card = form.save(commit=False)
        card.owner = request.user
        card.save()
        if purchase_form.cleaned_data.get("price") is not None:
            purchase = purchase_form.save(commit=False)
            purchase.card = card
            purchase.date = purchase.date or purchase_form.fields["date"].initial
            purchase.save()
        messages.success(request, f"Kaart toegevoegd: {card}")
        return redirect("inventory:card_detail", pk=card.pk)
    return render(
        request,
        "inventory/card_form.html",
        {"form": form, "purchase_form": purchase_form, "is_new": True},
    )


@login_required
def card_update(request, pk):
    card = _own_card(request, pk)
    form = CardForm(request.POST or None, instance=card)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Kaart bijgewerkt.")
        return redirect("inventory:card_detail", pk=card.pk)
    return render(request, "inventory/card_form.html", {"form": form, "card": card})


@login_required
def card_delete(request, pk):
    card = _own_card(request, pk)
    if request.method == "POST":
        card.delete()
        messages.success(request, f"Kaart verwijderd: {card}")
        return redirect("inventory:card_list")
    return render(request, "inventory/card_confirm_delete.html", {"card": card})


@login_required
@require_POST
def purchase_add(request, pk):
    card = _own_card(request, pk)
    form = PurchaseForm(request.POST)
    if form.is_valid():
        purchase = form.save(commit=False)
        purchase.card = card
        purchase.save()
        messages.success(request, "Inkoop toegevoegd.")
    else:
        messages.error(request, "Inkoop niet opgeslagen: controleer de velden.")
    return redirect("inventory:card_detail", pk=card.pk)


@login_required
def csv_upload(request):
    form = CsvUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            content = csv_import.decode(form.cleaned_data["file"].read())
        except ValueError as exc:
            form.add_error("file", str(exc))
        else:
            if not csv_import.read_header(content):
                form.add_error("file", "Het bestand heeft geen kopregel.")
            else:
                request.session[CSV_SESSION_KEY] = content
                return redirect("inventory:csv_map")
    return render(request, "inventory/csv_upload.html", {"form": form})


@login_required
def csv_map(request):
    content = request.session.get(CSV_SESSION_KEY)
    if not content:
        return redirect("inventory:csv_upload")
    headers = csv_import.read_header(content)

    if request.method == "POST":
        form = CsvMappingForm(headers, request.POST)
        if form.is_valid():
            try:
                report = csv_import.import_cards(content, form.mapping(), request.user)
            except ValueError as exc:
                form.add_error(None, str(exc))
            else:
                del request.session[CSV_SESSION_KEY]
                return render(request, "inventory/csv_report.html", {"report": report})
    else:
        form = CsvMappingForm(headers, initial=csv_import.suggest_mapping(headers))
    preview = content.splitlines()[:6]
    return render(
        request, "inventory/csv_map.html", {"form": form, "headers": headers, "preview": preview}
    )
