from django.urls import path

from . import listing_views, views

app_name = "sales"

urlpatterns = [
    path("", views.sale_list, name="sale_list"),
    path("kaart/<int:card_pk>/", views.sale_create, name="sale_create"),
    path("kaart/<int:card_pk>/listing/", listing_views.listing_generator, name="listing_generator"),
    path("kaart/<int:card_pk>/listing/winst/", listing_views.listing_profit, name="listing_profit"),
    path("templates/", listing_views.template_list, name="template_list"),
    path("templates/<int:pk>/", listing_views.template_edit, name="template_edit"),
]
