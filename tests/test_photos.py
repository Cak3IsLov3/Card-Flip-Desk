import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.urls import reverse
from PIL import ExifTags, Image

from inventory import photos as svc
from inventory.models import CardPhoto, PhotoLabel


def image_bytes(fmt="JPEG", size=(800, 1100), color=(200, 30, 30), exif=None, mode="RGB"):
    buf = io.BytesIO()
    img = Image.new(mode, size, color)
    options = {"format": fmt}
    if exif is not None:
        options["exif"] = exif
    img.save(buf, **options)
    return buf.getvalue()


def upload(data, name="card.jpg", content_type="image/jpeg"):
    return SimpleUploadedFile(name, data, content_type=content_type)


def gps_exif():
    exif = Image.Exif()
    exif[ExifTags.Base.Make] = "PhoneMaker"
    exif[ExifTags.Base.Model] = "Model X"
    exif[ExifTags.Base.Orientation] = 1
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    gps[ExifTags.GPS.GPSLatitudeRef] = "N"
    gps[ExifTags.GPS.GPSLatitude] = (52.0, 22.0, 12.0)
    gps[ExifTags.GPS.GPSLongitudeRef] = "E"
    gps[ExifTags.GPS.GPSLongitude] = (4.0, 53.0, 30.0)
    return exif


def open_stored(field):
    with field.open("rb") as f:
        img = Image.open(io.BytesIO(f.read()))
        img.load()
        return img


# --- validation ---------------------------------------------------------------

