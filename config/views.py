from decimal import Decimal

from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import redirect, render

from finance.models import DEFAULT_CATEGORY, FeeProfile


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
