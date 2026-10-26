"""API tests. Every external call (Nominatim, OSRM, Open-Meteo) is mocked: no network."""

import json
from unittest import mock

import numpy as np
from django.core.cache import cache
from django.test import TestCase, override_settings

from routing.services import routing_client


def straight_route(lat0, lon0, lat1, lon1, n=400, hours=12.0, source="osrm"):
    lats = np.linspace(lat0, lat1, n)
    lons = np.linspace(lon0, lon1, n)
    from routing.services import geo

    miles = float(geo.cumulative_miles(lats, lons)[-1])
    return routing_client.Route(
        lats=lats,
        lons=lons,
        distance_miles=miles,
        duration_seconds=hours * 3600,
        segment_seconds=np.full(n - 1, hours * 3600 / (n - 1)),
        source=source,
    )


def fake_weather(windy_lat_above=None, wind=60.0):
    """Calm everywhere, or wind `wind` mph north of `windy_lat_above`."""

    def _request(chunk, start, end):
        hours = int((end - start).total_seconds() // 3600) + 1
        out = []
        for lat, _lon in chunk:
            w = wind if windy_lat_above is not None and lat > windy_lat_above else 5.0
            out.append(
                {
                    "wind": np.full(hours, w),
                    "gust": np.full(hours, w + 5),
                    "rain": np.zeros(hours),
                    "snow": np.zeros(hours),
                }
            )
        return out

    return _request


PAYLOAD = {
    "origin": {"lat": 32.78, "lon": -96.80},
    "destination": {"lat": 39.74, "lon": -104.99},
    "departure_time": "2026-10-25T08:00:00-05:00",
    "load_weight_lb": 42000,
    "checkpoint_interval_miles": 25,
}


@override_settings(ALLOWED_HOSTS=["testserver"])
class AnalyzeApi(TestCase):
    def setUp(self):
        cache.clear()
        # Three distinct corridors: direct, bowed north-east, bowed south-west.
        self.routes = [
            straight_route(32.78, -96.80, 39.74, -104.99, hours=12),
            _bent(32.78, -96.80, 39.74, -104.99, (37.5, -98.5), hours=14),
            _bent(32.78, -96.80, 39.74, -104.99, (34.5, -103.5), hours=15),
        ]

    def post(self, payload=None):
        return self.client.post("/api/routes/analyze", json.dumps(payload or PAYLOAD), content_type="application/json")

    def test_happy_path_shape(self):
        with mock.patch.object(routing_client, "_osrm", return_value=self.routes) as osrm, mock.patch(
            "routing.services.weather_client._request", side_effect=fake_weather()
        ):
            r = self.post()
        self.assertEqual(r.status_code, 200, r.content)
        osrm.assert_called_once()  # 3 routes came back, so no fallback calls
        d = r.json()
        self.assertEqual(len(d["routes"]), 3)
        self.assertEqual(sum(rt["recommended"] for rt in d["routes"]), 1)
        best = d["routes"][0]
        self.assertTrue(best["recommended"])
        self.assertEqual(best["rank"], 1)
        # Calm weather everywhere -> fastest route wins on time.
        self.assertIn("min faster", best["recommendation_reason"])
        self.assertAlmostEqual(best["duration_hours"], 12, places=1)

        cps = best["checkpoints"]
        self.assertEqual(cps[0]["mile"], 0)
        self.assertAlmostEqual(cps[-1]["mile"], best["distance_miles"], delta=0.1)
        self.assertEqual(cps[1]["mile"], 25)
        self.assertTrue(cps[0]["eta"].endswith("-05:00"))  # ETA keeps the driver's offset
        self.assertAlmostEqual(sum(c["represented_miles"] for c in cps), best["distance_miles"], delta=0.5)
        self.assertEqual(cps[3]["risk"]["level"], "Low")
        self.assertIsNotNone(d["analysis_id"])

    def test_wind_plus_heavy_load_moves_recommendation(self):
        # 50 mph wind north of 37.2N: with 42,000 lb that's No Travel. Only the south-west route avoids
        # most of it, but every route ends in Denver, so all three cross some No Travel miles.
        with mock.patch.object(routing_client, "_osrm", return_value=self.routes), mock.patch(
            "routing.services.weather_client._request", side_effect=fake_weather(windy_lat_above=37.2, wind=50)
        ):
            d = self.post().json()
        best = d["routes"][0]
        others = d["routes"][1:]
        self.assertTrue(all(best["summary"]["no_travel_miles"] <= o["summary"]["no_travel_miles"] for o in others))
        self.assertIn("No safe route", d["warning"])
        windy = next(c for c in best["checkpoints"] if c["lat"] > 37.5)
        self.assertEqual(windy["risk"]["level"], "No Travel")
        self.assertIn("30,000", windy["risk"]["load_rule_applied"])

    def test_forecast_beyond_horizon_is_marked(self):
        payload = {**PAYLOAD, "departure_time": "2099-01-01T08:00:00Z"}
        with mock.patch.object(routing_client, "_osrm", return_value=self.routes), mock.patch(
            "routing.services.weather_client._request", side_effect=fake_weather()
        ) as wx:
            d = self.post(payload).json()
        wx.assert_not_called()
        cp = d["routes"][0]["checkpoints"][1]
        self.assertEqual(cp["status"], "forecast_unavailable")
        self.assertIsNone(cp["risk"])
        self.assertIn("forecast horizon", d["warning"])

    def test_fallback_adds_via_routes_when_osrm_returns_one(self):
        calls = []

        def osrm(coords, alternatives):
            calls.append(len(coords))
            if len(coords) == 2:
                return [self.routes[0]]
            via = coords[1]
            return [_bent(32.78, -96.80, 39.74, -104.99, via, hours=13, source="osrm-via")]

        with mock.patch.object(routing_client, "_osrm", side_effect=osrm), mock.patch(
            "routing.services.weather_client._request", side_effect=fake_weather()
        ):
            d = self.post().json()
        self.assertEqual(len(d["routes"]), 3)
        self.assertEqual(calls[0], 2)
        self.assertTrue(all(c == 3 for c in calls[1:]))
        self.assertEqual(sum(r["source"] == "osrm-via" for r in d["routes"]), 2)

    def test_response_is_cached(self):
        with mock.patch.object(routing_client, "_osrm", return_value=self.routes) as osrm, mock.patch(
            "routing.services.weather_client._request", side_effect=fake_weather()
        ):
            self.post()
            d = self.post().json()
        self.assertEqual(osrm.call_count, 1)
        self.assertTrue(d["cached"])

    def test_heatmap_after_analysis(self):
        with mock.patch.object(routing_client, "_osrm", return_value=self.routes), mock.patch(
            "routing.services.weather_client._request", side_effect=fake_weather(windy_lat_above=38.5, wind=60)
        ):
            d = self.post().json()
            h = self.client.get(f"/api/heatmap?analysis_id={d['analysis_id']}")
        self.assertEqual(h.status_code, 200)
        hm = h.json()
        self.assertEqual(len(hm["hours"]), 49)
        self.assertEqual(len(hm["values"]), 49)
        self.assertEqual(len(hm["values"][0]), len(hm["points"]))
        self.assertLessEqual(len(hm["points"]), 220)
        self.assertIn(4, hm["values"][0])
        self.assertIn(0, hm["values"][0])

    def test_heatmap_unknown_analysis(self):
        self.assertEqual(self.client.get("/api/heatmap?analysis_id=abc123").status_code, 404)

    def test_validation_errors(self):
        r = self.post({**PAYLOAD, "checkpoint_interval_miles": 30})
        self.assertEqual(r.status_code, 400)
        self.assertIn("checkpoint_interval_miles", r.json()["fields"])
        r = self.post({**PAYLOAD, "departure_time": "tomorrow"})
        self.assertEqual(r.status_code, 400)
        r = self.post({**PAYLOAD, "load_weight_lb": -5})
        self.assertEqual(r.status_code, 400)

    def test_outside_usa_rejected(self):
        r = self.post({**PAYLOAD, "origin": {"lat": 51.5, "lon": -0.12}})
        self.assertEqual(r.status_code, 400)
        self.assertIn("outside the USA", r.json()["error"])

    def test_weather_rate_limit_returns_503(self):
        with mock.patch.object(routing_client, "_osrm", return_value=self.routes), mock.patch(
            "routing.services.weather_client.get_json", return_value=({"reason": "Minutely API request limit exceeded"}, 429)
        ):
            r = self.post()
        self.assertEqual(r.status_code, 503)
        self.assertIn("try again in a minute", r.json()["error"])

    def test_upstream_timeout_returns_504(self):
        from routing.services.errors import UpstreamTimeout

        with mock.patch.object(routing_client, "_osrm", side_effect=UpstreamTimeout("Routing timed out")):
            r = self.post()
        self.assertEqual(r.status_code, 504)
        self.assertEqual(r.json()["error"], "Routing timed out")


def _bent(lat0, lon0, lat1, lon1, via, hours, source="osrm"):
    a = straight_route(lat0, lon0, via[0], via[1], n=200)
    b = straight_route(via[0], via[1], lat1, lon1, n=200)
    lats = np.concatenate([a.lats, b.lats[1:]])
    lons = np.concatenate([a.lons, b.lons[1:]])
    from routing.services import geo

    miles = float(geo.cumulative_miles(lats, lons)[-1])
    return routing_client.Route(lats, lons, miles, hours * 3600, None, source)
