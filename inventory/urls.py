from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("", views.card_list, name="card_list"),
    path("nieuw/", views.card_create, name="card_create"),
    path("<int:pk>/", views.card_detail, name="card_detail"),
    path("<int:pk>/bewerken/", views.card_update, name="card_update"),
    path("<int:pk>/verwijderen/", views.card_delete, name="card_delete"),
    path("<int:pk>/inkoop/", views.purchase_add, name="purchase_add"),
    path("import/", views.csv_upload, name="csv_upload"),
    path("import/koppelen/", views.csv_map, name="csv_map"),
]
