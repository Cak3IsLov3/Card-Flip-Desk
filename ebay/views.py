from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from . import oauth
from .client import EbayClient, EbayError, EbayNotConfigured
from .models import OAuthToken


@login_required
def connection(request):
    client = EbayClient()
    token = OAuthToken.objects.filter(user=request.user, provider="ebay", environment=client.environment).first()
    return render(
        request,
        "ebay/connection.html",
        {
            "client": client,
            "token": token,
            "can_connect": client.configured and bool(settings.EBAY_RUNAME),
            "calls_today": client.calls_today(),
            "budget": settings.EBAY_DAILY_CALL_BUDGET,
            "marketplace": settings.EBAY_MARKETPLACE_ID,
        },
    )


@login_required
@require_POST
def connect(request):
    try:
        url = oauth.authorize_url(EbayClient(), oauth.new_state(request.session))
    except EbayNotConfigured as exc:
        messages.error(request, str(exc))
        return redirect("ebay:connection")
    return redirect(url)


@login_required
def callback(request):
    """Accept-URL van de RuName. eBay stuurt `code` en onze `state` terug."""
    if not oauth.pop_state_matches(request.session, request.GET.get("state")):
        messages.error(request, "Koppeling afgebroken: ongeldige of verlopen state. Probeer het opnieuw.")
        return redirect("ebay:connection")
    code = request.GET.get("code")
    if not code:
        messages.error(request, "Je hebt de koppeling met eBay niet goedgekeurd.")
        return redirect("ebay:connection")
    try:
        oauth.exchange_code(request.user, code)
    except EbayError as exc:
        messages.error(request, f"Koppelen mislukt: {exc}")
    else:
        messages.success(request, "eBay-account gekoppeld.")
    return redirect("ebay:connection")


@login_required
@require_POST
def disconnect(request):
    OAuthToken.objects.filter(user=request.user, provider="ebay").delete()
    messages.success(request, "eBay-koppeling verwijderd. Trek de toegang ook in via je eBay-account als je wilt.")
    return redirect("ebay:connection")
