from celery import shared_task

from .models import Booking


@shared_task
def sync_pms(booking_id):
    booking = Booking.objects.get(pk=booking_id)
    return {"synced": booking.id}
