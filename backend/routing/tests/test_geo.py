from datetime import datetime, timezone
from unittest import TestCase

import numpy as np

from routing.services import eta, geo


class Haversine(TestCase):
    def test_known_distance(self):
        # New York -> Los Angeles is ~2,445 miles great-circle.
        d = geo.haversine_miles(40.7128, -74.0060, 34.0522, -118.2437)
        self.assertAlmostEqual(float(d), 2445, delta=10)

    def test_one_degree_latitude(self):
        self.assertAlmostEqual(float(geo.haversine_miles(0, 0, 1, 0)), 69.09, delta=0.1)

    def test_cumulative(self):
        lats = np.array([0.0, 1.0, 2.0])
        lons = np.zeros(3)
        cum = geo.cumulative_miles(lats, lons)
        self.assertEqual(cum[0], 0)
        self.assertAlmostEqual(cum[-1], 2 * 69.09, delta=0.2)


class Checkpoints(TestCase):
    def test_intervals_include_origin_and_destination(self):
        for interval in (10, 25, 50):
            with self.subTest(interval=interval):
                marks = geo.checkpoint_miles(237.0, interval)
                self.assertEqual(marks[0], 0)
                self.assertEqual(marks[-1], 237.0)
                self.assertTrue(np.allclose(np.diff(marks)[:-1], interval))

    def test_exact_multiple_has_no_duplicate_end(self):
        marks = geo.checkpoint_miles(100.0, 25)
        self.assertEqual(marks.tolist(), [0, 25, 50, 75, 100])

    def test_represented_miles_sum_to_route_length(self):
        for total in (5.0, 100.0, 237.4, 1999.9):
            for interval in (10, 25, 50):
                marks = geo.checkpoint_miles(total, interval)
                self.assertAlmostEqual(geo.represented_miles(marks).sum(), total, places=6)

    def test_represented_miles_halves(self):
        marks = geo.checkpoint_miles(60.0, 25)  # 0, 25, 50, 60
        self.assertEqual(geo.represented_miles(marks).tolist(), [12.5, 25.0, 17.5, 5.0])

    def test_interpolation_along_a_meridian(self):
        lats = np.array([30.0, 31.0, 32.0])
        lons = np.array([-100.0, -100.0, -100.0])
        cum = geo.cumulative_miles(lats, lons)
        la, lo = geo.interpolate_along(cum, lats, lons, [cum[-1] / 4])
        self.assertAlmostEqual(float(la[0]), 30.5, places=3)
        self.assertAlmostEqual(float(lo[0]), -100.0)


class Corridor(TestCase):
    def test_nearest_on_route(self):
        r_lats = np.linspace(35, 36, 70)
        r_lons = np.full(70, -100.0)
        # A point 0.1 deg of longitude east of the line at 35.5N is ~5.6 miles away.
        idx, d = geo.nearest_on_route(np.array([35.5]), np.array([-99.9]), r_lats, r_lons)
        self.assertAlmostEqual(float(d[0]), 5.63, delta=0.2)
        self.assertAlmostEqual(float(r_lats[idx[0]]), 35.5, delta=0.02)

    def test_simplify_keeps_endpoints_and_drops_collinear(self):
        lats = np.linspace(30, 31, 100)
        lons = np.linspace(-100, -99, 100)
        keep = geo.simplify(lats, lons)
        self.assertEqual(keep.tolist(), [0, 99])

    def test_offset_point_is_left_of_travel(self):
        lat, lon = geo.perpendicular_offset_point(30, -100, 30, -90, 0.1)  # travelling east
        self.assertGreater(lat, 30)  # left of east is north
        self.assertAlmostEqual(lon, -95, places=6)


class Eta(TestCase):
    def test_per_segment_durations(self):
        cum = np.array([0.0, 10.0, 20.0])
        secs = eta.cumulative_seconds(np.array([600.0, 1800.0]), cum, 2400.0)
        dep = datetime(2026, 1, 1, 8, tzinfo=timezone.utc)
        (at_10,) = eta.eta_at_miles(dep, cum, secs, [10.0])
        self.assertEqual(at_10, datetime(2026, 1, 1, 8, 10, tzinfo=timezone.utc))

    def test_linear_fallback(self):
        cum = np.array([0.0, 50.0, 100.0])
        secs = eta.cumulative_seconds(None, cum, 7200.0)
        self.assertEqual(secs.tolist(), [0, 3600, 7200])

    def test_round_to_hour(self):
        self.assertEqual(eta.round_to_hour(datetime(2026, 1, 1, 8, 29)).hour, 8)
        self.assertEqual(eta.round_to_hour(datetime(2026, 1, 1, 8, 30)).hour, 9)


class WeatherGrid(TestCase):
    def test_short_trip_keeps_fine_grid(self):
        from routing.services.weather_client import choose_grid_step

        pts = [(35 + i * 0.15, -100.0) for i in range(100)]
        self.assertEqual(choose_grid_step(pts, budget=350), 0.1)

    def test_long_trip_gets_coarser_grid_within_budget(self):
        from routing.services.weather_client import choose_grid_step, round_coord

        pts = [(35 + i * 0.01, -120 + i * 0.05) for i in range(900)]  # ~2,800 mi at ~3 mi spacing
        step = choose_grid_step(pts, budget=350)
        self.assertGreater(step, 0.1)
        self.assertLessEqual(len({(round_coord(a, step), round_coord(b, step)) for a, b in pts}), 350)
