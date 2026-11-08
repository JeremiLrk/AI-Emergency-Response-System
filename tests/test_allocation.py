"""Approved objective, snapshot boundary and deterministic solver-status tests.

unittest supplies self. Fixtures are immutable and need no future incident input.
Successful tests return None and preserve inputs; mocked statuses exercise fallback
branches without hoping that a machine happens to time out during a tiny solve.
"""
import copy
from dataclasses import replace
from itertools import product
from math import ceil
from pathlib import Path
import unittest
from unittest.mock import patch

from emergency_response.allocation import CspDispatcher, AllocationError, PRIORITY_ORDER, validate_snapshot
from emergency_response.baseline import NearestDispatcher
from emergency_response.bayesian import infer_scenario
from emergency_response.loaders import load_scenario
from emergency_response.models import Incident
from emergency_response.risk_routing import build_bayesian_graph
from emergency_response.search import Route
from emergency_response.simulation import simulate
from emergency_response.simulation_models import (AssignmentRequest, Candidate,
    DecisionSnapshot, IncidentView, ResponderView)

ROOT = Path(__file__).resolve().parents[1]


def snapshot(pairs, *, priorities=None, deadlines=None, releases=None, now=0, strict=True):
    """Construct a hand-checkable snapshot from (responder,incident,travel) triples.

    Parameters: pairs define eligible edges; optional dicts specify incident labels/
        absolute deadlines/releases; now is current seconds; strict sets policy.
    Preconditions: nonnegative durations, consistent per-incident metadata.
    Postconditions: fresh frozen views/candidates with First aid capability and
        zero treatment, independent of original scenario files or graph code.
    """
    priorities, deadlines, releases = priorities or {}, deadlines or {}, releases or {}
    ids = sorted({i for r, i, t in pairs})
    views = tuple(IncidentView(Incident(i, f"dest_{i}", priorities.get(i, "High"),
        deadlines.get(i, 10000), "First aid", releases.get(i, 0), 0), "pending", "not_due") for i in ids)
    responders = tuple(ResponderView(r, frozenset({"First aid"}), "available", f"start_{r}", now, None)
                       for r in sorted({r for r, i, t in pairs}))
    candidates = tuple(Candidate(r, i, Route((f"start_{r}", f"dest_{i}"), (f"{r}->{i}",), travel),
        now+travel, now+travel, now+travel <= deadlines.get(i, 10000)) for r, i, travel in pairs)
    return DecisionSnapshot(now, responders, views, candidates, strict)


def objective(view, requests):
    """Evaluate the approved lexicographic vector independently of model construction.

    Parameters: view is current snapshot; requests are a compatible chosen batch.
    Preconditions: every request is a valid candidate; used by exhaustive tests.
    Postconditions: integer tuple (priority counts, optional on-time counts,
        negative summed ceil-millisecond response), without deadline ranking.
    """
    inputs = {v.incident.id: v.incident for v in view.incidents}
    pairs = {(c.responder_id, c.incident_id): c for c in view.candidates}
    chosen = [pairs[(r.responder_id, r.incident_id)] for r in requests]
    counts = tuple(sum(inputs[c.incident_id].priority == p for c in chosen) for p in PRIORITY_ORDER)
    on_time = tuple(sum(c.on_time and inputs[c.incident_id].priority == p for c in chosen) for p in PRIORITY_ORDER)
    cost = sum(ceil((c.arrival_time-inputs[c.incident_id].timestamp)*1000) for c in chosen)
    return counts + (() if view.strict_deadlines else on_time) + (-cost,)


