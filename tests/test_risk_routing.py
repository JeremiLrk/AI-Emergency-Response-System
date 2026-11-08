"""Policy, UCS and CLI integration tests over preserved Bayesian distributions.

unittest supplies self to each test. Preconditions: supplied scenarios readable;
the standard test runner initializes fixtures where present. Postconditions on
success: named assertions pass, test methods return None, and production inputs
are unchanged. Temporary CLI state/stdout are restored by context managers.
"""
import contextlib
import copy
from dataclasses import replace
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import run
from emergency_response.bayesian import infer_scenario
from emergency_response.loaders import load_scenario
from emergency_response.models import Node, Road
from emergency_response.risk_routing import build_bayesian_graph, route_blockage_bounds
from emergency_response.routing import build_graph
from emergency_response.search import Route, ucs

ROOT = Path(__file__).resolve().parents[1]


class RiskRoutingTests(unittest.TestCase):
    """Separate policy consequences from inference correctness and UCS optimality."""

    def setUp(self):
        """Initialize self.s/self.beliefs from Scenario1, without changing files.

        Parameters: self is the test receiver. Preconditions: Scenario1 readable.
        Postconditions: valid scenario and a fresh full posterior mapping exist.
        """
        self.s = load_scenario(ROOT / "Scenarios/Scenario1")
        self.beliefs = infer_scenario(self.s)

    def test_conditional_time_includes_normalization(self):
        """Unknown-weather roads use (.685 + 1.5*.18)/(.685+.18), not MAP Open."""
        graph = build_bayesian_graph(self.s, self.beliefs, blocked_threshold=.2)
        edge = next(e for e in graph.neighbors("H1") if e.target == "N1")
        self.assertAlmostEqual(edge.seconds, (458/15)*(.685+1.5*.18)/(.685+.18))
        self.assertGreater(edge.seconds, 458/15)

    def test_posterior_driven_detour_and_risk_bounds(self):
        """Threshold .2 excludes the uncertain direct road and reports residual detour risk."""
        baseline = ucs(build_graph(self.s), "N1", "N2")
        self.assertEqual(baseline.nodes, ("N1", "N2"))
        original = copy.deepcopy(self.beliefs)
        graph = build_bayesian_graph(self.s, self.beliefs, blocked_threshold=.2)
        route = ucs(graph, "N1", "N2")
        self.assertEqual(route.nodes, ("N1", "H1", "N2"))
        self.assertAlmostEqual(route.seconds, 78.6*(.685+1.5*.18)/(.685+.18))
        bounds = route_blockage_bounds(self.s, self.beliefs, route)
        self.assertAlmostEqual(bounds.lower, .135)
        self.assertAlmostEqual(bounds.upper, .27)
        self.assertEqual(original, self.beliefs)

    def test_directed_policy_and_no_route_under_strict_threshold(self):
        """Direction-specific evidence preserves reverse arcs; restrictive policy can disconnect."""
        graph = build_bayesian_graph(self.s, self.beliefs, blocked_threshold=.2)
        self.assertFalse(any(e.target == "N2" for e in graph.neighbors("N1")))
        self.assertTrue(any(e.target == "N1" for e in graph.neighbors("N2")))
        strict = build_bayesian_graph(self.s, self.beliefs, blocked_threshold=.1)
        self.assertIsNone(ucs(strict, "N1", "N2"))

    def test_threshold_boundary_and_certain_blockage(self):
        """Equal-to-threshold and certain blockages are excluded; zero excludes all arcs."""
        beliefs = {r.key: {"Open": .8, "Congested": 0, "Blocked": .2} for r in self.s.roads}
        graph = build_bayesian_graph(self.s, beliefs, blocked_threshold=.2)
        self.assertTrue(all(not graph.neighbors(n.id) for n in self.s.nodes))
        graph = build_bayesian_graph(self.s, beliefs, blocked_threshold=.21)
        self.assertEqual(sum(len(graph.neighbors(n.id)) for n in self.s.nodes), len(self.s.roads))
        for row in beliefs.values():
            row.update(Open=0, Congested=0, Blocked=1)
        graph = build_bayesian_graph(self.s, beliefs, blocked_threshold=1)
        self.assertTrue(all(not graph.neighbors(n.id) for n in self.s.nodes))
        graph = build_bayesian_graph(self.s, self.beliefs, blocked_threshold=0)
        self.assertTrue(all(not graph.neighbors(n.id) for n in self.s.nodes))

    def test_invalid_thresholds_and_beliefs(self):
        """Invalid policy inputs fail rather than silently weakening road-risk constraints."""
        for threshold in (-.1, 1.1, float("nan"), float("inf"), True, None):
            with self.assertRaises(ValueError):
                build_bayesian_graph(self.s, self.beliefs, blocked_threshold=threshold)
        for row in ({"Open": 1}, {"Open": .5, "Congested": .5, "Blocked": .5},
                    {"Open": -1, "Congested": 1, "Blocked": 1},
                    {"Open": True, "Congested": 0, "Blocked": 0},
                    {"Open": float("nan"), "Congested": 0, "Blocked": 0}):
            bad = copy.deepcopy(self.beliefs)
            bad[next(iter(bad))] = row
            with self.assertRaises(ValueError):
                build_bayesian_graph(self.s, bad, blocked_threshold=.2)
        bad = dict(self.beliefs)
        bad.pop(next(iter(bad)))
        with self.assertRaises(ValueError):
            build_bayesian_graph(self.s, bad, blocked_threshold=.2)

    def test_zero_route_repeated_roads_and_invalid_path(self):
        """Bounds cover distinct static roads, not every repeated visit as a new event."""
        zero = route_blockage_bounds(self.s, self.beliefs, Route(("N1",), (), 0))
        self.assertEqual((zero.lower, zero.upper), (0, 0))
        route = Route(("H1", "N1", "H1", "N1"), ("H1->N1", "N1->H1", "H1->N1"), 0)
        bounds = route_blockage_bounds(self.s, self.beliefs, route)
        self.assertAlmostEqual(bounds.upper, .27)  # Two distinct directed roads.
        for invalid in (Route((), (), 0), Route(("H1", "N1"), (), 0),
                        Route(("X",), (), 0), Route(("N1", "H1"), ("H1->N1",), 0)):
            with self.assertRaises(ValueError):
                route_blockage_bounds(self.s, self.beliefs, invalid)

    def test_edge_threshold_is_not_route_risk_cap(self):
        """Two accepted .15-risk edges can have independent joint blockage risk .2775."""
        s = replace(self.s, nodes=tuple(Node(n, n, 0, 0, "normal") for n in ("A", "B", "C")),
                    roads=(Road("A", "B", 10, 1, "main"), Road("B", "C", 10, 1, "main")))
        beliefs = {r.key: {"Open": .85, "Congested": 0, "Blocked": .15} for r in s.roads}
        route = ucs(build_bayesian_graph(s, beliefs, blocked_threshold=.2), "A", "C")
        bounds = route_blockage_bounds(s, beliefs, route)
        self.assertAlmostEqual(bounds.lower, .15)
        self.assertAlmostEqual(bounds.upper, .3)
        independent_example = 1 - .85**2
        self.assertGreater(independent_example, .2)
        self.assertLessEqual(independent_example, bounds.upper)

    def test_all_pairs_bayesian_graph_against_independent_relaxation(self):
        """Check all 845 pair costs/unreachability in threshold-.2 snapshots against Bellman-Ford."""
        for directory in sorted((ROOT / "Scenarios").glob("Scenario*")):
            s = load_scenario(directory)
            graph = build_bayesian_graph(s, infer_scenario(s), blocked_threshold=.2)
            edges = [(n.id, e.target, e.seconds) for n in s.nodes for e in graph.neighbors(n.id)]
            for start in (n.id for n in s.nodes):
                costs = {n.id: float("inf") for n in s.nodes}
                costs[start] = 0
                for _ in range(len(s.nodes)-1):
                    for a, b, cost in edges:
                        costs[b] = min(costs[b], costs[a]+cost)
                for goal, expected in costs.items():
                    route = ucs(graph, start, goal)
                    if expected == float("inf"):
                        self.assertIsNone(route)
                    else:
                        self.assertAlmostEqual(route.seconds, expected)

    def test_fastest_accepted_route_is_not_necessarily_safest(self):
        """UCS optimizes the conditional-time score; it does not minimize blockage risk."""
        s = replace(self.s, nodes=tuple(Node(n, n, 0, 0, "normal") for n in ("A", "B", "C")),
                    roads=(Road("A", "C", 1, 1, "main"), Road("A", "B", 3, 1, "main"),
                           Road("B", "C", 3, 1, "main")))
        beliefs = {r.key: {"Open": .99, "Congested": 0, "Blocked": .01} for r in s.roads}
        beliefs[("A", "C")] = {"Open": .81, "Congested": 0, "Blocked": .19}
        route = ucs(build_bayesian_graph(s, beliefs, blocked_threshold=.2), "A", "C")
        self.assertEqual(route.nodes, ("A", "C"))
        self.assertAlmostEqual(route_blockage_bounds(s, beliefs, route).lower, .19)
        detour = Route(("A", "B", "C"), ("A->B", "B->C"), 6)
        self.assertAlmostEqual(route_blockage_bounds(s, beliefs, detour).upper, .02)


