"""Foto's per kaart: validatie, verwerking en beheer.

Elke upload wordt opnieuw gecodeerd. Dat verkleint het bestand, maakt een
thumbnail en laat alle metadata achter (EXIF met o.a. GPS-locatie, PNG-tekst).
De inhoud bepaalt het type, niet de extensie of de Content-Type van de browser.
"""

import io
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Max
from django.db.models.signals import post_delete
from django.dispatch import receiver
from PIL import Image, ImageOps, UnidentifiedImageError

from .models import Card, CardPhoto, PhotoLabel

ALLOWED_FORMATS = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"),
}


class PhotoError(ValidationError):
    pass


@dataclass(frozen=True)
class ProcessedImage:
    extension: str
    content_type: str
    image: bytes
    thumbnail: bytes
    size: tuple[int, int]
    thumbnail_size: tuple[int, int]


def process_image(upload) -> ProcessedImage:
    """Valideert en hercodeert een upload. Gooit PhotoError bij problemen."""
    max_bytes = settings.PHOTO_MAX_UPLOAD_BYTES
    if upload.size > max_bytes:
        raise PhotoError(f"Bestand is groter dan {max_bytes // (1024 * 1024)} MB.")

    # Stap 1: alleen de kop lezen; type en afmetingen controleren vóór het
    # decoderen, zodat een "decompressiebom" nooit in het geheugen komt.
    upload.seek(0)
    try:
        with Image.open(upload) as probe:
            fmt = probe.format
            width, height = probe.size
            probe.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError):
        raise PhotoError("Dit bestand is geen geldige afbeelding.") from None

    if fmt not in ALLOWED_FORMATS:
        raise PhotoError("Alleen JPEG, PNG en WebP zijn toegestaan.")
    limit = settings.PHOTO_MAX_INPUT_DIMENSION
    if width > limit or height > limit:
        raise PhotoError(f"Afbeelding is te groot ({width}×{height}); maximaal {limit}×{limit} pixels.")

    # Stap 2: echt decoderen (verify() maakt het object onbruikbaar).
    upload.seek(0)
    try:
        with Image.open(upload) as img:
            img.load()
            icc_profile = img.info.get("icc_profile")
            # Draai volgens de EXIF-oriëntatie, want die tag verdwijnt straks.
            img = ImageOps.exif_transpose(img)
            img = _normalise_mode(img, fmt)
    except (OSError, SyntaxError, Image.DecompressionBombError):
        raise PhotoError("De afbeelding kon niet worden gelezen (beschadigd bestand?).") from None

    main = img.copy()
    main.thumbnail((settings.PHOTO_MAX_DIMENSION,) * 2, Image.Resampling.LANCZOS)
    thumb = img.copy()
    thumb.thumbnail((settings.PHOTO_THUMB_SIZE,) * 2, Image.Resampling.LANCZOS)

    ext, content_type = ALLOWED_FORMATS[fmt]
    return ProcessedImage(
        extension=ext,
        content_type=content_type,
        image=_encode(main, fmt, icc_profile),
        thumbnail=_encode(thumb, fmt, icc_profile),
        size=main.size,
        thumbnail_size=thumb.size,
    )


def _normalise_mode(img, fmt):
    if fmt == "JPEG":
        return img if img.mode in ("RGB", "L") else img.convert("RGB")
    if img.mode == "P":
        return img.convert("RGBA" if "transparency" in img.info else "RGB")
    if img.mode not in ("RGB", "RGBA", "L", "LA"):
        return img.convert("RGBA" if "A" in img.mode else "RGB")
    return img


def _encode(img, fmt, icc_profile) -> bytes:
    clean = img.copy()
    clean.info = {}  # geen exif, xmp, tekstblokken of commentaar meenemen
    options = {"format": fmt}
    if fmt in ("JPEG", "WEBP"):
        options["quality"] = 85
    if fmt in ("JPEG", "PNG"):
        options["optimize"] = True
    if icc_profile:  # kleurprofiel bevat geen persoonsgegevens; behouden voor juiste kleuren
        options["icc_profile"] = icc_profile
    buf = io.BytesIO()
    clean.save(buf, **options)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Beheer


