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
from emergency_response.search import astar, straight_line_heuristic, ucs

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "Scenarios"


class ScenarioTests(unittest.TestCase):
    """Exercise typed loading and baseline routing on all three supplied datasets.

    Parameters:
        No explicit parameters; construction/calls are managed by unittest.

    Preconditions:
        Used by unittest with the supplied scenarios available.

    Postconditions:
        Tests describe expected behavior; the class itself does not execute a check
        until unittest runs it.
    """
    def test_all_supplied_schemas_and_counts(self):
        """Detect missing, duplicated or unexpectedly changed real scenario records.

        Parameters:
            self: The ScenarioTests instance receiving the call; passed automatically by
                Python.

        Preconditions:
            Run through unittest with a valid test instance. Tests reading real data
            require the supplied Scenarios directory; corrupt-fixture tests also require
            setUp's temporary copy.

        Postconditions:
            On success all assertions for the behavior described above pass and the method
            returns None. A failure/error is reported by unittest. Production scenario
            files remain unchanged; corrupt fixtures are cleaned up by registered cleanup.
        """
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
        """Verify interpreted units and release rules using recognizable Scenario1 values.

        Parameters:
            self: The ScenarioTests instance receiving the call; passed automatically by
                Python.

        Preconditions:
            Run through unittest with a valid test instance. Tests reading real data
            require the supplied Scenarios directory; corrupt-fixture tests also require
            setUp's temporary copy.

        Postconditions:
            On success all assertions for the behavior described above pass and the method
            returns None. A failure/error is reported by unittest. Production scenario
            files remain unchanged; corrupt fixtures are cleaned up by registered cleanup.
        """
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

    def test_baseline_all_pairs_against_astar(self):
        # Compare two course algorithms and validate both returned paths.
        """Compare UCS with straight-line A* for all 845 pairs; validate both paths.

        Parameters:
            self: The ScenarioTests instance receiving the call; passed automatically by
                Python.

        Preconditions:
            Run through unittest with a valid test instance. Tests reading real data
            require the supplied Scenarios directory; corrupt-fixture tests also require
            setUp's temporary copy.

        Postconditions:
            On success all assertions for the behavior described above pass and the method
            returns None. A failure/error is reported by unittest. Production scenario
            files remain unchanged; corrupt fixtures are cleaned up by registered cleanup.
        """
        for directory in sorted(SCENARIOS.glob("Scenario*")):
            s = load_scenario(directory)
            graph = build_graph(s)
            roads = {r.id: r for r in s.roads}
            heuristics = {n.id: straight_line_heuristic(s, graph, n.id) for n in s.nodes}
            for start in (n.id for n in s.nodes):
                for goal in heuristics:
                    comparison = astar(graph, start, goal, heuristics[goal])
                    expected = comparison.seconds if comparison is not None else float("inf")
                    route = ucs(graph, start, goal)
                    with self.subTest(scenario=directory.name, start=start, goal=goal):
                        if expected == float("inf"):
                            self.assertIsNone(route)
                        else:
                            self.assertAlmostEqual(route.seconds, expected)
                            self.assertEqual((route.nodes[0], route.nodes[-1]), (start, goal))
                            self.assertEqual(len(route.roads), len(route.nodes) - 1)
                            # A plausible cost alone is insufficient: validate the returned path too.
                            for selected in (route, comparison):
                                total = 0
                                self.assertEqual((selected.nodes[0], selected.nodes[-1]), (start, goal))
                                self.assertEqual(len(selected.roads), len(selected.nodes)-1)
                                for a, b, road_id in zip(selected.nodes, selected.nodes[1:], selected.roads):
                                    road = roads[road_id]
                                    self.assertEqual(road.key, (a, b))
                                    total += road.normal_seconds
                                self.assertAlmostEqual(total, selected.seconds)

    def test_status_snapshot_is_directional_and_excludes_blocked_roads(self):
        """Check Blocked/Congested effects without treating reverse roads as identical.

        Parameters:
            self: The ScenarioTests instance receiving the call; passed automatically by
                Python.

        Preconditions:
            Run through unittest with a valid test instance. Tests reading real data
            require the supplied Scenarios directory; corrupt-fixture tests also require
            setUp's temporary copy.

        Postconditions:
            On success all assertions for the behavior described above pass and the method
            returns None. A failure/error is reported by unittest. Production scenario
            files remain unchanged; corrupt fixtures are cleaned up by registered cleanup.
        """
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
        """Reject malformed distributions without testing any unimplemented inference.

        Parameters:
            self: The ScenarioTests instance receiving the call; passed automatically by
                Python.

        Preconditions:
            Run through unittest with a valid test instance. Tests reading real data
            require the supplied Scenarios directory; corrupt-fixture tests also require
            setUp's temporary copy.

        Postconditions:
            On success all assertions for the behavior described above pass and the method
            returns None. A failure/error is reported by unittest. Production scenario
            files remain unchanged; corrupt fixtures are cleaned up by registered cleanup.
        """
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
    """Alter isolated temporary fixtures; never edit supplied scenario files.

    Parameters:
        No explicit parameters; construction/calls are managed by unittest.

    Preconditions:
        Used by unittest with the supplied scenarios available.

    Postconditions:
        Tests describe expected behavior; the class itself does not execute a check
        until unittest runs it.
    """
    def setUp(self):
        """Copy Scenario1 for each test and register cleanup even if an assertion fails.

        Parameters:
            self: The CorruptScenarioTests instance receiving the call; passed
                automatically by Python.

        Preconditions:
            unittest invokes this before each corrupt-fixture test; the scenario and tests
            directory must be readable/writable as needed.

        Postconditions:
            Creates an isolated temporary Scenario1 copy, assigns self.temp/self.directory,
            and registers cleanup. Supplied scenarios are unchanged.
        """
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tests")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "scenario"
        shutil.copytree(SCENARIOS / "Scenario1", self.directory)

    def replace_text(self, filename, old, new):
        """Change a known fixture value, failing if the expected original is absent.

        Parameters:
            self: The CorruptScenarioTests instance receiving the call; passed
                automatically by Python.
            filename: Filename inside this test's temporary scenario copy.
            old: Expected original text; its presence is asserted.
            new: Replacement text used to corrupt or adjust the temporary fixture.

        Preconditions:
            setUp must have created self.directory. The named temporary file must exist and
            contain old.

        Postconditions:
            Replaces every occurrence of old with new in the temporary file and returns
            None. Original scenarios are unchanged; missing old triggers AssertionError.
        """
        path = self.directory / filename
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new), encoding="utf-8")

    def test_dangling_road_reference(self):
        """A road cannot refer to a node absent from city_graph.json.

        Parameters:
            self: The CorruptScenarioTests instance receiving the call; passed
                automatically by Python.

        Preconditions:
            Run through unittest with a valid test instance. Tests reading real data
            require the supplied Scenarios directory; corrupt-fixture tests also require
            setUp's temporary copy.

        Postconditions:
            On success all assertions for the behavior described above pass and the method
            returns None. A failure/error is reported by unittest. Production scenario
            files remain unchanged; corrupt fixtures are cleaned up by registered cleanup.
        """
        path = self.directory / "city_graph.json"
        data = json.loads(path.read_text())
        data["roads"][0]["to"] = "unknown"
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "city_graph.json road"):
            load_scenario(self.directory)

    def test_zero_speed(self):
        """Zero speed is invalid because base travel time divides distance by speed.

        Parameters:
            self: The CorruptScenarioTests instance receiving the call; passed
                automatically by Python.

        Preconditions:
            Run through unittest with a valid test instance. Tests reading real data
            require the supplied Scenarios directory; corrupt-fixture tests also require
            setUp's temporary copy.

        Postconditions:
            On success all assertions for the behavior described above pass and the method
            returns None. A failure/error is reported by unittest. Production scenario
            files remain unchanged; corrupt fixtures are cleaned up by registered cleanup.
        """
        path = self.directory / "city_graph.json"
        data = json.loads(path.read_text())
        data["roads"][0]["speed"] = 0
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "numeric range"):
            load_scenario(self.directory)

    def test_conflicting_local_weather(self):
        """Reports for the same road must agree on its known local weather.

        Parameters:
            self: The CorruptScenarioTests instance receiving the call; passed
                automatically by Python.

        Preconditions:
            Run through unittest with a valid test instance. Tests reading real data
            require the supplied Scenarios directory; corrupt-fixture tests also require
            setUp's temporary copy.

        Postconditions:
            On success all assertions for the behavior described above pass and the method
            returns None. A failure/error is reported by unittest. Production scenario
            files remain unchanged; corrupt fixtures are cleaned up by registered cleanup.
        """
        self.replace_text("road_reports.csv", "N1,N2,Rain,Police", "N1,N2,Storm,Police")
        with self.assertRaisesRegex(ValueError, "conflicting known weather"):
            load_scenario(self.directory)

    def test_duplicate_traffic_observation(self):
        """A directed road cannot have two observations with the same ordinal index.

        Parameters:
            self: The CorruptScenarioTests instance receiving the call; passed
                automatically by Python.

        Preconditions:
            Run through unittest with a valid test instance. Tests reading real data
            require the supplied Scenarios directory; corrupt-fixture tests also require
            setUp's temporary copy.

        Postconditions:
            On success all assertions for the behavior described above pass and the method
            returns None. A failure/error is reported by unittest. Production scenario
            files remain unchanged; corrupt fixtures are cleaned up by registered cleanup.
        """
        path = self.directory / "observed_traffic.csv"
        with path.open("a") as stream:
            # The source file may lack a trailing newline; separate the appended record.
            stream.write("\n1,H1,N1,Low\n")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            load_scenario(self.directory)

    def test_history_is_sorted_per_road(self):
        """CSV record ordering must not change each road's reconstructed history.

        Parameters:
            self: The CorruptScenarioTests instance receiving the call; passed
                automatically by Python.

        Preconditions:
            Run through unittest with a valid test instance. Tests reading real data
            require the supplied Scenarios directory; corrupt-fixture tests also require
            setUp's temporary copy.

        Postconditions:
            On success all assertions for the behavior described above pass and the method
            returns None. A failure/error is reported by unittest. Production scenario
            files remain unchanged; corrupt fixtures are cleaned up by registered cleanup.
        """
        path = self.directory / "observed_traffic.csv"
        header, *rows = path.read_text().splitlines()
        path.write_text("\n".join([header, *reversed(rows)]) + "\n")
        s = load_scenario(self.directory)
        self.assertEqual([o.observation_nr for o in s.traffic_history[("H1", "N1")]], list(range(1, 11)))

    def test_available_with_remaining_busy_time_is_invalid(self):
        """Available and positive remaining busy time form a contradictory input state.

        Parameters:
            self: The CorruptScenarioTests instance receiving the call; passed
                automatically by Python.

        Preconditions:
            Run through unittest with a valid test instance. Tests reading real data
            require the supplied Scenarios directory; corrupt-fixture tests also require
            setUp's temporary copy.

        Postconditions:
            On success all assertions for the behavior described above pass and the method
            returns None. A failure/error is reported by unittest. Production scenario
            files remain unchanged; corrupt fixtures are cleaned up by registered cleanup.
        """
        self.replace_text("responders.csv", "Available,0", "Available,2.5")
        with self.assertRaisesRegex(ValueError, "zero remaining"):
            load_scenario(self.directory)

    def test_fractional_time_is_preserved_and_impossible_deadline_warns(self):
        """Retain fractional seconds and distinguish infeasibility from corrupt structure.

        Parameters:
            self: The CorruptScenarioTests instance receiving the call; passed
                automatically by Python.

        Preconditions:
            Run through unittest with a valid test instance. Tests reading real data
            require the supplied Scenarios directory; corrupt-fixture tests also require
            setUp's temporary copy.

        Postconditions:
            On success all assertions for the behavior described above pass and the method
            returns None. A failure/error is reported by unittest. Production scenario
            files remain unchanged; corrupt fixtures are cleaned up by registered cleanup.
        """
        self.replace_text("responders.csv", "Busy,10", "Busy,10.25")
        self.replace_text("incidents.csv", "I5,N1,High,200", "I5,N1,High,40.5")
        s = load_scenario(self.directory)
        self.assertEqual(next(r for r in s.responders if r.id == "R4").initial_ready_at, 10.25)
        self.assertTrue(any("I5: deadline precedes release" in w for w in s.warnings))


if __name__ == "__main__":
    unittest.main()
