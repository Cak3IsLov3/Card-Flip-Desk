from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from . import views

app_name = "api"

router = DefaultRouter()
router.register("cards", views.CardViewSet, basename="card")
router.register("purchases", views.PurchaseViewSet, basename="purchase")
router.register("photos", views.PhotoViewSet, basename="photo")
router.register("listings", views.ListingViewSet, basename="listing")
router.register("listing-templates", views.ListingTemplateViewSet, basename="listing-template")
router.register("sales", views.SaleViewSet, basename="sale")
router.register("fee-profiles", views.FeeProfileViewSet, basename="fee-profile")

urlpatterns = [
    path("", include(router.urls)),
    path("calculator/", views.CalculatorView.as_view(), name="calculator"),
    path("calculator/reverse/", views.ReverseCalculatorView.as_view(), name="calculator-reverse"),
    path("auth/token/", views.TokenView.as_view(), name="token"),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api:schema"), name="docs"),
]
