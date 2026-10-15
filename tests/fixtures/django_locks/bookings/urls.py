from django.urls import path

from . import views

urlpatterns = [
    path("bookings/<int:pk>/rebook/", views.RebookView.as_view(), name="booking-rebook"),
]
