from django.urls import path

from . import views

app_name = "ebay"

urlpatterns = [
    path("", views.connection, name="connection"),
    path("connect/", views.connect, name="connect"),
    path("callback/", views.callback, name="callback"),
    path("disconnect/", views.disconnect, name="disconnect"),
]
