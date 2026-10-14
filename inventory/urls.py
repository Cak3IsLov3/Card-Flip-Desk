from django.urls import path

from . import attention_views, photo_views, views

app_name = "inventory"

urlpatterns = [
    path("", views.card_list, name="card_list"),
    path("nieuw/", views.card_create, name="card_create"),
    path("<int:pk>/", views.card_detail, name="card_detail"),
    path("<int:pk>/bewerken/", views.card_update, name="card_update"),
    path("<int:pk>/verwijderen/", views.card_delete, name="card_delete"),
    path("<int:pk>/inkoop/", views.purchase_add, name="purchase_add"),
    path("<int:card_pk>/fotos/", photo_views.photo_upload, name="photo_upload"),
    path("fotos/<int:pk>/bestand/", photo_views.photo_file, {"kind": "full"}, name="photo_file"),
    path("fotos/<int:pk>/thumb/", photo_views.photo_file, {"kind": "thumb"}, name="photo_thumb"),
    path("fotos/<int:pk>/hoofdfoto/", photo_views.photo_set_main, name="photo_set_main"),
    path("fotos/<int:pk>/naar-voren/", photo_views.photo_move, {"direction": "up"}, name="photo_move_up"),
    path("fotos/<int:pk>/naar-achteren/", photo_views.photo_move, {"direction": "down"}, name="photo_move_down"),
    path("fotos/<int:pk>/soort/", photo_views.photo_label, name="photo_label"),
    path("fotos/<int:pk>/vervangen/", photo_views.photo_replace, name="photo_replace"),
    path("fotos/<int:pk>/verwijderen/", photo_views.photo_delete, name="photo_delete"),
    path("aandacht/", attention_views.attention_list, name="attention"),
    path("aandacht/drempels/", attention_views.threshold_settings, name="threshold_settings"),
    path("<int:pk>/vastzetten/", attention_views.pin_card, name="pin_card"),
    path("<int:pk>/losmaken/", attention_views.unpin_card, name="unpin_card"),
    path("<int:pk>/prijsverlaging/", attention_views.price_preview, name="price_preview"),
    path("<int:pk>/prijsverlaging/toepassen/", attention_views.price_apply, name="price_apply"),
    path("import/", views.csv_upload, name="csv_upload"),
    path("import/koppelen/", views.csv_map, name="csv_map"),
]
