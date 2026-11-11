from django.urls import path

from . import views

app_name = "social"

urlpatterns = [
    path("settings/", views.SettingsView.as_view(), name="settings"),
    path("articles/<int:pk>/share/<str:network>/", views.share, name="share"),
]
