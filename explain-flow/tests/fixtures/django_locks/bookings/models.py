from django.db import models


class Booking(models.Model):
    guest = models.CharField(max_length=120)
    apartment = models.ForeignKey("locks.Apartment", on_delete=models.CASCADE)
    start = models.DateTimeField()
    end = models.DateTimeField()
    status = models.CharField(max_length=20, default="confirmed")