@pytest.mark.parametrize("fmt, mime", [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")])
def test_valid_formats_accepted(fmt, mime):
    result = svc.process_image(upload(image_bytes(fmt)))
    assert result.content_type == mime
    assert Image.open(io.BytesIO(result.image)).format == fmt


def test_wrong_type_rejected():
    gif = image_bytes("GIF", mode="P", color=1)
    with pytest.raises(svc.PhotoError, match="JPEG, PNG and WebP"):
        svc.process_image(upload(gif, "card.gif", "image/gif"))


def test_non_image_with_jpg_extension_rejected():
    fake = upload(b"<?php echo 'not a photo'; ?>" * 20, "card.jpg", "image/jpeg")
    with pytest.raises(svc.PhotoError, match="not a valid image"):
        svc.process_image(fake)


def test_truncated_image_rejected():
    data = image_bytes("PNG", size=(400, 400))
    with pytest.raises(svc.PhotoError):
        svc.process_image(upload(data[: len(data) // 2], "card.png"))


def test_too_large_file_rejected(settings):
    settings.PHOTO_MAX_UPLOAD_BYTES = 1000
    with pytest.raises(svc.PhotoError, match="larger than"):
        svc.process_image(upload(b"x" * 1001))


def test_too_large_dimensions_rejected(settings):
    settings.PHOTO_MAX_INPUT_DIMENSION = 1000
    with pytest.raises(svc.PhotoError, match="maximum is 1000×1000"):
        svc.process_image(upload(image_bytes(size=(1001, 500))))


def test_extension_does_not_decide_type():
    # A PNG with a .jpg extension is recognised as PNG and stored as such.
    result = svc.process_image(upload(image_bytes("PNG"), "card.jpg"))
    assert result.extension == "png"


# --- processing ---------------------------------------------------------------

def test_resized_and_thumbnail_dimensions(settings):
    settings.PHOTO_MAX_DIMENSION = 1600
    settings.PHOTO_THUMB_SIZE = 300
    result = svc.process_image(upload(image_bytes(size=(2000, 2800))))
    assert result.size == (1143, 1600)
    assert result.thumbnail_size == (214, 300)
    assert Image.open(io.BytesIO(result.thumbnail)).size == (214, 300)


def test_small_image_not_enlarged():
    result = svc.process_image(upload(image_bytes(size=(200, 280))))
    assert result.size == (200, 280)
    assert result.thumbnail_size == (200, 280)


@pytest.mark.parametrize("fmt", ["JPEG", "WEBP", "PNG"])
def test_exif_is_removed(fmt):
    original = image_bytes(fmt, exif=gps_exif())
    assert Image.open(io.BytesIO(original)).getexif().get(ExifTags.Base.Make) == "PhoneMaker"

    result = svc.process_image(upload(original))
    for data in (result.image, result.thumbnail):
        cleaned = Image.open(io.BytesIO(data))
        assert len(cleaned.getexif()) == 0
        assert "exif" not in cleaned.info
        assert b"PhoneMaker" not in data


def test_exif_orientation_applied_before_stripping():
    exif = Image.Exif()
    exif[ExifTags.Base.Orientation] = 6  # rotated 90°
    result = svc.process_image(upload(image_bytes(size=(400, 300), exif=exif)))
    assert result.size == (300, 400)


def test_png_with_transparency_keeps_alpha():
    result = svc.process_image(upload(image_bytes("PNG", mode="RGBA", color=(0, 0, 0, 0)), "k.png"))
    assert Image.open(io.BytesIO(result.image)).mode == "RGBA"


def test_cmyk_jpeg_converted_to_rgb():
    result = svc.process_image(upload(image_bytes("JPEG", mode="CMYK", color=(0, 0, 0, 0))))
    assert Image.open(io.BytesIO(result.image)).mode == "RGB"


# --- management ---------------------------------------------------------------

def test_add_photos_stores_random_names_and_first_is_main(user, make_card):
    card = make_card(user)
    files = [upload(image_bytes(), "../../etc/my photo.jpg"), upload(image_bytes("PNG"), "back.png")]
    first, second = svc.add_photos(card, files, PhotoLabel.FRONT)

    assert first.is_main and not second.is_main
    assert first.position < second.position
    for photo in (first, second):
        assert photo.image.name.startswith("cards/")
        assert photo.thumbnail.name.startswith("cards/thumbs/")
        assert "my" not in photo.image.name and ".." not in photo.image.name
        assert photo.image.storage.exists(photo.image.name)
    assert second.image.name.endswith(".png")
    assert (first.width, first.height) == (800, 1100)

    stored = open_stored(first.image)
    assert len(stored.getexif()) == 0


def test_photos_have_no_public_url(user, make_card):
    photo = svc.add_photos(make_card(user), [upload(image_bytes())])[0]
    with pytest.raises(ValueError):
        _ = photo.image.url


def test_limit_of_six_photos(user, make_card, settings):
    settings.PHOTOS_PER_CARD = 6
    card = make_card(user)
    svc.add_photos(card, [upload(image_bytes()) for _ in range(5)])
    with pytest.raises(svc.PhotoError, match="At most 6"):
        svc.add_photos(card, [upload(image_bytes()), upload(image_bytes())])
    assert card.photos.count() == 5


def test_one_bad_file_saves_nothing(user, make_card, private_media):
    card = make_card(user)
    with pytest.raises(svc.PhotoError, match="fake.jpg"):
        svc.add_photos(card, [upload(image_bytes()), upload(b"fake" * 100, "fake.jpg")])
    assert card.photos.count() == 0
    assert [p for p in private_media.rglob("*") if p.is_file()] == []


def test_at_most_one_main_photo(user, make_card):
    card = make_card(user)
    a, b, c = svc.add_photos(card, [upload(image_bytes()) for _ in range(3)])
    svc.set_main(c)
    assert list(card.photos.filter(is_main=True)) == [c]
    svc.set_main(b)
    assert list(card.photos.filter(is_main=True)) == [b]

    # The database enforces it too.
    with pytest.raises(IntegrityError), transaction.atomic():
        CardPhoto.objects.filter(pk=a.pk).update(is_main=True)


def test_deleting_main_promotes_next(user, make_card, django_capture_on_commit_callbacks):
    card = make_card(user)
    a, b = svc.add_photos(card, [upload(image_bytes()), upload(image_bytes())])
    storage, name = a.image.storage, a.image.name
    with django_capture_on_commit_callbacks(execute=True):
        svc.delete_photo(a)
    b.refresh_from_db()
    assert b.is_main
    assert not storage.exists(name)


def test_move_reorders(user, make_card):
    card = make_card(user)
    a, b, c = svc.add_photos(card, [upload(image_bytes()) for _ in range(3)])
    svc.move(c, -1)
    assert list(card.photos.all()) == [a, c, b]
    svc.move(a, -1)  # already first: nothing happens
    assert list(card.photos.all()) == [a, c, b]
    svc.move(a, 1)
    assert list(card.photos.all()) == [c, a, b]


def test_replace_photo_removes_old_files(user, make_card, django_capture_on_commit_callbacks):
    card = make_card(user)
    photo = svc.add_photos(card, [upload(image_bytes())])[0]
    old = [photo.image.name, photo.thumbnail.name]
    with django_capture_on_commit_callbacks(execute=True):
        svc.replace_photo(photo, upload(image_bytes("PNG", size=(300, 420)), "new.png"))
    photo.refresh_from_db()
    assert photo.content_type == "image/png"
    assert (photo.width, photo.height) == (300, 420)
    assert photo.image.name not in old
    assert not any(photo.image.storage.exists(n) for n in old)


def test_deleting_card_deletes_files(user, make_card, django_capture_on_commit_callbacks):
    card = make_card(user)
    photos = svc.add_photos(card, [upload(image_bytes()), upload(image_bytes())])
    names = [n for p in photos for n in (p.image.name, p.thumbnail.name)]
    storage = photos[0].image.storage
    with django_capture_on_commit_callbacks(execute=True):
        card.delete()
    assert not any(storage.exists(n) for n in names)


def test_checklist(user, make_card):
    card = make_card(user)
    assert svc.photo_checklist(card) == ["There are no photos yet."]
    svc.add_photos(card, [upload(image_bytes())], PhotoLabel.FRONT)
    assert svc.photo_checklist(card) == ["Back photo is missing."]
    svc.add_photos(card, [upload(image_bytes())], PhotoLabel.BACK)
    assert svc.photo_checklist(card) == []


# --- views and access ---------------------------------------------------------

def test_upload_view_and_owner_can_fetch(user, make_card, client_for):
    card = make_card(user)
    client = client_for(user)
    resp = client.post(
        reverse("inventory:photo_upload", args=[card.pk]),
        {"files": [upload(image_bytes(exif=gps_exif()))], "label": "front"},
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 200
    assert "inventory/_photo_panel.html" in [t.name for t in resp.templates]
    photo = card.photos.get()

    for name in ("inventory:photo_file", "inventory:photo_thumb"):
        resp = client.get(reverse(name, args=[photo.pk]))
        assert resp.status_code == 200
        assert resp["Content-Type"] == "image/jpeg"
        assert "private" in resp["Cache-Control"]
        assert b"PhoneMaker" not in b"".join(resp.streaming_content)


def test_upload_view_reports_invalid_file(user, make_card, client_for):
    card = make_card(user)
    resp = client_for(user).post(
        reverse("inventory:photo_upload", args=[card.pk]),
        {"files": [upload(b"not a photo" * 50, "x.jpg")], "label": "front"},
        HTTP_HX_REQUEST="true",
    )
    assert any("not a valid image" in e for e in resp.context["photo_errors"])
    assert not card.photos.exists()


@pytest.mark.parametrize(
    "name, method",
    [
        ("inventory:photo_file", "get"),
        ("inventory:photo_thumb", "get"),
        ("inventory:photo_set_main", "post"),
        ("inventory:photo_move_up", "post"),
        ("inventory:photo_label", "post"),
        ("inventory:photo_replace", "post"),
        ("inventory:photo_delete", "post"),
    ],
)
def test_other_user_cannot_access_photos(name, method, user, other_user, make_card, client_for):
    card = make_card(user)
    photo = svc.add_photos(card, [upload(image_bytes())], PhotoLabel.FRONT)[0]
    resp = getattr(client_for(other_user), method)(reverse(name, args=[photo.pk]), {"label": "defect"})
    assert resp.status_code == 404
    photo.refresh_from_db()
    assert photo.label == PhotoLabel.FRONT


def test_other_user_cannot_upload_to_card(user, other_user, make_card, client_for):
    card = make_card(user)
    resp = client_for(other_user).post(
        reverse("inventory:photo_upload", args=[card.pk]),
        {"files": [upload(image_bytes())], "label": "front"},
    )
    assert resp.status_code == 404
    assert not card.photos.exists()


def test_anonymous_cannot_fetch_photo(client, user, make_card):
    photo = svc.add_photos(make_card(user), [upload(image_bytes())])[0]
    resp = client.get(reverse("inventory:photo_file", args=[photo.pk]))
    assert resp.status_code == 302


def test_card_list_shows_main_thumbnail_without_extra_queries(
    user, make_card, client_for, django_assert_max_num_queries
):
    for i in range(5):
        svc.add_photos(make_card(user, player=f"Player {i}"), [upload(image_bytes(size=(50, 70)))])
    client = client_for(user)
    with django_assert_max_num_queries(15):  # fixed number, independent of the number of cards
        resp = client.get(reverse("inventory:card_list"))
    assert resp.content.count(b'class="thumb-sm"') == 5
