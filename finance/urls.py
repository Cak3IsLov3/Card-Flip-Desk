from django.urls import path

from . import views

app_name = "finance"

urlpatterns = [
    path("calculator/", views.calculator, name="calculator"),
    path("fee-profiles/", views.fee_profile_list, name="fee_profiles"),
    path("fee-profiles/<int:pk>/", views.fee_profile_edit, name="fee_profile_edit"),
    path("shipping/", views.shipping_method_list, name="shipping_methods"),
    path("shipping/<int:pk>/", views.shipping_method_edit, name="shipping_method_edit"),
]
