from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from sales.views import dashboard

from .views import signup

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("registreren/", signup, name="signup"),
    path("dashboard/", dashboard, name="dashboard"),
    path("", include("inventory.urls")),
    path("financien/", include("finance.urls")),
    path("verkopen/", include("sales.urls")),
]
