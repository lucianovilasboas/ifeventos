from django.urls import path

from . import views

app_name = "apoio"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("evento/<int:evento_id>/", views.evento, name="evento"),
]