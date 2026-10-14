from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from . import photos as photo_service
from .forms import PhotoLabelForm, PhotoReplaceForm, PhotoUploadForm
from .models import Card, CardPhoto, PhotoLabel


def _own_photo(request, pk):
    return get_object_or_404(CardPhoto.objects.select_related("card"), pk=pk, card__owner=request.user)


def photo_panel_context(card, errors=None, upload_form=None):
    photos = list(card.photos.all())
    return {
        "card": card,
        "photos": photos,
        "photo_errors": errors or [],
        "photo_checklist": photo_service.photo_checklist(card, photos),
        "upload_form": upload_form or PhotoUploadForm(),
        "can_add_photos": len(photos) < settings.PHOTOS_PER_CARD,
        "photo_limit": settings.PHOTOS_PER_CARD,
        "label_choices": PhotoLabel.choices,
    }


def _respond(request, card, errors=None, success=None, upload_form=None):
    if request.htmx:
        return render(
            request, "inventory/_photo_panel.html", photo_panel_context(card, errors, upload_form)
        )
    for e in errors or []:
        messages.error(request, e)
    if success and not errors:
        messages.success(request, success)
    return redirect("inventory:card_detail", pk=card.pk)


@login_required
@require_POST
def photo_upload(request, card_pk):
    card = get_object_or_404(Card, pk=card_pk, owner=request.user)
    form = PhotoUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        errors = [e for errs in form.errors.values() for e in errs]
        return _respond(request, card, errors, upload_form=form)
    try:
        added = photo_service.add_photos(card, form.cleaned_data["files"], form.cleaned_data["label"])
    except photo_service.PhotoError as exc:
        return _respond(request, card, exc.messages)
    return _respond(request, card, success=f"{len(added)} foto('s) toegevoegd.")


@login_required
@require_GET
def photo_file(request, pk, kind):
    photo = _own_photo(request, pk)
    field = photo.thumbnail if kind == "thumb" else photo.image
    try:
        handle = field.open("rb")
    except FileNotFoundError:
        raise Http404 from None
    response = FileResponse(handle, content_type=photo.content_type)
    # Privé: geen gedeelde caches (proxy/CDN) laten bewaren.
    response["Cache-Control"] = "private, max-age=3600"
    return response


@login_required
@require_POST
def photo_set_main(request, pk):
    photo = _own_photo(request, pk)
    photo_service.set_main(photo)
    return _respond(request, photo.card, success="Hoofdfoto ingesteld.")


@login_required
@require_POST
def photo_move(request, pk, direction):
    photo = _own_photo(request, pk)
    photo_service.move(photo, -1 if direction == "up" else 1)
    return _respond(request, photo.card)


@login_required
@require_POST
def photo_label(request, pk):
    photo = _own_photo(request, pk)
    form = PhotoLabelForm(request.POST)
    if form.is_valid():
        photo.label = form.cleaned_data["label"]
        photo.save(update_fields=["label"])
        return _respond(request, photo.card, success="Soort bijgewerkt.")
    return _respond(request, photo.card, ["Onbekende soort foto."])


@login_required
@require_POST
def photo_replace(request, pk):
    photo = _own_photo(request, pk)
    form = PhotoReplaceForm(request.POST, request.FILES)
    if not form.is_valid():
        return _respond(request, photo.card, ["Kies een bestand om de foto te vervangen."])
    try:
        photo_service.replace_photo(photo, form.cleaned_data["file"])
    except photo_service.PhotoError as exc:
        return _respond(request, photo.card, exc.messages)
    return _respond(request, photo.card, success="Foto vervangen.")


@login_required
@require_POST
def photo_delete(request, pk):
    photo = _own_photo(request, pk)
    card = photo.card
    photo_service.delete_photo(photo)
    return _respond(request, card, success="Foto verwijderd.")
