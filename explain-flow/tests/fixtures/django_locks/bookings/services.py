from locks.service import LockService

from .tasks import sync_pms


def rebook(booking, start, end):
    booking.start = start
    booking.end = end
    booking.status = "rebooked"
    booking.save()
    LockService().issue_code(booking)
    sync_pms.delay(booking.id)
    return booking
