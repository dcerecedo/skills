from django.db import models


class Apartment(models.Model):
    name = models.CharField(max_length=120)
    lock_id = models.CharField(max_length=64)


class AccessCode(models.Model):
    booking = models.ForeignKey("bookings.Booking", on_delete=models.CASCADE)
    code = models.CharField(max_length=6)
