from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from inventory.models import Card

from .advice import build_advice, parse_sold_prices, search_query, sold_search_url


@login_required
def card_advice(request, card_pk):
    """GET shows own history and earlier snapshots.

    POST either fetches active listings from eBay (API) or, with
    action=sold, uses the sold prices the user pasted (no API).
    """
    card = get_object_or_404(Card, pk=card_pk, owner=request.user)
    query = request.POST.get("q") if request.method == "POST" else None
    sold = None
    if request.method == "POST" and request.POST.get("action") == "sold":
        sold = parse_sold_prices(request.POST.get("prices", ""))
    fetch = request.method == "POST" and sold is None
    advice = build_advice(card, query=query, fetch=fetch, today=timezone.localdate(), sold=sold)
    context = {
        "card": card,
        "advice": advice,
        "default_query": search_query(card),
        "sold_url": sold_search_url(advice.query),
        "sold_text": request.POST.get("prices", "") if sold is not None else "",
        "snapshots": card.price_snapshots.all()[:10],
        "fetched": fetch or sold is not None,
    }
    template = "pricing/_advice.html" if request.htmx else "pricing/card_advice.html"
    return render(request, template, context)
