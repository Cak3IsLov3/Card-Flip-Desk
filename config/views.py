from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.db import connection
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from finance.starter import create_starter_costs


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
        # Starter fee profile and shipping methods, so the calculator works right away.
        create_starter_costs(user)
        login(request, user)
        return redirect("inventory:card_list")
    return render(request, "registration/signup.html", {"form": form})
