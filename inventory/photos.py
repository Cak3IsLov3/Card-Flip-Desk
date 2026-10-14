"""Photos per card: validation, processing and management.

Every upload is re-encoded. That shrinks the file, creates a thumbnail and
leaves all metadata behind (EXIF including GPS location, PNG text chunks).
The contents decide the type, not the extension or the browser's Content-Type.
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
    """Validate and re-encode an upload. Raises PhotoError on problems."""
    max_bytes = settings.PHOTO_MAX_UPLOAD_BYTES
    if upload.size > max_bytes:
        raise PhotoError(f"File is larger than {max_bytes // (1024 * 1024)} MB.")

    # Step 1: read only the header; check type and dimensions before decoding,
    # so a "decompression bomb" never makes it into memory.
    upload.seek(0)
    try:
        with Image.open(upload) as probe:
            fmt = probe.format
            width, height = probe.size
            probe.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError):
        raise PhotoError("This file is not a valid image.") from None

    if fmt not in ALLOWED_FORMATS:
        raise PhotoError("Only JPEG, PNG and WebP are allowed.")
    limit = settings.PHOTO_MAX_INPUT_DIMENSION
    if width > limit or height > limit:
        raise PhotoError(f"Image is too large ({width}×{height}); the maximum is {limit}×{limit} pixels.")

    # Step 2: actually decode (verify() leaves the object unusable).
    upload.seek(0)
    try:
        with Image.open(upload) as img:
            img.load()
            icc_profile = img.info.get("icc_profile")
            # Rotate according to the EXIF orientation, because that tag is dropped below.
            img = ImageOps.exif_transpose(img)
            img = _normalise_mode(img, fmt)
    except (OSError, SyntaxError, Image.DecompressionBombError):
        raise PhotoError("The image could not be read (corrupt file?).") from None

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
    clean.info = {}  # drop exif, xmp, text chunks and comments
    options = {"format": fmt}
    if fmt in ("JPEG", "WEBP"):
        options["quality"] = 85
    if fmt in ("JPEG", "PNG"):
        options["optimize"] = True
    if icc_profile:  # a colour profile holds no personal data; keep it for correct colours
        options["icc_profile"] = icc_profile
    buf = io.BytesIO()
    clean.save(buf, **options)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Management


def add_photos(card: Card, uploads, label: str = PhotoLabel.OTHER) -> list[CardPhoto]:
    """Add photos. Everything is validated first; if one fails, nothing is
    saved."""
    uploads = list(uploads)
    existing = card.photos.count()
    limit = settings.PHOTOS_PER_CARD
    if existing + len(uploads) > limit:
        raise PhotoError(
            f"At most {limit} photos per card; there are already {existing}."
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
        # Database rolled back: the files already written should not exist either.
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
    photo.delete()  # files are removed by the post_delete signal
    if was_main:
        successor = card.photos.order_by("position", "id").first()
        if successor:
            successor.is_main = True
            successor.save(update_fields=["is_main"])


@transaction.atomic
def set_main(photo: CardPhoto) -> None:
    # Unset the old one first, otherwise the unique constraint is violated.
    photo.card.photos.filter(is_main=True).exclude(pk=photo.pk).update(is_main=False)
    if not photo.is_main:
        photo.is_main = True
        photo.save(update_fields=["is_main"])


@transaction.atomic
def move(photo: CardPhoto, direction: int) -> None:
    """Move a photo one place (-1 = earlier, +1 = later)."""
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
    """Warnings for a listing: front and back photos belong in every listing."""
    photos = list(card.photos.all()) if photos is None else photos
    if not photos:
        return ["There are no photos yet."]
    labels = {p.label for p in photos}
    warnings = []
    if PhotoLabel.FRONT not in labels:
        warnings.append("Front photo is missing.")
    if PhotoLabel.BACK not in labels:
        warnings.append("Back photo is missing.")
    return warnings


def _store_files(photo: CardPhoto, item: ProcessedImage) -> None:
    photo.width, photo.height = item.size
    name = f"upload.{item.extension}"  # upload_to turns this into a random name
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
    return getattr(upload, "name", None) or "file"


@receiver(post_delete, sender=CardPhoto)
def _remove_files(sender, instance, **kwargs):
    # Also when a card is deleted: the cascade sends this signal per photo.
    # Only after commit, so a rollback does not lose any files.
    _delete_files_on_commit([instance.image.name, instance.thumbnail.name])
