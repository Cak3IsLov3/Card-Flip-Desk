from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from inventory.models import Card

from .advice import build_advice, search_query


@login_required
def card_advice(request, card_pk):
    """GET shows own history and earlier snapshots; POST fetches from eBay."""
    card = get_object_or_404(Card, pk=card_pk, owner=request.user)
    fetch = request.method == "POST"
    query = request.POST.get("q") if fetch else None
    advice = build_advice(card, query=query, fetch=fetch, today=timezone.localdate())
    context = {
        "card": card,
        "advice": advice,
        "default_query": search_query(card),
        "snapshots": card.price_snapshots.all()[:10],
        "fetched": fetch,
    }
    template = "pricing/_advice.html" if request.htmx else "pricing/card_advice.html"
    return render(request, template, context)
