from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from config.env_checks import env_problems

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
            "env_problems": env_problems(),
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
    """Accept URL of the RuName. eBay sends back `code` and our `state`."""
    if not oauth.pop_state_matches(request.session, request.GET.get("state")):
        messages.error(request, "Connection cancelled: invalid or expired state. Please try again.")
        return redirect("ebay:connection")
    code = request.GET.get("code")
    if not code:
        messages.error(request, "You did not approve the connection with eBay.")
        return redirect("ebay:connection")
    try:
        oauth.exchange_code(request.user, code)
    except EbayError as exc:
        messages.error(request, f"Connecting failed: {exc}")
    else:
        messages.success(request, "eBay account connected.")
    return redirect("ebay:connection")


@login_required
@require_POST
def disconnect(request):
    OAuthToken.objects.filter(user=request.user, provider="ebay").delete()
    messages.success(request, "eBay connection removed. You can also revoke access in your eBay account.")
    return redirect("ebay:connection")
