"""Metric denominators and new default/compare CLI contract tests.

unittest supplies self. Fixtures/source scenarios must be readable. Context
managers restore CLI/stdout; no production files are written. Successful tests
return None with counts/means asserted independently of solver diagnostics.
"""
import contextlib
import io
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import run
from emergency_response.simulation import simulate
from emergency_response.statistics import summarize
from test_simulation import fixture, incident, scripted

ROOT = Path(__file__).resolve().parents[1]


class StatisticsTests(unittest.TestCase):
    """Avoid rewarding unhandled work or confusing service with response time."""

    def test_empty_run_uses_null_denominators(self):
        """No incidents/completions has no meaningful mean or deadline percentage."""
        s, g = fixture([])
        stats = summarize(simulate(s, g, lambda view: ()))
        self.assertEqual((stats.total_incidents, stats.handled, stats.deadlines_met), (0, 0, 0))
        self.assertIsNone(stats.average_response_seconds)
        self.assertIsNone(stats.deadlines_met_percent_all)
        self.assertIsNone(stats.deadlines_met_percent_handled)

    def test_unhandled_counts_as_not_met_but_not_zero_response(self):
        """No handled incident means N/A average, not a falsely excellent zero mean."""
        s, g = fixture([incident(deadline=2)])
        stats = summarize(simulate(s, g, lambda view: ()))
        self.assertEqual((stats.handled, stats.unhandled, stats.responders_used), (0, 1, 0))
        self.assertIsNone(stats.average_response_seconds)
        self.assertEqual(stats.deadlines_met_percent_all, 0)
        self.assertIsNone(stats.deadlines_met_percent_handled)

    def test_response_includes_dispatch_waiting_excludes_treatment(self):
        """A departure at 3 plus five travel seconds gives response 8, not completion 10."""
        s, g = fixture([incident("I1", deadline=10), incident("I2", deadline=4)])
        stats = summarize(scripted(s, g, {3: [("R", "I1")]}))
        self.assertEqual((stats.total_incidents, stats.handled, stats.deadlines_met), (2, 1, 1))
        self.assertEqual(stats.average_response_seconds, 8)
        self.assertEqual(stats.deadlines_met_percent_all, 50)
        self.assertEqual(stats.deadlines_met_percent_handled, 100)
        self.assertEqual(stats.handled_by_priority["High"], 1)

    def test_late_completion_is_handled_but_not_deadline_success(self):
        """Late work counts as completed treatment without rewriting its missed result."""
        s, g = fixture([incident(deadline=2)])
        stats = summarize(scripted(s, g, {0: [("R", "I")]}, strict_deadlines=False))
        self.assertEqual((stats.handled, stats.deadlines_met), (1, 0))
        self.assertEqual(stats.average_response_seconds, 5)
        self.assertEqual(stats.deadlines_met_percent_handled, 0)


class AutomaticCLITests(unittest.TestCase):
    """Normal mode automatically allocates, while route/script modes remain available."""

    def call_cli(self, options):
        """Run one CLI command and parse captured JSON.

        Parameters: self is test receiver; options is argument list after scenario.
        Preconditions: Scenario1 readable, OR-Tools available for default CSP mode.
        Postconditions: returns decoded output; restores sys.argv and stdout.
        """
        output = io.StringIO()
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory, patch("sys.argv", ["run.py", str(ROOT / "Scenarios/Scenario1"), "--output-dir", directory, *options]), contextlib.redirect_stdout(output):
            run.main()
        return json.loads(output.getvalue())

    def test_default_run_uses_csp_and_reports_statistics(self):
        """No script is needed; normal Bayesian run allocates online with solver diagnostics."""
        result = self.call_cli(["--routing-policy", "bayesian", "--block-threshold", ".2"])
        self.assertEqual(result["allocator"], "csp")
        self.assertEqual(result["statistics"]["handled"], 6)
        self.assertTrue(all(d["lexicographic_optimal"] for d in result["allocation_diagnostics"]))

    def test_compare_runs_same_routing_policy_for_both_allocators(self):
        """CSP/nearest use independent states and identical threshold-.2 routing inputs."""
        result = self.call_cli(["--compare", "--routing-policy", "bayesian", "--block-threshold", ".2"])
        self.assertEqual(result["comparison"]["csp"]["statistics"]["handled"], 6)
        self.assertEqual(result["comparison"]["nearest"]["statistics"]["handled"], 5)

    def test_nearest_and_late_normal_modes_do_not_require_script(self):
        """The previous script-only --allow-late restriction is intentionally removed."""
        result = self.call_cli(["--allocator", "nearest", "--allow-late"])
        self.assertEqual(result["allocator"], "nearest")
        self.assertFalse(result["simulation"]["strict_deadlines"])
        self.assertEqual(result["allocation_diagnostics"], [])

    def test_zero_budget_visible_in_normal_run(self):
        """A no-incumbent budget fallback is recorded, not mislabeled no feasible work."""
        result = self.call_cli(["--solver-time-limit", "0"])
        self.assertEqual(result["statistics"]["handled"], 0)
        self.assertTrue(any(d["status"] == "BUDGET_EXHAUSTED" for d in result["allocation_diagnostics"]))

    def test_cli_rejects_invalid_budget_and_conflicting_allocator_mode(self):
        """Invalid budgets and ignored nearest selections are explicit argument errors."""
        for options in (["--solver-time-limit", "nan"], ["--solver-time-limit", "-1"],
                        ["--compare", "--allocator", "nearest"]):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    self.call_cli(options)


if __name__ == "__main__":
    unittest.main()
