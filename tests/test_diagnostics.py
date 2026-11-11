"""Observed explanations must never change planning or claim global impossibility.

unittest supplies self; fixtures are isolated copies of actual scenario inputs.
Each test returns None on success. Assertions check evidence and execution together.
"""
from dataclasses import asdict, replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from emergency_response.allocation import CspDispatcher
from emergency_response.bayesian import infer_scenario
from emergency_response.diagnostics import render_explanations
from emergency_response.hmm import infer_traffic
from emergency_response.loaders import load_scenario
from emergency_response.outputs import make_plan, write_outputs
from emergency_response.risk_routing import build_bayesian_graph
from emergency_response.search import ucs
from emergency_response.simulation import simulate
from emergency_response.simulation_models import AssignmentRequest
from emergency_response.statistics import summarize
from emergency_response.traffic_routing import TrafficRouter
from test_simulation import fixture, incident, responder

ROOT = Path(__file__).resolve().parents[1]


class DiagnosticTests(unittest.TestCase):
    def test_reason_changes_from_busy_to_late(self):
        scenario, graph = fixture([incident(deadline=7)], [responder(ready=5, busy=True)])
        result = simulate(scenario, graph, CspDispatcher())
        explanation, = result.unhandled_explanations
        checks = [d.checks[0] for d in explanation.decisions]
        self.assertEqual([c.reason for c in checks], ["busy", "late", "late"])
        self.assertIsNone(checks[0].route_exists)
        self.assertIsNone(checks[0].arrival_time)
        self.assertEqual(checks[0].available_at, 5)
        self.assertEqual(checks[1].required_capability, "First aid")
        self.assertEqual(explanation.earliest_checked_arrival, 10)
        self.assertEqual(explanation.earliest_decision_time, 5)
        self.assertFalse(explanation.ever_eligible_on_time)
        text = "\n".join(render_explanations((explanation,)))
        self.assertIn("Too late by: 3.0 seconds", text)
        self.assertIn("right skill were busy", text)
        self.assertNotIn("eligible on-time candidate", text)
        self.assertLess(len(text.splitlines()), 18)

    def test_eligible_on_time_candidate_loses_competing_assignment(self):
        critical = replace(incident("C", deadline=6, treatment=20), priority="Critical")
        scenario, graph = fixture([critical, incident("H", deadline=6)])
        result = simulate(scenario, graph, CspDispatcher())
        self.assertEqual([a.incident_id for a in result.assignments], ["C"])
        explanation, = result.unhandled_explanations
        first = explanation.decisions[0]
        self.assertTrue(explanation.ever_eligible_on_time)
        self.assertEqual(first.checks[0].reason, "eligible")
        self.assertEqual(first.selected_assignments, (("R", "C"),))
        self.assertEqual(first.allocator_status, "OPTIMAL")
        self.assertTrue(first.optimal)
        text = "\n".join(render_explanations((explanation,)))
        self.assertIn("R was assigned to C instead", text)
        self.assertIn("Different earlier assignments", text)

    def test_missing_skill_and_disconnected_route_are_distinct(self):
        scenario, graph = fixture([incident("skill", capability="CPR"), incident("road", location="C")])
        result = simulate(scenario, graph, CspDispatcher())
        explanations = {e.incident_id: e for e in result.unhandled_explanations}
        self.assertEqual(explanations["skill"].decisions[0].checks[0].reason, "lacks_capability")
        self.assertIsNone(explanations["skill"].decisions[0].checks[0].route_exists)
        self.assertFalse(explanations["road"].decisions[0].checks[0].route_exists)
        self.assertIsNone(explanations["road"].earliest_checked_arrival)

    def test_no_responders_still_records_actual_decisions(self):
        scenario, graph = fixture([incident()], responders=[])
        explanation, = simulate(scenario, graph, CspDispatcher()).unhandled_explanations
        self.assertTrue(explanation.decisions)
        self.assertEqual(explanation.decisions[0].checks, ())
        self.assertIsNone(explanation.earliest_checked_arrival)

    def test_deadline_before_release_has_no_invented_check(self):
        scenario, graph = fixture([incident(timestamp=10, deadline=9)])
        explanation, = simulate(scenario, graph, CspDispatcher()).unhandled_explanations
        self.assertEqual(explanation.decisions, ())
        self.assertIsNone(explanation.earliest_checked_arrival)
        self.assertIn("before any assignment check", "\n".join(render_explanations((explanation,))))

    def test_late_candidate_is_not_called_on_time(self):
        scenario, graph = fixture([incident(deadline=1)])
        result = simulate(scenario, graph, lambda snapshot: (), strict_deadlines=False)
        explanation, = result.unhandled_explanations
        self.assertTrue(explanation.decisions[0].checks[0].eligible)
        self.assertFalse(explanation.ever_eligible_on_time)
        self.assertEqual(explanation.earliest_checked_arrival, 5)
        self.assertIsNone(explanation.decisions[0].allocator_status)
        self.assertEqual(explanation.closure_reason, "no_more_events_unassigned")

    def test_solver_budget_exhaustion_is_visible(self):
        scenario, graph = fixture([incident()])
        result = simulate(scenario, graph, CspDispatcher(time_limit_seconds=0))
        explanation, = result.unhandled_explanations
        self.assertTrue(explanation.ever_eligible_on_time)
        self.assertEqual(explanation.decisions[0].allocator_status, "BUDGET_EXHAUSTED")
        self.assertFalse(explanation.decisions[0].optimal)
        self.assertEqual(explanation.decisions[0].selected_assignments, ())

    def test_no_additional_searches_or_dispatcher_calls(self):
        scenario, graph = fixture([incident()])
        observed = []
        for enabled in (False, True):
            snapshots = []
            def dispatch(snapshot):
                snapshots.append(snapshot)
                return ()
            with patch("emergency_response.simulation.ucs", wraps=ucs) as search:
                result = simulate(scenario, graph, dispatch, record_diagnostics=enabled)
                observed.append((snapshots, search.call_count, result.assignments, result.events))
        self.assertEqual(observed[0], observed[1])

    def test_zero_time_decisions_have_distinct_indices_and_no_future_calls(self):
        scenario, graph = fixture([incident("A", location="A", treatment=0),
                                   incident("B", capability="CPR"),
                                   incident("future", timestamp=10, capability="CPR")])
        def dispatch(snapshot):
            return tuple(AssignmentRequest(c.responder_id, c.incident_id)
                         for c in snapshot.candidates if c.incident_id == "A")
        result = simulate(scenario, graph, dispatch)
        explanations = {e.incident_id: e for e in result.unhandled_explanations}
        first_two = explanations["B"].decisions[:2]
        self.assertEqual([d.time for d in first_two], [0, 0])
        self.assertEqual([d.index for d in first_two], [0, 1])
        self.assertTrue(all(d.time >= 10 for d in explanations["future"].decisions))
        self.assertFalse(any(d.time > 100 for d in explanations["B"].decisions))

    def test_exports_add_diagnostics_without_changing_plan_or_metrics(self):
        scenario, graph = fixture([incident(deadline=1)])
        result = simulate(scenario, graph, CspDispatcher())
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
            exported = write_outputs(scenario, result, directory)
            text = Path(exported["statistics"]).read_text(encoding="utf-8")
            self.assertIn("Why incidents were not handled", text)
            self.assertIn("Arrival deadline: 1.0 seconds", text)
            self.assertEqual(make_plan(result), [])
            self.assertEqual(exported["validation"]["statistics"], asdict(summarize(result)))

    def test_all_three_scenarios_recording_on_off_are_identical(self):
        for number in (1, 2, 3):
            scenario = load_scenario(ROOT / f"Scenarios/Scenario{number}")
            graph = build_bayesian_graph(scenario, infer_scenario(scenario), blocked_threshold=.2)
            traffic = infer_traffic(scenario)
            for strict in (True, False):
                with self.subTest(scenario=number, strict=strict):
                    results = [simulate(scenario, graph, CspDispatcher(), strict_deadlines=strict,
                        record_diagnostics=enabled, route_planner=TrafficRouter(
                            scenario.roads, traffic, policy="bounded", max_extra_fraction=.05,
                            min_exposure_reduction=.10)) for enabled in (False, True)]
                    self.assertEqual(replace(results[1], unhandled_explanations=()), results[0])
                    self.assertEqual(summarize(results[0]), summarize(results[1]))
                    self.assertEqual(make_plan(results[0]), make_plan(results[1]))
                    self.assertEqual(len(results[1].unhandled_explanations), summarize(results[1]).unhandled)

    def test_recording_flag_requires_bool(self):
        scenario, graph = fixture([incident()])
        with self.assertRaises(ValueError):
            simulate(scenario, graph, lambda snapshot: (), record_diagnostics=1)
