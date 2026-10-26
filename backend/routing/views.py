import logging

from django.http import JsonResponse
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import AnalyzeRequestSerializer
from .services import analysis
from .services.errors import ServiceError

logger = logging.getLogger("routing")


def _error(exc: ServiceError) -> Response:
    return Response({"error": exc.message}, status=exc.status)


class AnalyzeView(APIView):
    """POST /api/routes/analyze — 3 routes with checkpoint weather, risk and a recommendation."""

    def post(self, request: Request) -> Response:
        ser = AnalyzeRequestSerializer(data=request.data)
        if not ser.is_valid():
            return Response({"error": "Invalid request.", "fields": ser.errors}, status=400)
        d = ser.validated_data
        try:
            result = analysis.analyze(
                analysis.TripRequest(
                    origin=d["origin"],
                    destination=d["destination"],
                    departure=d["departure_time"],
                    load_weight_lb=d["load_weight_lb"],
                    checkpoint_interval_miles=int(d["checkpoint_interval_miles"]),
                )
            )
        except ServiceError as exc:
            return _error(exc)
        return Response(result)


class HeatmapView(APIView):
    """GET /api/heatmap?analysis_id=... — risk scores for the corridor grid, hours 0–48 from departure."""

    def get(self, request: Request) -> Response:
        analysis_id = request.query_params.get("analysis_id", "").strip()
        if not analysis_id.isalnum() or len(analysis_id) > 32:
            return Response({"error": "analysis_id is required."}, status=400)
        try:
            return Response(analysis.heatmap_for(analysis_id))
        except ServiceError as exc:
            return _error(exc)


def health(request):
    return JsonResponse({"status": "ok"})
