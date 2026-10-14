"""Page in the app to view or renew your API token."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from rest_framework.authtoken.models import Token


@login_required
def api_token(request):
    if request.method == "POST":
        had_token, _ = Token.objects.filter(user=request.user).delete()
        if "create" in request.POST:
            Token.objects.create(user=request.user)
            note = " The old one no longer works." if had_token else ""
            messages.success(request, "New API token created." + note)
        else:
            messages.success(request, "API token revoked.")
        return redirect("api_token")
    token = Token.objects.filter(user=request.user).first()
    return render(request, "api/token.html", {"token": token})
