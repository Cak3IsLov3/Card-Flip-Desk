"""Seller Hub import: upload → map columns → confirm the card per sale → report."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from inventory import csv_import

from . import seller_hub
from .forms import SellerHubMappingForm, SellerHubOptionsForm, SellerHubUploadForm

CONTENT_KEY = "seller_hub_content"
MAPPING_KEY = "seller_hub_mapping"


@login_required
def seller_hub_upload(request):
    form = SellerHubUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            content = csv_import.decode(form.cleaned_data["file"].read())
        except ValueError as exc:
            form.add_error("file", str(exc))
        else:
            if not seller_hub.read_header(content):
                form.add_error("file", "The file has no header row.")
            else:
                request.session[CONTENT_KEY] = content
                request.session.pop(MAPPING_KEY, None)
                return redirect("sales:seller_hub_map")
    return render(request, "sales/seller_hub_upload.html", {"form": form})


@login_required
def seller_hub_map(request):
    content = request.session.get(CONTENT_KEY)
    if not content:
        return redirect("sales:seller_hub_upload")
    headers = seller_hub.read_header(content)
    if request.method == "POST":
        form = SellerHubMappingForm(headers, request.POST)
        if form.is_valid():
            request.session[MAPPING_KEY] = form.mapping()
            return redirect("sales:seller_hub_review")
    else:
        initial = request.session.get(MAPPING_KEY) or seller_hub.suggest_mapping(headers)
        form = SellerHubMappingForm(headers, initial=initial)
    index, _ = seller_hub.find_header(content)
    preview = content.splitlines()[index:index + 6]
    return render(request, "sales/seller_hub_map.html", {"form": form, "preview": preview})


@login_required
def seller_hub_review(request):
    content, mapping = request.session.get(CONTENT_KEY), request.session.get(MAPPING_KEY)
    if not content or not mapping:
        return redirect("sales:seller_hub_upload")
    try:
        rows = seller_hub.parse_rows(content, mapping)
    except ValueError as exc:
        return render(request, "sales/seller_hub_map.html", {"error": str(exc)})
    seller_hub.mark_imported(rows, request.user)
    cards = seller_hub.open_cards(request.user)
    options = SellerHubOptionsForm(request.user, request.POST or None)

    if request.method == "POST" and options.is_valid():
        # Only the user's own unsold cards can be chosen; anything else is ignored.
        by_pk = {str(c.pk): c for c in cards}
        choices = {
            row.line: by_pk[request.POST.get(f"card_{row.line}", "")]
            for row in rows
            if request.POST.get(f"card_{row.line}", "") in by_pk
        }
        report = seller_hub.import_sales(
            rows, choices, request.user,
            shipping_cost=options.cleaned_data["shipping_cost"],
            packaging_cost=options.cleaned_data["packaging_cost"],
        )
        request.session.pop(CONTENT_KEY, None)
        request.session.pop(MAPPING_KEY, None)
        return render(request, "sales/seller_hub_report.html", {"report": report})

    suggestions = seller_hub.suggest_cards(rows, cards)
    table = [(row, suggestions.get(row.line)) for row in rows]
    return render(
        request,
        "sales/seller_hub_review.html",
        {"table": table, "cards": cards, "options": options,
         "importable": sum(1 for r in rows if r.importable)},
    )