class FakeSolver:
    """Minimal scripted status outcome; invalid value reads fail the tests.

    Parameters: cp is actual enum namespace; selected chooses every x or none;
        readable allows value access only for simulated feasible outcomes.
    Preconditions: tests use one pair so all-selected is compatible.
    Postconditions: records value reads, supplies deterministic status/bound/time.
    """
    def __init__(self, cp, *, selected=True, readable=True):
        """Set fake state; self receives cp enum namespace and boolean flags.

        Preconditions: used only by unit tests. Postconditions: zero value calls.
        """
        self.cp, self.selected, self.readable = cp, selected, readable
        self.value_calls = 0
        self.best_objective_bound = 1
        self.wall_time = 0

    def status_name(self, status):
        """Return enum name; self is fake and status is a CP-SAT status value.

        Preconditions: actual enum provided. Postconditions: string result only.
        """
        return {self.cp.OPTIMAL: "OPTIMAL", self.cp.FEASIBLE: "FEASIBLE",
                self.cp.UNKNOWN: "UNKNOWN", self.cp.INFEASIBLE: "INFEASIBLE",
                self.cp.MODEL_INVALID: "MODEL_INVALID"}[status]

    def value(self, variable):
        """Read one fake Boolean; variable is a model variable unused by this fake.

        Preconditions: readable must be True. Postconditions: counts access and
        returns 0/1, or raises if production code improperly reads UNKNOWN values.
        """
        if not self.readable:
            raise AssertionError("Read solver values without feasible solution")
        self.value_calls += 1
        return int(self.selected)


