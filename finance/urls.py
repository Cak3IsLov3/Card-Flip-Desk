from django.urls import path

from . import views

app_name = "finance"

urlpatterns = [
    path("calculator/", views.calculator, name="calculator"),
    path("kostenprofielen/", views.fee_profile_list, name="fee_profiles"),
    path("kostenprofielen/<int:pk>/", views.fee_profile_edit, name="fee_profile_edit"),
]
