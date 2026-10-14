from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from api.token_views import api_token
from sales.views import dashboard

from .views import signup

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("signup/", signup, name="signup"),
    path("dashboard/", dashboard, name="dashboard"),
    path("", include("inventory.urls")),
    path("finance/", include("finance.urls")),
    path("sales/", include("sales.urls")),
    path("ebay/", include("ebay.urls")),
    path("pricing/", include("pricing.urls")),
    path("api/v1/", include("api.urls")),
    path("api-token/", api_token, name="api_token"),
]
