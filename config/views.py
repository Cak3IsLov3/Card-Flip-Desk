from decimal import Decimal

from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.db import connection
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from finance.models import DEFAULT_CATEGORY, FeeProfile


@never_cache
@require_GET
def health(request):
    """Liveness check for Docker: the app is up and the database answers.

    Deliberately reveals nothing else (no versions, no counts).
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        return HttpResponse("database unavailable", status=503, content_type="text/plain")
    return HttpResponse("ok", content_type="text/plain")


def signup(request):
    if request.user.is_authenticated:
        return redirect("inventory:card_list")
    form = UserCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        # Starter profile so the calculator works right away; rates are editable.
        FeeProfile.objects.create(
            user=user,
            category=DEFAULT_CATEGORY,
            commission_percentage=Decimal("13.25"),
            fixed_fee=Decimal("0.35"),
            payment_percentage=Decimal("0.00"),
        )
        login(request, user)
        return redirect("inventory:card_list")
    return render(request, "registration/signup.html", {"form": form})
