from django.urls import path

from . import attention_views, photo_views, views

app_name = "inventory"

urlpatterns = [
    path("", views.card_list, name="card_list"),
    path("new/", views.card_create, name="card_create"),
    path("<int:pk>/", views.card_detail, name="card_detail"),
    path("<int:pk>/edit/", views.card_update, name="card_update"),
    path("<int:pk>/delete/", views.card_delete, name="card_delete"),
    path("<int:pk>/purchases/", views.purchase_add, name="purchase_add"),
    path("<int:card_pk>/photos/", photo_views.photo_upload, name="photo_upload"),
    path("photos/<int:pk>/file/", photo_views.photo_file, {"kind": "full"}, name="photo_file"),
    path("photos/<int:pk>/thumb/", photo_views.photo_file, {"kind": "thumb"}, name="photo_thumb"),
    path("photos/<int:pk>/main/", photo_views.photo_set_main, name="photo_set_main"),
    path("photos/<int:pk>/move-up/", photo_views.photo_move, {"direction": "up"}, name="photo_move_up"),
    path("photos/<int:pk>/move-down/", photo_views.photo_move, {"direction": "down"}, name="photo_move_down"),
    path("photos/<int:pk>/label/", photo_views.photo_label, name="photo_label"),
    path("photos/<int:pk>/replace/", photo_views.photo_replace, name="photo_replace"),
    path("photos/<int:pk>/delete/", photo_views.photo_delete, name="photo_delete"),
    path("attention/", attention_views.attention_list, name="attention"),
    path("attention/thresholds/", attention_views.threshold_settings, name="threshold_settings"),
    path("<int:pk>/pin/", attention_views.pin_card, name="pin_card"),
    path("<int:pk>/unpin/", attention_views.unpin_card, name="unpin_card"),
    path("<int:pk>/price-drop/", attention_views.price_preview, name="price_preview"),
    path("<int:pk>/price-drop/apply/", attention_views.price_apply, name="price_apply"),
    path("import/", views.csv_upload, name="csv_upload"),
    path("import/map/", views.csv_map, name="csv_map"),
]
