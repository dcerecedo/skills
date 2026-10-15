from django.db.models.signals import post_save
from django.dispatch import receiver

from locks.service import LockService

from .models import Booking


@receiver(post_save, sender=Booking)
def on_booking_saved(sender, instance, created, **kwargs):
    if instance.status in ("confirmed", "rebooked"):
        LockService().issue_code(instance)
