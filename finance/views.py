from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from inventory.models import Card

from .calculator import CostInput, calculate, required_price
from .forms import CalculatorForm, FeeProfileForm
from .models import FeeProfile


@login_required
def calculator(request):
    initial = {"mode": CalculatorForm.MODE_FORWARD}
    card_id = request.GET.get("card")
    if card_id:
        card = get_object_or_404(Card, pk=card_id, owner=request.user)
        initial["purchase_cost"] = card.total_cost

    form = CalculatorForm(request.user, request.POST or None, initial=initial)
    context = {"form": form, "has_profiles": FeeProfile.objects.filter(user=request.user).exists()}

    if request.method == "POST" and form.is_valid():
        context.update(_compute(form.cleaned_data))

    if request.htmx:
        return render(request, "finance/_calculator_result.html", context)
    return render(request, "finance/calculator.html", context)


def _compute(data):
    fees = data["fee_profile"].to_fees()
    costs = {k: data[k] for k in ("shipping_income", "shipping_cost", "packaging_cost", "purchase_cost")}
    if data["mode"] == CalculatorForm.MODE_REVERSE:
        try:
            price = required_price(data["target_profit"], fees, **costs)
        except ValueError as exc:
            return {"error": str(exc)}
        return {"required_price": price, "result": calculate(CostInput(price, **costs), fees)}
    return {"result": calculate(CostInput(data["sale_price"], **costs), fees)}


@login_required
def fee_profile_list(request):
    form = FeeProfileForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        profile = form.save(commit=False)
        profile.user = request.user
        profile.save()
        messages.success(request, f"Fee profile saved: {profile}")
        return redirect("finance:fee_profiles")
    return render(
        request,
        "finance/fee_profiles.html",
        {"form": form, "profiles": FeeProfile.objects.filter(user=request.user)},
    )


@login_required
def fee_profile_edit(request, pk):
    profile = get_object_or_404(FeeProfile, pk=pk, user=request.user)
    form = FeeProfileForm(request.POST or None, instance=profile)
    if request.method == "POST":
        if "delete" in request.POST:
            profile.delete()
            messages.success(request, "Fee profile deleted.")
            return redirect("finance:fee_profiles")
        if form.is_valid():
            form.save()
            messages.success(request, "Fee profile updated.")
            return redirect("finance:fee_profiles")
    return render(request, "finance/fee_profile_edit.html", {"form": form, "profile": profile})