class CLITests(unittest.TestCase):
    """Exercise the public CLI, including JSON risk explanations and explicit policy input."""

    def test_bayesian_cli_preserves_full_beliefs(self):
        """The CLI emits distributions, conditional cost, detour and honest risk bounds."""
        output = io.StringIO()
        args = ["run.py", str(ROOT / "Scenarios/Scenario1"), "--route", "N1", "N2",
                "--routing-policy", "bayesian", "--block-threshold", ".2"]
        with patch("sys.argv", args), contextlib.redirect_stdout(output):
            run.main()
        result = json.loads(output.getvalue())
        self.assertEqual(len(result["road_beliefs"]), 14)
        self.assertEqual(result["route"]["nodes"], ["N1", "H1", "N2"])
        self.assertAlmostEqual(result["route_blockage_bounds"]["upper"], .27)
        self.assertIn("conditional", result["cost_interpretation"])
        output = io.StringIO()
        args[-1] = ".1"
        with patch("sys.argv", args), contextlib.redirect_stdout(output):
            run.main()
        result = json.loads(output.getvalue())
        self.assertIsNone(result["route"])
        self.assertIsNone(result["route_blockage_bounds"])

    def test_cli_rejects_implicit_or_ignored_threshold(self):
        """A Bayesian route requires an explicit threshold; baseline may not silently ignore one."""
        for options in (["--route", "N1", "N2", "--routing-policy", "bayesian"],
                        ["--block-threshold", ".2"],
                        ["--routing-policy", "bayesian"]):
            with patch("sys.argv", ["run.py", str(ROOT / "Scenarios/Scenario1"), *options]), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    run.main()


if __name__ == "__main__":
    unittest.main()
