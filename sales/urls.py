from django.urls import path

from . import views

app_name = "sales"

urlpatterns = [
    path("", views.sale_list, name="sale_list"),
    path("kaart/<int:card_pk>/", views.sale_create, name="sale_create"),
]