def add_photos(card: Card, uploads, label: str = PhotoLabel.OTHER) -> list[CardPhoto]:
    """Voegt foto's toe. Alles wordt eerst gevalideerd; bij één fout wordt
    niets opgeslagen."""
    uploads = list(uploads)
    existing = card.photos.count()
    limit = settings.PHOTOS_PER_CARD
    if existing + len(uploads) > limit:
        raise PhotoError(
            f"Maximaal {limit} foto's per kaart; er zijn er al {existing}."
        )

    processed = []
    for upload in uploads:
        try:
            processed.append(process_image(upload))
        except PhotoError as exc:
            raise PhotoError(f"{_display_name(upload)}: {exc.messages[0]}") from None

    created = []
    try:
        with transaction.atomic():
            has_main = card.photos.filter(is_main=True).exists()
            position = (card.photos.aggregate(m=Max("position"))["m"] or 0) + 1
            for i, item in enumerate(processed):
                photo = CardPhoto(
                    card=card,
                    label=label,
                    position=position + i,
                    is_main=not has_main and i == 0,
                    content_type=item.content_type,
                )
                _store_files(photo, item)
                created.append(photo)
                photo.save()
    except Exception:
        # Database teruggedraaid: de al geschreven bestanden horen er ook niet te zijn.
        storage = CardPhoto._meta.get_field("image").storage
        for photo in created:
            for name in (photo.image.name, photo.thumbnail.name):
                if name:
                    storage.delete(name)
        raise
    return created


def replace_photo(photo: CardPhoto, upload) -> CardPhoto:
    item = process_image(upload)
    old_names = [photo.image.name, photo.thumbnail.name]
    with transaction.atomic():
        photo.content_type = item.content_type
        _store_files(photo, item)
        photo.save()
        _delete_files_on_commit(old_names)
    return photo


@transaction.atomic
def delete_photo(photo: CardPhoto) -> None:
    card, was_main = photo.card, photo.is_main
    photo.delete()  # bestanden gaan via het post_delete-signaal
    if was_main:
        successor = card.photos.order_by("position", "id").first()
        if successor:
            successor.is_main = True
            successor.save(update_fields=["is_main"])


@transaction.atomic
def set_main(photo: CardPhoto) -> None:
    # Eerst de oude uitzetten, anders botst de unieke constraint.
    photo.card.photos.filter(is_main=True).exclude(pk=photo.pk).update(is_main=False)
    if not photo.is_main:
        photo.is_main = True
        photo.save(update_fields=["is_main"])


@transaction.atomic
def move(photo: CardPhoto, direction: int) -> None:
    """Verschuift een foto één plek (-1 = naar voren, +1 = naar achteren)."""
    photos = list(photo.card.photos.select_for_update().order_by("position", "id"))
    index = next(i for i, p in enumerate(photos) if p.pk == photo.pk)
    target = index + direction
    if not 0 <= target < len(photos):
        return
    photos[index], photos[target] = photos[target], photos[index]
    for pos, p in enumerate(photos, start=1):
        if p.position != pos:
            p.position = pos
            p.save(update_fields=["position"])


def photo_checklist(card: Card, photos=None) -> list[str]:
    """Waarschuwingen voor een listing: voor- en achterkant horen erbij."""
    photos = list(card.photos.all()) if photos is None else photos
    if not photos:
        return ["Er zijn nog geen foto's."]
    labels = {p.label for p in photos}
    warnings = []
    if PhotoLabel.FRONT not in labels:
        warnings.append("Foto van de voorkant ontbreekt.")
    if PhotoLabel.BACK not in labels:
        warnings.append("Foto van de achterkant ontbreekt.")
    return warnings


def _store_files(photo: CardPhoto, item: ProcessedImage) -> None:
    photo.width, photo.height = item.size
    name = f"upload.{item.extension}"  # upload_to maakt hier een willekeurige naam van
    photo.image.save(name, ContentFile(item.image), save=False)
    photo.thumbnail.save(name, ContentFile(item.thumbnail), save=False)


def _delete_files_on_commit(names) -> None:
    storage = CardPhoto._meta.get_field("image").storage

    def _delete():
        for name in names:
            if name:
                storage.delete(name)

    transaction.on_commit(_delete)


def _display_name(upload) -> str:
    return getattr(upload, "name", None) or "bestand"


@receiver(post_delete, sender=CardPhoto)
def _remove_files(sender, instance, **kwargs):
    # Ook bij het verwijderen van een kaart: de cascade stuurt dit signaal
    # per foto. Pas na de commit, zodat een rollback geen bestanden kost.
    _delete_files_on_commit([instance.image.name, instance.thumbnail.name])
