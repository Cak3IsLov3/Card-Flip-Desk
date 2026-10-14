from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.formats import date_format

from inventory.models import Card, CardStatus

from .dashboard import DEFAULT_PERIOD, PERIODS, build_dashboard
from .forms import SaleForm
from .models import Sale
from .services import NoFeeProfile, register_sale


@login_required
def sale_create(request, card_pk):
    card = get_object_or_404(Card, pk=card_pk, owner=request.user)
    if card.status == CardStatus.SOLD:
        messages.info(request, "Deze kaart is al verkocht.")
        return redirect("inventory:card_detail", pk=card.pk)

    form = SaleForm(request.user, request.POST or None)
    if not form.fields["category"].choices:
        messages.warning(request, "Maak eerst een kostenprofiel aan.")
        return redirect("finance:fee_profiles")

    if request.method == "POST" and form.is_valid():
        try:
            register_sale(card, **form.cleaned_data)
        except NoFeeProfile as exc:
            form.add_error("category", str(exc))
        else:
            messages.success(request, "Verkoop geregistreerd.")
            return redirect("inventory:card_detail", pk=card.pk)
    return render(request, "sales/sale_form.html", {"form": form, "card": card})


@login_required
def dashboard(request):
    data = build_dashboard(
        request.user, today=timezone.localdate(), period=request.GET.get("periode", DEFAULT_PERIOD)
    )
    charted_sets = [s for s in data.sets if s["margin"] is not None][:12]
    # Bedragen als string: JSON kent geen Decimal en een float zou afronden.
    chart_data = {
        "months": {
            "labels": [date_format(m["month"], "b 'y") for m in data.months],
            "revenue": [str(m["revenue"]) for m in data.months],
            "profit": [str(m["profit"]) for m in data.months],
        },
        "sets": {
            "labels": [f"{s['set_name']} {s['year']}" for s in charted_sets],
            "margin": [str(s["margin"]) for s in charted_sets],
            "profit": [str(s["profit"]) for s in charted_sets],
        },
    }
    return render(
        request,
        "sales/dashboard.html",
        {"d": data, "chart_data": chart_data, "periods": PERIODS},
    )


@login_required
def sale_list(request):
    sales = (
        Sale.objects.owned_by(request.user)
        .with_profit()
        .select_related("listing__card")
        .order_by("-sold_at")
    )
    months = Sale.objects.owned_by(request.user).profit_per_month()
    return render(request, "sales/sale_list.html", {"sales": sales, "months": months})