class AllocationTests(unittest.TestCase):
    """Check assignment constraints and the user-approved objective hierarchy."""

    def test_priority_beats_shorter_lower_priority_response(self):
        """Critical gets selected despite much faster High; empty assignment cannot win."""
        view = snapshot([("R", "critical", 50), ("R", "high", 1)],
                        priorities={"critical": "Critical"})
        self.assertEqual(CspDispatcher()(view), (AssignmentRequest("R", "critical"),))
        self.assertEqual(NearestDispatcher()(view), (AssignmentRequest("R", "high"),))

    def test_no_deadline_ranking_before_response(self):
        """Both High candidates meet deadlines; later-deadline shorter response wins."""
        view = snapshot([("R", "early", 8), ("R", "later", 1)], deadlines={"early": 10, "later": 100})
        self.assertEqual(CspDispatcher()(view), (AssignmentRequest("R", "later"),))

    def test_coverage_before_response_preserves_flexible_responder(self):
        """Two assignments beat nearest greedy's one; exact pairing is optimized jointly."""
        view = snapshot([("R1", "I1", 1), ("R1", "I2", 2), ("R2", "I1", 3)])
        selected = CspDispatcher()(view)
        self.assertEqual(set(selected), {AssignmentRequest("R1", "I2"), AssignmentRequest("R2", "I1")})
        self.assertEqual(len(NearestDispatcher()(view)), 1)

    def test_choose_faster_responder_for_same_incident(self):
        """At most one responder handles I; its smaller response estimate wins."""
        view = snapshot([("R1", "I", 9), ("R2", "I", 2)])
        self.assertEqual(CspDispatcher()(view), (AssignmentRequest("R2", "I"),))

    def test_response_includes_waiting_not_only_travel(self):
        """Approved response objective includes arrival-release, without an aging bonus."""
        view = snapshot([("R", "old", 1), ("R", "new", 2)],
                        now=100, releases={"old": 0, "new": 100})
        self.assertEqual(CspDispatcher()(view), (AssignmentRequest("R", "new"),))

    def test_late_mode_prefers_on_time_after_equal_priority_coverage(self):
        """On-time count beats faster late response only after priority coverage is fixed."""
        view = snapshot([("R", "late", 1), ("R", "timely", 5)],
                        deadlines={"late": 0, "timely": 10}, strict=False)
        self.assertEqual(CspDispatcher()(view), (AssignmentRequest("R", "timely"),))

    def test_late_critical_coverage_still_precedes_high_on_time(self):
        """The approved hierarchy does not silently prioritize High on-time over Critical coverage."""
        view = snapshot([("R", "critical", 2), ("R", "high", 0)], priorities={"critical": "Critical"},
                        deadlines={"critical": 1}, strict=False)
        self.assertEqual(CspDispatcher()(view), (AssignmentRequest("R", "critical"),))

    def test_no_candidates_is_not_timeout(self):
        """No eligible pair yields a trivially optimal empty assignment and explicit status."""
        dispatcher = CspDispatcher()
        self.assertEqual(dispatcher(snapshot([])), ())
        self.assertEqual(dispatcher.diagnostics[-1].status, "NO_CANDIDATES")
        self.assertTrue(dispatcher.diagnostics[-1].lexicographic_optimal)

    def test_exhaustive_small_models_match_full_objective_vector(self):
        """Independent subset enumeration verifies coverage/on-time/response and exclusivity."""
        for strict in (True, False):
            view = snapshot([("R1", "I1", 4), ("R1", "I2", 1), ("R2", "I1", 2),
                             ("R2", "I3", 5), ("R3", "I2", 6)],
                            priorities={"I1": "Critical", "I3": "Low"},
                            deadlines={"I2": 3} if not strict else {}, strict=strict)
            scores = []
            for bits in product((0, 1), repeat=len(view.candidates)):
                chosen = [c for c, bit in zip(view.candidates, bits) if bit]
                if len({c.responder_id for c in chosen}) != len(chosen) or len({c.incident_id for c in chosen}) != len(chosen):
                    continue
                scores.append(objective(view, [AssignmentRequest(c.responder_id, c.incident_id) for c in chosen]))
            self.assertEqual(objective(view, CspDispatcher()(view)), max(scores))

    def test_invalid_snapshots_and_no_input_mutation(self):
        """Reject future records, busy/capability mismatches, duplicates and inconsistent timing."""
        view = snapshot([("R", "I", 2)])
        original = copy.deepcopy(view)
        CspDispatcher()(view)
        self.assertEqual(view, original)
        bad_views = [
            replace(view, candidates=view.candidates*2),
            replace(view, responders=(replace(view.responders[0], status="travelling"),)),
            replace(view, responders=(replace(view.responders[0], available_at=10),)),
            replace(view, responders=(replace(view.responders[0], capabilities=frozenset()),)),
            replace(view, incidents=(replace(view.incidents[0], incident=replace(view.incidents[0].incident, timestamp=1)),)),
            replace(view, candidates=(replace(view.candidates[0], arrival_time=3),)),
            replace(view, candidates=(replace(view.candidates[0], on_time=False),)),
        ]
        for bad in bad_views:
            with self.assertRaises(ValueError):
                CspDispatcher()(bad)

    def test_settings_and_integer_limits_checked(self):
        """Invalid budgets/precision cannot become misleading optimal no-work outcomes."""
        for budget in (-1, True, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                CspDispatcher(time_limit_seconds=budget)
        for scale in (0, True, 1.5):
            with self.assertRaises(ValueError):
                CspDispatcher(response_scale=scale)
        view = snapshot([("R", "I", 1e17)], deadlines={"I": 1e18})
        with self.assertRaisesRegex(ValueError, "integer precision"):
            CspDispatcher()(view)

    def test_zero_budget_is_visible_and_does_not_read_values(self):
        """Zero limit deterministically tests no-incumbent fallback, not random timing."""
        dispatcher = CspDispatcher(time_limit_seconds=0)
        with patch.object(dispatcher, "_solve_phase") as solve:
            self.assertEqual(dispatcher(snapshot([("R", "I", 1)])), ())
        solve.assert_not_called()
        diagnostic = dispatcher.diagnostics[-1]
        self.assertEqual((diagnostic.status, diagnostic.fallback_reason),
                         ("BUDGET_EXHAUSTED", "no_incumbent_available"))
        self.assertFalse(diagnostic.lexicographic_optimal)

    def test_unknown_without_incumbent_never_reads_values(self):
        """UNKNOWN has no usable values; return empty with a warning diagnostic."""
        dispatcher = CspDispatcher()
        solver = FakeSolver(dispatcher.cp, readable=False)
        with patch.object(dispatcher, "_solve_phase", return_value=(solver, dispatcher.cp.UNKNOWN)):
            self.assertEqual(dispatcher(snapshot([("R", "I", 1)])), ())
        self.assertEqual(solver.value_calls, 0)
        self.assertEqual(dispatcher.diagnostics[-1].status, "UNKNOWN")

    def test_unknown_retains_previous_valid_incumbent(self):
        """Failure at response stage retains proven coverage solution, not UNKNOWN values."""
        dispatcher = CspDispatcher()
        first = FakeSolver(dispatcher.cp)
        unknown = FakeSolver(dispatcher.cp, readable=False)
        with patch.object(dispatcher, "_solve_phase", side_effect=[
                (first, dispatcher.cp.OPTIMAL), (unknown, dispatcher.cp.UNKNOWN)]):
            result = dispatcher(snapshot([("R", "I", 1)]))
        self.assertEqual(result, (AssignmentRequest("R", "I"),))
        self.assertEqual(dispatcher.diagnostics[-1].fallback_reason, "previous_incumbent_retained")
        self.assertFalse(dispatcher.diagnostics[-1].lexicographic_optimal)

    def test_feasible_stops_without_claiming_optimal_priority_counts(self):
        """Do not freeze a merely feasible objective and continue lower priorities."""
        dispatcher = CspDispatcher()
        solver = FakeSolver(dispatcher.cp)
        with patch.object(dispatcher, "_solve_phase", return_value=(solver, dispatcher.cp.FEASIBLE)) as solve:
            result = dispatcher(snapshot([("R", "I", 1)]))
        self.assertEqual(len(result), 1)
        self.assertEqual(solve.call_count, 1)
        self.assertFalse(dispatcher.diagnostics[-1].lexicographic_optimal)

    def test_budget_is_shared_across_phases(self):
        """Time spent on a proven first phase cannot grant a fresh full second budget."""
        dispatcher = CspDispatcher(time_limit_seconds=1)
        solver = FakeSolver(dispatcher.cp)
        with patch("emergency_response.allocation.monotonic", side_effect=[0, 0, 2]), \
             patch.object(dispatcher, "_solve_phase", return_value=(solver, dispatcher.cp.OPTIMAL)) as solve:
            result = dispatcher(snapshot([("R", "I", 1)]))
        self.assertEqual(len(result), 1)
        self.assertEqual(solve.call_count, 1)
        self.assertEqual(dispatcher.diagnostics[-1].status, "BUDGET_EXHAUSTED")

    def test_invalid_or_infeasible_status_is_a_visible_error(self):
        """Optional assignment model must never quietly equate infeasibility with unhandled work."""
        for name in ("INFEASIBLE", "MODEL_INVALID"):
            dispatcher = CspDispatcher()
            solver = FakeSolver(dispatcher.cp, readable=False)
            with patch.object(dispatcher, "_solve_phase", return_value=(solver, getattr(dispatcher.cp, name))):
                with self.assertRaises(AllocationError):
                    dispatcher(snapshot([("R", "I", 1)]))
            self.assertEqual(dispatcher.diagnostics[-1].status, name)

    def test_model_validation_error_is_reported_before_solving(self):
        """An invalid integer model is an implementation error, not a timeout fallback."""
        dispatcher = CspDispatcher()
        with patch.object(dispatcher.cp.CpModel, "validate", return_value="test invalid model"), \
             patch.object(dispatcher, "_solve_phase") as solve:
            with self.assertRaises(AllocationError):
                dispatcher(snapshot([("R", "I", 1)]))
        solve.assert_not_called()


class ActualAllocationTests(unittest.TestCase):
    """Use actual scenario snapshots and independently replay complete online runs."""

    def test_scenario1_initial_priority_conflict_and_busy_responder(self):
        """R2 goes to Critical I4, not the shorter High I1; initially busy R4 is unused."""
        s = load_scenario(ROOT / "Scenarios/Scenario1")
        graph = build_bayesian_graph(s, infer_scenario(s), blocked_threshold=.2)
        initial = []
        def collect(view):
            if view.time == 0:
                initial.append(view)
            return ()
        simulate(s, graph, collect)
        chosen = CspDispatcher()(initial[0])
        self.assertEqual(set(chosen), {AssignmentRequest("R1", "I2"),
            AssignmentRequest("R2", "I4"), AssignmentRequest("R3", "I3")})

    def test_scenario2_choice_between_two_responders_and_police_conflict(self):
        """Choose R7 or R8 for I4, one only; R10 handles Critical I3 over High I2."""
        s = load_scenario(ROOT / "Scenarios/Scenario2")
        graph = build_bayesian_graph(s, infer_scenario(s), blocked_threshold=.2)
        initial = []
        def collect(view):
            if view.time == 0:
                initial.append(view)
            return ()
        simulate(s, graph, collect)
        view = initial[0]
        chosen = CspDispatcher()(view)
        self.assertIn(AssignmentRequest("R10", "I3"), chosen)
        self.assertNotIn(AssignmentRequest("R10", "I2"), chosen)
        self.assertEqual(sum(r.incident_id == "I4" for r in chosen), 1)
        self.assertTrue(any(r.incident_id == "I4" and r.responder_id in {"R7", "R8"} for r in chosen))
        # Seven candidate pairs make exhaustive verification inexpensive (128 subsets).
        scores = []
        for bits in product((0, 1), repeat=len(view.candidates)):
            selected = [c for c, bit in zip(view.candidates, bits) if bit]
            if len({c.responder_id for c in selected}) == len(selected) == len({c.incident_id for c in selected}):
                scores.append(objective(view, [AssignmentRequest(c.responder_id, c.incident_id) for c in selected]))
        self.assertEqual(objective(view, chosen), max(scores))

    def test_all_scenarios_online_boundary_independent_replay_and_metrics(self):
        """Both policies/modes preserve releases, capability, locations, occupancy and statistics."""
        from emergency_response.statistics import summarize
        for directory in sorted((ROOT / "Scenarios").glob("Scenario*")):
            s = load_scenario(directory)
            graph = build_bayesian_graph(s, infer_scenario(s), blocked_threshold=.2)
            for strict in (True, False):
                for policy in (CspDispatcher(time_limit_seconds=10), NearestDispatcher()):
                    def dispatch(view):
                        self.assertTrue(all(v.incident.timestamp <= view.time for v in view.incidents))
                        self.assertFalse(hasattr(view, "scenario"))
                        return policy(view)
                    result = simulate(s, graph, dispatch, strict_deadlines=strict)
                    ready = {r.id: r.time_until_available for r in s.responders}
                    location = {r.id: r.start_location for r in s.responders}
                    people, incidents = {r.id: r for r in s.responders}, {i.id: i for i in s.incidents}
                    handled, response_times = set(), []
                    for a in result.assignments:
                        i, r = incidents[a.incident_id], people[a.responder_id]
                        self.assertNotIn(i.id, handled)
                        self.assertIn(i.required_capability, r.capabilities)
                        self.assertGreaterEqual(a.departure_time, max(i.timestamp, ready[r.id]))
                        self.assertEqual((a.route.nodes[0], a.route.nodes[-1]), (location[r.id], i.location))
                        duration = sum(next(e.seconds for e in graph.neighbors(n) if e.target == m and e.road_id == road)
                                       for n, m, road in zip(a.route.nodes, a.route.nodes[1:], a.route.roads))
                        self.assertAlmostEqual(a.arrival_time, a.departure_time+duration)
                        self.assertAlmostEqual(a.completion_time, a.arrival_time+i.time_required)
                        if strict:
                            self.assertLessEqual(a.arrival_time, i.deadline)
                        ready[r.id], location[r.id] = a.completion_time, i.location
                        handled.add(i.id)
                        response_times.append(a.arrival_time-i.timestamp)
                    metrics = summarize(result)
                    self.assertEqual(metrics.handled, len(handled))
                    self.assertEqual(metrics.total_incidents, len(s.incidents))
                    self.assertAlmostEqual(metrics.average_response_seconds, sum(response_times)/len(response_times))
                    if isinstance(policy, CspDispatcher):
                        self.assertTrue(all(d.lexicographic_optimal for d in policy.diagnostics))


if __name__ == "__main__":
    unittest.main()
