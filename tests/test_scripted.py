"""Script parsing and public CLI integration, with no allocator implementation.

unittest supplies self. Preconditions: scenario/example files readable; tests may
create temporary scripts below tests/. Postconditions on success: expected output
assertions pass, temporary files and patched CLI state are cleaned up; source
scenario files remain unchanged. Test helpers document their explicit arguments.
"""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import run
from emergency_response.scripted import ScriptedDispatcher, load_script
from emergency_response.simulation_models import AssignmentRequest, DecisionSnapshot

ROOT = Path(__file__).resolve().parents[1]


class ScriptedTests(unittest.TestCase):
    """Check explicit fixture dispatch and modeled-execution CLI behavior."""

    def test_script_consumes_time_once_and_copies_input(self):
        """Zero-event callback repeats must not replay a committed script batch."""
        batch = [AssignmentRequest("R", "I")]
        schedule = {0: batch}
        dispatcher = ScriptedDispatcher(schedule)
        batch.clear()
        view = DecisionSnapshot(0, (), (), (), True)
        self.assertEqual(dispatcher(view), (AssignmentRequest("R", "I"),))
        self.assertEqual(dispatcher(view), ())
        self.assertEqual(dispatcher.decision_times, (0,))

    def test_script_file_groups_simultaneous_dispatches(self):
        """Same-time JSON records form one batch rather than sequential allocations."""
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
            path = Path(directory) / "script.json"
            path.write_text(json.dumps([
                {"time": 2.5, "responder_id": "R1", "incident_id": "I1"},
                {"time": 2.5, "responder_id": "R2", "incident_id": "I2"}]))
            dispatcher = load_script(path)
            self.assertEqual(len(dispatcher(DecisionSnapshot(2.5, (), (), (), True))), 2)

    def test_invalid_script_structure_times_and_ids(self):
        """Reject malformed fixtures before attempting scenario dispatch."""
        for schedule in ([], {True: []}, {-1: []}, {float("nan"): []},
                         {0: [("R", "I")]}, {0: [AssignmentRequest("", "I")]}):
            with self.assertRaises(ValueError):
                ScriptedDispatcher(schedule)
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
            path = Path(directory) / "script.json"
            for value in ({}, [{"time": 0}], [{"time": -1, "responder_id": "R", "incident_id": "I"}]):
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    load_script(path)

    def test_bayesian_simulation_cli_outputs_states_and_deadlines(self):
        """The real example prints full beliefs, commitments, outcomes and modeled-time label."""
        args = ["run.py", str(ROOT / "Scenarios/Scenario1"), "--simulate-script",
                str(ROOT / "examples/scenario1_script.json"), "--routing-policy", "bayesian",
                "--block-threshold", ".2"]
        output = io.StringIO()
        with patch("sys.argv", args), contextlib.redirect_stdout(output):
            run.main()
        result = json.loads(output.getvalue())
        self.assertEqual(len(result["simulation"]["assignments"]), 4)
        self.assertEqual(len(result["road_beliefs"]), 14)
        self.assertEqual(len(result["assignment_blockage_bounds"]), 4)
        self.assertTrue(result["simulation"]["strict_deadlines"])
        self.assertIn("no sampled road truth", result["execution_assumption"])
        self.assertIsInstance(result["simulation"]["responders"][0]["capabilities"], list)

    def test_allow_late_cli_preserves_missed_completed_combination(self):
        """--allow-late changes policy, never changes a missed deadline into success."""
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
            path = Path(directory) / "late.json"
            path.write_text(json.dumps([{"time": 100, "responder_id": "R2", "incident_id": "I1"}]))
            args = ["run.py", str(ROOT / "Scenarios/Scenario1"), "--simulate-script", str(path), "--allow-late"]
            output = io.StringIO()
            with patch("sys.argv", args), contextlib.redirect_stdout(output):
                run.main()
            states = json.loads(output.getvalue())["simulation"]["incidents"]
            incident = next(i for i in states if i["incident"]["id"] == "I1")
            self.assertEqual((incident["status"], incident["deadline_result"]), ("completed", "missed"))

    def test_cli_rejects_conflicting_or_incomplete_simulation_options(self):
        """Simulation arguments cannot silently ignore deadline/risk/route settings."""
        script = str(ROOT / "examples/scenario1_script.json")
        for options in (["--allow-late"], ["--simulate-script", script, "--route", "N1", "N2"],
                        ["--simulate-script", script, "--routing-policy", "bayesian"]):
            with patch("sys.argv", ["run.py", str(ROOT / "Scenarios/Scenario1"), *options]), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    run.main()


if __name__ == "__main__":
    unittest.main()
