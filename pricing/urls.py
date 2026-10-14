from django.urls import path

from . import views

app_name = "pricing"

urlpatterns = [
    path("kaart/<int:card_pk>/", views.card_advice, name="card_advice"),
]
