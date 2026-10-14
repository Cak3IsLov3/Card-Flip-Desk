from django.urls import path

from . import import_views, listing_views, views

app_name = "sales"

urlpatterns = [
    path("", views.sale_list, name="sale_list"),
    path("import/", import_views.seller_hub_upload, name="seller_hub_upload"),
    path("import/map/", import_views.seller_hub_map, name="seller_hub_map"),
    path("import/review/", import_views.seller_hub_review, name="seller_hub_review"),
    path("card/<int:card_pk>/", views.sale_create, name="sale_create"),
    path("card/<int:card_pk>/listing/", listing_views.listing_generator, name="listing_generator"),
    path("card/<int:card_pk>/listing/profit/", listing_views.listing_profit, name="listing_profit"),
    path("templates/", listing_views.template_list, name="template_list"),
    path("templates/<int:pk>/", listing_views.template_edit, name="template_edit"),
]
