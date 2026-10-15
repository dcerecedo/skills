from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Booking
from .services import rebook


class RebookView(APIView):
    def post(self, request, pk):
        booking = Booking.objects.get(pk=pk)
        updated = rebook(booking, request.data["start"], request.data["end"])
        return Response({"id": updated.id, "status": updated.status})
