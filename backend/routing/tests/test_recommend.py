from unittest import TestCase

from routing.services.recommend import rank, summarize


def route(rid, hours, cps):
    """cps: list of (miles, score)"""
    return summarize(rid, hours, cps)


class Summaries(TestCase):
    def test_miles_by_level_and_average(self):
        s = route("a", 10, [(10, 0), (20, 2), (10, 3)])
        self.assertEqual(s.miles_by_level["Low"], 10)
        self.assertEqual(s.high_miles, 20)
        self.assertEqual(s.severe_miles, 10)
        self.assertAlmostEqual(s.average_risk, (0 * 10 + 2 * 20 + 3 * 10) / 40)
        self.assertEqual(s.max_level, "Severe")

    def test_unavailable_forecast_is_excluded_from_average(self):
        s = route("a", 10, [(10, 2), (30, None)])
        self.assertEqual(s.unknown_miles, 30)
        self.assertEqual(s.average_risk, 2)


class Ranking(TestCase):
    def test_fewest_severe_miles_wins_first(self):
        a = route("a", 5, [(50, 3), (50, 0)])  # 50 severe, 0 high
        b = route("b", 9, [(10, 3), (90, 2)])  # 10 severe, 90 high
        r = rank([a, b])
        self.assertEqual([s.route_id for s in r.order], ["b", "a"])
        self.assertIn("Severe miles", r.reasons["b"])

    def test_then_fewest_high_miles(self):
        a = route("a", 5, [(30, 2), (70, 0)])
        b = route("b", 9, [(10, 2), (90, 1)])
        self.assertEqual(rank([a, b]).order[0].route_id, "b")

    def test_then_lowest_average_risk(self):
        a = route("a", 5, [(100, 1)])
        b = route("b", 9, [(50, 1), (50, 0)])
        r = rank([a, b])
        self.assertEqual(r.order[0].route_id, "b")
        self.assertIn("average risk", r.reasons["b"])

    def test_then_shortest_time(self):
        a = route("a", 9, [(100, 0)])
        b = route("b", 5, [(100, 0)])
        r = rank([a, b])
        self.assertEqual(r.order[0].route_id, "b")
        self.assertEqual(r.reasons["b"], "Same weather risk as the next option, but 240 min faster")
        self.assertEqual(r.reasons["a"], "Same weather risk as #1, which is 240 min faster")

    def test_no_travel_is_worse_than_any_severe(self):
        a = route("a", 5, [(1, 4), (99, 0)])
        b = route("b", 5, [(99, 3), (1, 0)])
        self.assertEqual(rank([a, b]).order[0].route_id, "b")

    def test_all_routes_no_travel_gives_warning_but_still_ranks(self):
        a = route("a", 5, [(10, 4), (90, 0)])
        b = route("b", 5, [(20, 4), (80, 0)])
        r = rank([a, b])
        self.assertEqual(r.order[0].route_id, "a")
        self.assertIn("No safe route", r.warning)

    def test_tiny_differences_are_ties(self):
        a = route("a", 6, [(100.01, 2)])
        b = route("b", 5, [(100.0, 2)])
        self.assertEqual(rank([a, b]).order[0].route_id, "b")

    def test_reason_never_reports_negative_time(self):
        # 0.004 vs 0.0 average risk rounds to a different bucket, so the reason must cite risk, not time.
        a = route("a", 50, [(1000, 0)])
        b = route("b", 46, [(996, 0), (4, 1)])
        c = route("c", 53, [(1000, 0)])
        r = rank([a, b, c])
        for reason in r.reasons.values():
            self.assertNotIn("-", reason)

    def test_single_route(self):
        r = rank([route("a", 5, [(10, 0)])])
        self.assertEqual(r.reasons["a"], "Only route available")
