"""Hand-calculated Bayesian cases and course-style enumeration cross-checks.

All tests are run by unittest with self passed automatically. They require the
supplied scenarios to be readable. Passing tests return None with their assertions
satisfied; inputs/scenario files are never edited. No inference policy is tested
here: routing decisions belong in test_risk_routing.py.
"""
import copy
from dataclasses import replace
from itertools import product
from pathlib import Path
import unittest

from emergency_response.bayesian import infer_road_status, infer_scenario
from emergency_response.loaders import load_scenario
from emergency_response.models import RoadReport

ROOT = Path(__file__).resolve().parents[1]


class BayesianTests(unittest.TestCase):
    """Verify posteriors against arithmetic independent of inference helpers."""

    def setUp(self):
        """Load immutable-by-convention test inputs; self is the unittest instance.

        Preconditions: Scenario1 exists. Postconditions: self.s and self.tables
        contain valid inputs; no source files change.
        """
        self.s = load_scenario(ROOT / "Scenarios/Scenario1")
        self.tables = self.s.road_probabilities

    def assert_distribution(self, actual, expected):
        """Compare probabilities; self is the current test instance.

        Parameters: actual/expected are status-to-number dicts.
        Preconditions: values support numeric comparison.
        Postconditions: returns None if labels/values/sum match within tolerance;
        otherwise unittest raises an assertion failure. Inputs are unchanged.
        """
        self.assertEqual(set(actual), set(expected))
        self.assertAlmostEqual(sum(actual.values()), 1)
        for status, value in expected.items():
            self.assertAlmostEqual(actual[status], value, places=12)

    def test_worked_example_conflicting_reports(self):
        """Rain + Citizen/Police Blocked + Sensor Congested matches manual weights."""
        p = infer_road_status(self.tables, weather="Rain",
                              reports={"Citizen": "Blocked", "Police": "Blocked", "Sensor": "Congested"})
        self.assert_distribution(p, {"Open": .00012/.00837, "Congested": .00384/.00837,
                                     "Blocked": .00441/.00837})

    def test_reverse_road_example(self):
        """All Congested reports under Rain reproduce the reverse-road calculation."""
        p = infer_road_status(self.tables, weather="Rain",
                              reports={s: "Congested" for s in ("Citizen", "Police", "Sensor")})
        self.assert_distribution(p, {"Open": .00072/.121792, "Congested": .12096/.121792,
                                     "Blocked": .000112/.121792})

    def test_known_weather_without_reports(self):
        """No reports leaves the known Rain prior unchanged."""
        self.assert_distribution(infer_road_status(self.tables, weather="Rain"),
                                 {"Open": .6, "Congested": .3, "Blocked": .1})

    def test_unknown_weather_without_reports(self):
        """Marginalizing the supplied weather prior yields .685/.180/.135."""
        self.assert_distribution(infer_road_status(self.tables),
                                 {"Open": .685, "Congested": .18, "Blocked": .135})

    def test_one_report_and_unknown_weather(self):
        """A lone Citizen Blocked report updates the marginalized weather prior."""
        self.assert_distribution(infer_road_status(self.tables, reports={"Citizen": "Blocked"}),
                                 {"Open": .0685/.199, "Congested": .036/.199, "Blocked": .0945/.199})

    def test_missing_sources_by_full_joint_enumeration(self):
        """Sum out weather/Citizen/Sensor instead of omitting their factors by rule."""
        joint = {s: 0 for s in ("Open", "Congested", "Blocked")}
        for status, weather, citizen, sensor in product(joint, ("Clear", "Rain", "Storm"), joint, joint):
            joint[status] += (self.tables["weather_prior"][weather]
                              * self.tables["road_status_given_weather"][weather][status]
                              * self.tables["citizen_report"][status][citizen]
                              * self.tables["police_report"][status]["Blocked"]
                              * self.tables["sensor_report"][status][sensor])
        total = sum(joint.values())
        self.assert_distribution(infer_road_status(self.tables, reports={"Police": "Blocked"}),
                                 {s: v/total for s, v in joint.items()})

    def test_report_order_invariance_and_no_mutation(self):
        """Reordering the same evidence does not change beliefs or input data."""
        reports = {"Citizen": "Blocked", "Police": "Blocked", "Sensor": "Congested"}
        original = copy.deepcopy((self.tables, reports))
        a = infer_road_status(self.tables, weather="Rain", reports=reports)
        b = infer_road_status(self.tables, weather="Rain", reports=dict(reversed(list(reports.items()))))
        self.assertEqual(a, b)
        self.assertEqual((self.tables, reports), original)

    def test_directed_coverage_missing_evidence_and_local_weather(self):
        """Every road is inferred independently; neighbors/reverse roads do not leak evidence."""
        beliefs = infer_scenario(self.s)
        self.assertEqual(set(beliefs), {r.key for r in self.s.roads})
        self.assertAlmostEqual(beliefs[("N1", "N2")]["Blocked"], .00441/.00837)
        self.assertAlmostEqual(beliefs[("N2", "N1")]["Blocked"], .000112/.121792)
        self.assert_distribution(beliefs[("H1", "N1")], {"Open": .685, "Congested": .18, "Blocked": .135})
        self.assertAlmostEqual(beliefs[("H1", "N3")]["Blocked"], .2835/.284066)
        # Drop reverse reports: forward Rain must not become known reverse weather.
        s = replace(self.s, road_reports=tuple(r for r in self.s.road_reports if r.road != ("N2", "N1")))
        self.assert_distribution(infer_scenario(s)[("N2", "N1")],
                                 {"Open": .685, "Congested": .18, "Blocked": .135})

    def test_all_scenarios_normalize(self):
        """All supplied roads receive full finite distributions summing to one."""
        for directory in sorted((ROOT / "Scenarios").glob("Scenario*")):
            s = load_scenario(directory)
            beliefs = infer_scenario(s)
            self.assertEqual(len(beliefs), len(s.roads))
            for row in beliefs.values():
                self.assertAlmostEqual(sum(row.values()), 1)
                self.assertTrue(all(0 <= p <= 1 for p in row.values()))

    def test_invalid_inputs_and_zero_evidence(self):
        """Invalid labels and impossible evidence fail explicitly, without a fake fallback."""
        for kwargs in ({"weather": "Snow"}, {"reports": {"Unknown": "Open"}},
                       {"reports": {"Police": "High"}}, {"reports": []}):
            with self.assertRaises(ValueError):
                infer_road_status(self.tables, **kwargs)
        bad = copy.deepcopy(self.tables)
        bad["weather_prior"]["Clear"] = .1
        with self.assertRaises(ValueError):
            infer_road_status(bad)
        zero = copy.deepcopy(self.tables)
        for row in zero["police_report"].values():
            row.update(Open=0, Congested=1, Blocked=0)
        with self.assertRaisesRegex(ValueError, "zero likelihood"):
            infer_road_status(zero, reports={"Police": "Open"})

    def test_direct_scenarios_reject_ambiguous_reports(self):
        """Bypassing the loader must not enable double-counting or conflicting weather."""
        first = self.s.road_reports[0]
        for report in (first, replace(self.s.road_reports[1], weather="Storm"),
                       RoadReport("X", "Y", "Rain", "Police", "Open")):
            reports = (first, report)
            with self.assertRaises(ValueError):
                infer_scenario(replace(self.s, road_reports=reports))


if __name__ == "__main__":
    unittest.main()
