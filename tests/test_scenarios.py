"""Real-schema checks plus deliberately corrupted copies of Scenario1."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from emergency_response.loaders import (load_scenario, validate_road_probabilities,
                                         validate_traffic_probabilities)
from emergency_response.routing import build_graph
from emergency_response.search import ucs

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "Scenarios"


class ScenarioTests(unittest.TestCase):
    def test_all_supplied_schemas_and_counts(self):
        expected = {
            "Scenario1": (5, 14, 4, 7, 18, 14, 140),
            "Scenario2": (12, 30, 10, 12, 42, 3, 15),
            "Scenario3": (26, 60, 10, 20, 42, 10, 100),
        }
        for name, counts in expected.items():
            with self.subTest(scenario=name):
                s = load_scenario(SCENARIOS / name)
                self.assertEqual((len(s.nodes), len(s.roads), len(s.responders), len(s.incidents),
                                  len(s.road_reports), len(s.traffic_history),
                                  sum(map(len, s.traffic_history.values()))), counts)

    def test_units_capabilities_availability_and_online_visibility(self):
        s = load_scenario(SCENARIOS / "Scenario1")
        road = next(r for r in s.roads if r.key == ("H1", "N1"))
        self.assertAlmostEqual(road.normal_seconds, 458 / 15)
        r4 = next(r for r in s.responders if r.id == "R4")
        self.assertEqual(r4.initial_ready_at, 10)
        self.assertIn("First aid", r4.capabilities)
        self.assertEqual({i.id for i in s.known_incidents(0)}, {"I1", "I2", "I3", "I4"})
        self.assertEqual(len(s.known_incidents(50)), 6)
        self.assertEqual(len(s.known_incidents(60)), 7)
        i5 = next(i for i in s.incidents if i.id == "I5")
        self.assertEqual((i5.timestamp, i5.deadline), (50, 200))
        self.assertEqual([o.observation_nr for o in s.traffic_history[("H1", "N1")]], list(range(1, 11)))

    def test_baseline_all_pairs_against_bellman_ford(self):
        # Independent repeated relaxation checks optimal costs and route validity.
        for directory in sorted(SCENARIOS.glob("Scenario*")):
            s = load_scenario(directory)
            graph = build_graph(s)
            roads = {r.id: r for r in s.roads}
            for start in (n.id for n in s.nodes):
                distance = {n.id: float("inf") for n in s.nodes}
                distance[start] = 0
                for _ in range(len(s.nodes) - 1):
                    for r in s.roads:
                        distance[r.target] = min(distance[r.target], distance[r.source] + r.normal_seconds)
                for goal, expected in distance.items():
                    route = ucs(graph, start, goal)
                    with self.subTest(scenario=directory.name, start=start, goal=goal):
                        if expected == float("inf"):
                            self.assertIsNone(route)
                        else:
                            self.assertAlmostEqual(route.seconds, expected)
                            self.assertEqual((route.nodes[0], route.nodes[-1]), (start, goal))
                            self.assertEqual(len(route.roads), len(route.nodes) - 1)
                            total = 0
                            for a, b, road_id in zip(route.nodes, route.nodes[1:], route.roads):
                                road = roads[road_id]
                                self.assertEqual(road.key, (a, b))
                                total += road.normal_seconds
                            self.assertAlmostEqual(total, route.seconds)

    def test_status_snapshot_is_directional_and_excludes_blocked_roads(self):
        s = load_scenario(SCENARIOS / "Scenario1")
        statuses = {r.key: "Open" for r in s.roads}
        statuses[("H1", "N1")] = "Blocked"
        statuses[("N1", "H1")] = "Congested"
        graph = build_graph(s, statuses)
        self.assertFalse(any(e.target == "N1" for e in graph.neighbors("H1")))
        reverse = next(e for e in graph.neighbors("N1") if e.target == "H1")
        self.assertAlmostEqual(reverse.seconds, 458 / 15 * 1.5)
        with self.assertRaises(ValueError):
            build_graph(s, {("H1", "N1"): "Open"})
        statuses[("H1", "N1")] = "High"  # A traffic level is not a road status.
        with self.assertRaises(ValueError):
            build_graph(s, statuses)

    def test_probability_tables_reject_invalid_labels_ranges_and_row_sums(self):
        s = load_scenario(SCENARIOS / "Scenario1")
        for value in [-0.1, 1.1, float("nan"), True, 0.5]:
            bad = copy.deepcopy(s.traffic_probabilities)
            bad["initial"]["Low"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_traffic_probabilities(bad)
        bad = copy.deepcopy(s.road_probabilities)
        bad["police_report"]["Open"]["High"] = bad["police_report"]["Open"].pop("Open")
        with self.assertRaises(ValueError):
            validate_road_probabilities(bad)


class CorruptScenarioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tests")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "scenario"
        shutil.copytree(SCENARIOS / "Scenario1", self.directory)

    def replace_text(self, filename, old, new):
        path = self.directory / filename
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new), encoding="utf-8")

    def test_dangling_road_reference(self):
        path = self.directory / "city_graph.json"
        data = json.loads(path.read_text())
        data["roads"][0]["to"] = "unknown"
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "city_graph.json road"):
            load_scenario(self.directory)

    def test_zero_speed(self):
        path = self.directory / "city_graph.json"
        data = json.loads(path.read_text())
        data["roads"][0]["speed"] = 0
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "numeric range"):
            load_scenario(self.directory)

    def test_conflicting_local_weather(self):
        self.replace_text("road_reports.csv", "N1,N2,Rain,Police", "N1,N2,Storm,Police")
        with self.assertRaisesRegex(ValueError, "conflicting known weather"):
            load_scenario(self.directory)

    def test_duplicate_traffic_observation(self):
        path = self.directory / "observed_traffic.csv"
        with path.open("a") as stream:
            stream.write("\n1,H1,N1,Low\n")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            load_scenario(self.directory)

    def test_history_is_sorted_per_road(self):
        path = self.directory / "observed_traffic.csv"
        header, *rows = path.read_text().splitlines()
        path.write_text("\n".join([header, *reversed(rows)]) + "\n")
        s = load_scenario(self.directory)
        self.assertEqual([o.observation_nr for o in s.traffic_history[("H1", "N1")]], list(range(1, 11)))

    def test_available_with_remaining_busy_time_is_invalid(self):
        self.replace_text("responders.csv", "Available,0", "Available,2.5")
        with self.assertRaisesRegex(ValueError, "zero remaining"):
            load_scenario(self.directory)

    def test_fractional_time_is_preserved_and_impossible_deadline_warns(self):
        self.replace_text("responders.csv", "Busy,10", "Busy,10.25")
        self.replace_text("incidents.csv", "I5,N1,High,200", "I5,N1,High,40.5")
        s = load_scenario(self.directory)
        self.assertEqual(next(r for r in s.responders if r.id == "R4").initial_ready_at, 10.25)
        self.assertTrue(any("I5: deadline precedes release" in w for w in s.warnings))


if __name__ == "__main__":
    unittest.main()
