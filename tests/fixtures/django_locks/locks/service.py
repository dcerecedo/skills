import secrets

from .client import LockProviderClient
from .models import AccessCode


class LockService:
    def __init__(self, client=None):
        self.client = client or LockProviderClient()

    def issue_code(self, booking):
        code = self._generate()
        self.client.create_code(booking.apartment.lock_id, code, booking.start, booking.end)
        return AccessCode.objects.create(booking=booking, code=code)

    def _generate(self):
        return f"{secrets.randbelow(10**6):06d}"
