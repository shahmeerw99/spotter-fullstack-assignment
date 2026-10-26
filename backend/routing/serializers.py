from datetime import timezone

from django.utils.dateparse import parse_datetime
from rest_framework import serializers


class LocationField(serializers.Field):
    """Accepts 'City, ST', 'lat,lon' or {"lat": .., "lon": ..}."""

    default_error_messages = {"invalid": "Enter an address string or an object with lat and lon."}

    def to_internal_value(self, data):
        if isinstance(data, str):
            if not data.strip():
                raise serializers.ValidationError("This field may not be blank.")
            if len(data) > 200:
                raise serializers.ValidationError("Address is too long.")
            return data.strip()
        if isinstance(data, dict) and "lat" in data and "lon" in data:
            try:
                return {"lat": float(data["lat"]), "lon": float(data["lon"])}
            except (TypeError, ValueError):
                pass
        self.fail("invalid")

    def to_representation(self, value):
        return value


class AnalyzeRequestSerializer(serializers.Serializer):
    origin = LocationField()
    destination = LocationField()
    departure_time = serializers.CharField()
    load_weight_lb = serializers.FloatField(min_value=0, max_value=200_000)
    checkpoint_interval_miles = serializers.ChoiceField(choices=[10, 25, 50], default=25)

    def validate_departure_time(self, value: str):
        """Keep the caller's UTC offset so ETAs come back in the driver's local time. Naive = UTC."""
        try:
            dt = parse_datetime(value.strip())
        except ValueError:
            dt = None
        if dt is None:
            raise serializers.ValidationError("Use ISO 8601, e.g. 2026-10-25T08:00:00-05:00.")
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    def validate(self, attrs):
        if attrs["origin"] == attrs["destination"]:
            raise serializers.ValidationError("Origin and destination must be different.")
        return attrs
