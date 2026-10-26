from unittest import TestCase

import numpy as np

from routing.services.risk import Level, Weather, assess, rain_level, score_grid, snow_level, wind_level


def wx(wind=0.0, rain=0.0, snow=0.0, gust=0.0):
    return Weather(wind_mph=wind, gust_mph=gust, rain_in_hr=rain, snow_in_hr=snow)


class WindThresholds(TestCase):
    def test_boundaries(self):
        cases = [
            (0, Level.LOW), (24.9, Level.LOW),
            (25, Level.MODERATE), (34.9, Level.MODERATE),
            (35, Level.HIGH), (44.9, Level.HIGH),
            (45, Level.SEVERE), (54.9, Level.SEVERE),
            (55, Level.NO_TRAVEL), (80, Level.NO_TRAVEL),
        ]
        for mph, expected in cases:
            with self.subTest(mph=mph):
                self.assertEqual(wind_level(mph), expected)


class RainThresholds(TestCase):
    def test_boundaries(self):
        cases = [
            (0.0, Level.LOW), (0.099, Level.LOW),
            (0.10, Level.MODERATE), (0.249, Level.MODERATE),
            (0.25, Level.HIGH), (0.499, Level.HIGH),
            (0.50, Level.SEVERE), (1.00, Level.SEVERE),
            (1.001, Level.NO_TRAVEL),
        ]
        for v, expected in cases:
            with self.subTest(rain=v):
                self.assertEqual(rain_level(v), expected)


class SnowThresholds(TestCase):
    def test_boundaries(self):
        cases = [
            (0.0, Level.LOW), (0.49, Level.LOW),
            (0.5, Level.MODERATE), (0.99, Level.MODERATE),
            (1.0, Level.HIGH), (1.99, Level.HIGH),
            (2.0, Level.SEVERE), (3.0, Level.SEVERE),
            (3.01, Level.NO_TRAVEL),
        ]
        for v, expected in cases:
            with self.subTest(snow=v):
                self.assertEqual(snow_level(v), expected)


class LoadRules(TestCase):
    def test_55_mph_is_no_travel_for_any_load(self):
        a = assess(wx(wind=55), load_lb=0)
        self.assertEqual(a.level, Level.NO_TRAVEL)
        self.assertIn("any load", a.load_rule_applied)

    def test_45_to_54_mph_over_30k_is_no_travel(self):
        self.assertEqual(assess(wx(wind=45), 30_001).level, Level.NO_TRAVEL)
        self.assertEqual(assess(wx(wind=54.9), 30_001).level, Level.NO_TRAVEL)

    def test_45_to_54_mph_at_or_under_30k_stays_severe(self):
        a = assess(wx(wind=50), 30_000)
        self.assertEqual(a.level, Level.SEVERE)
        self.assertIsNone(a.load_rule_applied)

    def test_35_to_44_mph_over_40k_is_severe(self):
        a = assess(wx(wind=35), 40_001)
        self.assertEqual(a.level, Level.SEVERE)
        self.assertIn("40,000", a.load_rule_applied)
        self.assertEqual(assess(wx(wind=44.9), 40_001).level, Level.SEVERE)

    def test_35_to_44_mph_at_40k_stays_high(self):
        self.assertEqual(assess(wx(wind=40), 40_000).level, Level.HIGH)

    def test_35_to_44_mph_between_30k_and_40k_stays_high(self):
        self.assertEqual(assess(wx(wind=40), 35_000).level, Level.HIGH)

    def test_load_rules_do_not_touch_low_wind(self):
        self.assertEqual(assess(wx(wind=34.9), 80_000).level, Level.MODERATE)


class WorstOf(TestCase):
    def test_level_is_worst_condition(self):
        a = assess(wx(wind=26, rain=0.3, snow=2.5), 10_000)
        self.assertEqual(a.level, Level.SEVERE)
        self.assertEqual(a.drivers, ["snow"])
        self.assertEqual(a.by_condition, {"wind": "Moderate", "rain": "High", "snow": "Severe"})

    def test_ties_list_every_driver(self):
        a = assess(wx(wind=36, rain=0.3), 10_000)
        self.assertEqual(a.level, Level.HIGH)
        self.assertEqual(a.drivers, ["wind", "rain"])

    def test_load_rule_can_be_the_worst(self):
        a = assess(wx(wind=46, rain=0.6), 35_000)
        self.assertEqual(a.level, Level.NO_TRAVEL)
        self.assertEqual(a.drivers, ["wind"])

    def test_calm_weather_has_no_drivers(self):
        a = assess(wx(), 10_000)
        self.assertEqual(a.level, Level.LOW)
        self.assertEqual(a.drivers, [])

    def test_gusts_do_not_drive_classification(self):
        self.assertEqual(assess(wx(wind=10, gust=60), 10_000).level, Level.LOW)


class VectorisedMatchesScalar(TestCase):
    def test_score_grid_agrees_with_assess(self):
        rng = np.random.default_rng(1)
        wind = rng.uniform(0, 70, 500)
        rain = rng.uniform(0, 1.5, 500)
        snow = rng.uniform(0, 4, 500)
        for load in (0, 30_000, 35_000, 45_000):
            grid = score_grid(wind, wind, rain, snow, load)
            for i in range(500):
                self.assertEqual(grid[i], assess(wx(wind[i], rain[i], snow[i]), load).score)

    def test_missing_values_are_minus_one(self):
        self.assertEqual(score_grid([np.nan], [0], [0], [0], 0)[0], -1)
