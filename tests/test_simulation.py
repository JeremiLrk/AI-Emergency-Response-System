"""Event timing, information boundary and deadline-policy contract tests.

unittest supplies self to each test. Valid supplied Scenario1 is used as a base
for small isolated fixtures; source files are never changed. On success each test
returns None with its stated assertions satisfied; failures propagate to unittest.
"""
import copy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import unittest

from emergency_response.loaders import load_scenario
from emergency_response.models import Incident, Node, Responder, Road
from emergency_response.routing import build_graph
from emergency_response.bayesian import infer_scenario
from emergency_response.risk_routing import build_bayesian_graph
from emergency_response.scripted import ScriptedDispatcher, load_script
from emergency_response.simulation import simulate, _Simulator
from emergency_response.simulation_models import AssignmentRequest

ROOT = Path(__file__).resolve().parents[1]


def incident(id="I", location="B", timestamp=0, deadline=100, treatment=2,
             capability="First aid"):
    """Build a small incident fixture.

    Parameters: id is unique string; location is destination; timestamp/deadline
        are absolute seconds; treatment is duration; capability is required skill.
    Preconditions: caller supplies nonnegative finite times and known labels/nodes.
    Postconditions: returns a frozen input record without modifying source data.
    """
    return Incident(id, location, "High", deadline, capability, timestamp, treatment)


def responder(id="R", location="A", ready=0, busy=False):
    """Build an ambulance fixture.

    Parameters: id/location identify responder/node; ready is initial remaining
        seconds; busy selects Busy versus Available input state.
    Preconditions: time nonnegative; Available implies zero (unless testing errors).
    Postconditions: returns frozen responder with First aid capability only.
    """
    return Responder(id, "Ambulance", location, frozenset({"First aid"}),
                     "Busy" if busy else "Available", ready)


def fixture(incidents, responders=None, edges=(("A", "B", 5), ("B", "A", 3))):
    """Build a three-node scenario/normal-cost graph for controlled mechanics.

    Parameters: incidents/responders are input record iterables; responders None
        creates one free ambulance; edges are source/target/travel-second triples.
    Preconditions: IDs/nodes/capabilities/times are appropriate for each test.
    Postconditions: returns (scenario, graph); replaces evidence with empty inputs
        rather than retaining unrelated Scenario1 references. No files are changed.
    """
    base = load_scenario(ROOT / "Scenarios/Scenario1")
    s = replace(base,
        nodes=tuple(Node(n, n, 0, 0, "normal") for n in ("A", "B", "C")),
        roads=tuple(Road(a, b, seconds, 1, "main") for a, b, seconds in edges),
        responders=tuple(responders if responders is not None else [responder()]),
        incidents=tuple(incidents), road_reports=(), traffic_history={}, warnings=())
    return s, build_graph(s)


def scripted(s, graph, schedule, **options):
    """Execute one fresh scripted test run.

    Parameters: s/graph are fixture inputs; schedule maps times to (responder,incident)
        pairs; options are simulate keyword arguments such as strict_deadlines.
    Preconditions: script eligibility is checked by the simulator at dispatch.
    Postconditions: returns result or propagates invalid-dispatch errors; no CSP.
    """
    dispatcher = ScriptedDispatcher({time: tuple(AssignmentRequest(*pair) for pair in batch)
                                     for time, batch in schedule.items()})
    return simulate(s, graph, dispatcher, decision_times=dispatcher.decision_times, **options)


class SimulationTests(unittest.TestCase):
    """Verify physical/logical event invariants without optimizing allocation."""

    def test_travel_then_treatment_and_position(self):
        """Travel ends at 5, treatment at 7; availability includes both intervals."""
        s, g = fixture([incident()])
        seen = []
        script = ScriptedDispatcher({0: [AssignmentRequest("R", "I")]})
        def dispatch(view):
            seen.append(view)
            return script(view)
        result = simulate(s, g, dispatch)
        self.assertEqual(result.time, 7)  # Obsolete deadline 100 must not extend horizon.
        self.assertEqual((result.incidents[0].arrival_time, result.incidents[0].completion_time), (5, 7))
        self.assertEqual((result.incidents[0].status, result.incidents[0].deadline_result), ("completed", "met"))
        self.assertEqual((result.responders[0].status, result.responders[0].location), ("available", "B"))
        during = next(v for v in seen if v.time == 5)
        self.assertEqual((during.responders[0].status, during.responders[0].location), ("treating", "B"))
        self.assertEqual(during.candidates, ())

    def test_future_incidents_are_absent_and_views_are_frozen(self):
        """No snapshot/candidate reveals input before release; snapshots cannot mutate state."""
        s, g = fixture([incident("I1", timestamp=5, treatment=0),
                        incident("I2", timestamp=10, treatment=0)])
        seen = []
        def dispatch(view):
            seen.append(view)
            self.assertFalse(hasattr(view, "scenario"))
            self.assertFalse(hasattr(view, "queue"))
            ids = {v.incident.id for v in view.incidents}
            self.assertTrue(all(v.incident.timestamp <= view.time for v in view.incidents))
            self.assertTrue(all(c.incident_id in ids for c in view.candidates))
            with self.assertRaises(FrozenInstanceError):
                view.time = 999
            with self.assertRaises(FrozenInstanceError):
                view.responders[0].status = "available"
            return [AssignmentRequest(c.responder_id, c.incident_id) for c in view.candidates[:1]]
        result = simulate(s, g, dispatch)
        self.assertEqual(seen[0].incidents, ())
        self.assertTrue(all(v.incident.id != "I2" for snap in seen if snap.time < 10 for v in snap.incidents))
        self.assertEqual(len(result.assignments), 2)

    def test_simultaneous_releases_are_batched_regardless_of_input_order(self):
        """At time 5 both incidents are visible to the first dispatch call."""
        s, g = fixture([incident("I2", timestamp=5), incident("I1", timestamp=5)],
                        [responder("R1"), responder("R2")])
        seen = []
        script = ScriptedDispatcher({5: [AssignmentRequest("R1", "I1"), AssignmentRequest("R2", "I2")]})
        def dispatch(view):
            seen.append(view)
            return script(view)
        result = simulate(s, g, dispatch)
        at_five = next(v for v in seen if v.time == 5)
        self.assertEqual({v.incident.id for v in at_five.incidents}, {"I1", "I2"})
        self.assertEqual(len(result.assignments), 2)

    def test_completion_and_release_same_time_use_updated_location(self):
        """First job ends at 7 in B; new job at 7 routes from B, not station A."""
        s, g = fixture([incident("I1"), incident("I2", location="A", timestamp=7, treatment=0)])
        result = scripted(s, g, {0: [("R", "I1")], 7: [("R", "I2")]})
        self.assertEqual(result.assignments[1].route.nodes, ("B", "A"))
        self.assertEqual(result.assignments[1].arrival_time, 10)
        events = [e.kind for e in result.events if e.time == 7]
        self.assertLess(events.index("completion"), events.index("dispatch"))
        self.assertLess(events.index("release"), events.index("dispatch"))

    def test_initial_busy_and_unknown_position_until_ready(self):
        """An initially busy responder is released at its supplied start node."""
        s, g = fixture([incident()], [responder(ready=10, busy=True)])
        seen = []
        script = ScriptedDispatcher({10: [AssignmentRequest("R", "I")]})
        def dispatch(view):
            seen.append(view)
            return script(view)
        result = simulate(s, g, dispatch)
        self.assertEqual((seen[0].responders[0].status, seen[0].responders[0].location),
                         ("initially_busy", None))
        self.assertEqual(seen[0].candidates, ())
        self.assertEqual(result.assignments[0].departure_time, 10)
        self.assertEqual(result.assignments[0].arrival_time, 15)

    def test_initial_busy_zero_is_ready_before_zero_dispatch(self):
        """Busy with zero remaining time is released before decisions at zero."""
        s, g = fixture([incident(location="A", deadline=0, treatment=0)],
                        [responder(ready=0, busy=True)])
        result = scripted(s, g, {0: [("R", "I")]})
        self.assertEqual(result.time, 0)
        self.assertEqual(result.incidents[0].deadline_result, "met")

    def test_multiple_zero_jobs_at_exact_deadline_terminate(self):
        """Same-node zero-service jobs can chain at one timestamp before deadline expiry."""
        s, g = fixture([incident(str(i), "A", timestamp=5, deadline=5, treatment=0) for i in range(4)])
        calls = []
        def dispatch(view):
            calls.append(view.time)
            return [AssignmentRequest(c.responder_id, c.incident_id) for c in view.candidates[:1]]
        result = simulate(s, g, dispatch)
        self.assertEqual(len(result.assignments), 4)
        self.assertEqual(result.time, 5)
        self.assertTrue(all(i.status == "completed" and i.deadline_result == "met" for i in result.incidents))
        self.assertLess(len(calls), 10)

    def test_zero_travel_positive_treatment_and_zero_treatment_positive_travel(self):
        """Zero durations preserve event order without releasing a responder early."""
        for location, treatment, arrival, completion in (("A", 3, 0, 3), ("B", 0, 5, 5)):
            s, g = fixture([incident(location=location, treatment=treatment)])
            result = scripted(s, g, {0: [("R", "I")]})
            self.assertEqual((result.incidents[0].arrival_time, result.time), (arrival, completion))
            self.assertEqual([e.kind for e in result.events if e.kind in {"dispatch", "arrival", "completion"}],
                             ["dispatch", "arrival", "completion"])

    def test_arrival_equality_and_service_after_deadline(self):
        """Arrival at deadline 5 meets it; treatment may legitimately finish at 15."""
        s, g = fixture([incident(deadline=5, treatment=10)])
        result = scripted(s, g, {0: [("R", "I")]})
        self.assertEqual(result.time, 15)
        self.assertEqual(result.incidents[0].deadline_result, "met")
        self.assertFalse(any(e.kind == "deadline_missed" for e in result.events))

    def test_strict_deadline_closure_is_separate_from_outcome(self):
        """Strict unhandled work is closed for policy reasons and independently marked missed."""
        s, g = fixture([incident(deadline=2)])
        result = simulate(s, g, lambda view: ())
        view = result.incidents[0]
        self.assertEqual((view.status, view.deadline_result), ("closed_unassigned", "missed"))
        self.assertEqual(view.unassigned_reason, "strict_deadline_unassigned")
        self.assertEqual(result.assignments, ())

    def test_late_response_can_complete_after_missing_deadline(self):
        """Allow-late policy preserves missed outcomes while finishing assigned work."""
        s, g = fixture([incident(deadline=2)])
        result = scripted(s, g, {0: [("R", "I")]}, strict_deadlines=False)
        view = result.incidents[0]
        self.assertEqual((view.status, view.deadline_result), ("completed", "missed"))
        self.assertEqual((view.arrival_time, view.completion_time), (5, 7))
        self.assertEqual([e.time for e in result.events if e.kind == "deadline_missed"], [2])

    def test_late_dispatch_after_deadline_keeps_pending_until_response(self):
        """At time 3 the missed incident is still pending in allow-late mode."""
        s, g = fixture([incident(deadline=2)])
        seen = []
        script = ScriptedDispatcher({3: [AssignmentRequest("R", "I")]})
        def dispatch(view):
            seen.append(view)
            return script(view)
        result = simulate(s, g, dispatch, strict_deadlines=False, decision_times=script.decision_times)
        at_three = next(v for v in seen if v.time == 3).incidents[0]
        self.assertEqual((at_three.status, at_three.deadline_result), ("pending", "missed"))
        self.assertEqual(result.incidents[0].arrival_time, 8)

    def test_strict_rejects_late_assignment(self):
        """A predicted-late request is invalid in strict mode, not silently accepted."""
        s, g = fixture([incident(deadline=2)])
        with self.assertRaisesRegex(ValueError, "Ineligible"):
            scripted(s, g, {0: [("R", "I")]})

    def test_unreachable_work_is_explicitly_unhandled(self):
        """Missing routes never create assignments or infinite retry loops."""
        for strict in (True, False):
            s, g = fixture([incident(deadline=4)], edges=())
            calls = []
            def dispatch(view):
                calls.append(view.time)
                self.assertEqual(view.candidates, ())
                return ()
            result = simulate(s, g, dispatch, strict_deadlines=strict)
            self.assertEqual(result.incidents[0].status, "closed_unassigned")
            self.assertEqual(result.incidents[0].deadline_result, "missed")
            self.assertEqual(result.time, 4)
            self.assertEqual(calls, [0, 4])

    def test_empty_decisions_advance_to_future_releases_and_deadlines(self):
        """No free responders/assignments must not hide future incidents or spin."""
        s, g = fixture([incident("I1", timestamp=100, deadline=101),
                        incident("I2", timestamp=5000, deadline=5001)], responders=[])
        seen = []
        def dispatch(view):
            seen.append(view.time)
            return ()
        result = simulate(s, g, dispatch)
        self.assertEqual(seen, [0, 100, 101, 5000, 5001])
        self.assertEqual(len(result.incidents), 2)

    def test_deadline_before_release_and_fractional_times(self):
        """Badly timed incidents are revealed, never scheduled backwards; fractions remain."""
        s, g = fixture([incident(timestamp=2.5, deadline=1)])
        result = simulate(s, g, lambda view: ())
        self.assertEqual(result.time, 2.5)
        self.assertEqual(result.incidents[0].deadline_result, "missed")
        seen = []
        def inspect(view):
            seen.append(view)
            return ()
        simulate(s, g, inspect, strict_deadlines=False)
        at_release = next(view for view in seen if view.time == 2.5)
        self.assertEqual(at_release.incidents[0].deadline_result, "missed")
        s, g = fixture([incident(timestamp=.25, deadline=2, treatment=.125)], edges=(("A", "B", .5),))
        result = scripted(s, g, {.25: [("R", "I")]})
        self.assertEqual((result.assignments[0].arrival_time, result.time), (.75, .875))

    def test_no_epsilon_reveals_nearly_simultaneous_future_work(self):
        """Different float timestamps stay distinct rather than being merged by tolerance."""
        s, g = fixture([incident("I1", timestamp=1), incident("I2", timestamp=1.000000001)])
        seen = []
        def dispatch(view):
            seen.append(view)
            return ()
        simulate(s, g, dispatch)
        at_one = next(v for v in seen if v.time == 1)
        self.assertEqual([i.incident.id for i in at_one.incidents], ["I1"])

    def test_invalid_batches_are_atomic_and_no_double_booking(self):
        """One invalid request prevents every dispatch in its batch from committing."""
        s, g = fixture([incident("I1"), incident("I2")], [responder("R1"), responder("R2")])
        batches = [
            [AssignmentRequest("R1", "I1"), AssignmentRequest("R1", "I2")],
            [AssignmentRequest("R1", "I1"), AssignmentRequest("R2", "I1")],
            [AssignmentRequest("R1", "I1"), AssignmentRequest("R2", "unknown")],
        ]
        for batch in batches:
            engine = _Simulator(s, g, lambda view: batch, True, ())
            with self.assertRaises(ValueError):
                engine.run()
            self.assertEqual(engine.assignments, [])
            self.assertTrue(all(r.view.status == "available" for r in engine.responders.values()))

    def test_invalid_capability_busy_and_unrevealed_requests(self):
        """The engine validates current eligibility even if a script knows future IDs."""
        cases = [fixture([incident(capability="CPR")]),
                 fixture([incident()], [responder(ready=10, busy=True)]),
                 fixture([incident(timestamp=10)])]
        for s, g in cases:
            with self.assertRaisesRegex(ValueError, "Ineligible"):
                scripted(s, g, {0: [("R", "I")]})

    def test_nonpreemption_with_new_critical_incident(self):
        """A later urgent release cannot free or redirect a committed travelling responder."""
        s, g = fixture([incident("I1", treatment=10),
                        replace(incident("I2", timestamp=1), priority="Critical")])
        seen = []
        script = ScriptedDispatcher({0: [AssignmentRequest("R", "I1")]})
        def dispatch(view):
            seen.append(view)
            return script(view)
        result = simulate(s, g, dispatch)
        at_one = next(v for v in seen if v.time == 1)
        self.assertEqual((at_one.responders[0].status, at_one.responders[0].location), ("travelling", None))
        self.assertEqual(at_one.candidates, ())
        self.assertEqual(result.assignments[0].incident_id, "I1")

    def test_snapshot_isolation_and_input_preservation(self):
        """Earlier views and original records/graph remain unchanged after later transitions."""
        s, g = fixture([incident()])
        original = copy.deepcopy(s)
        edges = {n.id: g.neighbors(n.id) for n in s.nodes}
        seen = []
        script = ScriptedDispatcher({0: [AssignmentRequest("R", "I")]})
        def dispatch(view):
            seen.append(view)
            return script(view)
        simulate(s, g, dispatch)
        self.assertEqual(s, original)
        self.assertEqual(edges, {n.id: g.neighbors(n.id) for n in s.nodes})
        self.assertEqual(seen[0].responders[0].status, "available")
        self.assertEqual(seen[0].incidents[0].status, "pending")

    def test_invalid_times_and_inconsistent_initial_state(self):
        """Reject invalid wake-ups/policies and invalid initial availability."""
        s, g = fixture([incident()])
        for time in (-1, float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                simulate(s, g, lambda view: (), decision_times=[time])
        with self.assertRaises(ValueError):
            simulate(s, g, lambda view: (), strict_deadlines="strict")
        bad = replace(s, responders=(responder(ready=2),))
        with self.assertRaises(ValueError):
            simulate(bad, g, lambda view: ())

    def test_empty_scenario_terminates(self):
        """An empty input stream needs one initial decision, not an infinite loop."""
        s, g = fixture([])
        result = simulate(s, g, lambda view: ())
        self.assertEqual((result.time, result.assignments, result.incidents), (0, (), ()))

    def test_unrepresentable_clock_advance_fails_instead_of_becoming_zero(self):
        """At huge times, small positive travel must not collapse into immediate arrival."""
        s, g = fixture([incident(timestamp=1e20, deadline=1e21)], edges=(("A", "B", 1),))
        with self.assertRaisesRegex(ValueError, "not representable"):
            simulate(s, g, lambda view: ())

    def test_real_scenario_script_uses_estimates_and_finishes_service_after_deadline(self):
        """Real Scenario1 scripts exercise Bayesian routing, initial busy time and completion."""
        s = load_scenario(ROOT / "Scenarios/Scenario1")
        g = build_bayesian_graph(s, infer_scenario(s), blocked_threshold=.2)
        script = load_script(ROOT / "examples/scenario1_script.json")
        result = simulate(s, g, script, decision_times=script.decision_times)
        self.assertEqual(len(result.assignments), 4)
        states = {v.incident.id: v for v in result.incidents}
        self.assertAlmostEqual(states["I1"].arrival_time, 66.96878612716763)
        self.assertAlmostEqual(states["I2"].completion_time, 116.77803468208094)
        self.assertAlmostEqual(states["I5"].arrival_time, 197.34714003944772)
        self.assertAlmostEqual(states["I5"].completion_time, 217.34714003944772)
        self.assertEqual(states["I5"].deadline_result, "met")
        self.assertTrue(all(v.deadline_result == "missed" for key, v in states.items()
                            if key in {"I3", "I6", "I7"}))

    def test_all_real_scenarios_reveal_all_incidents_without_an_allocator(self):
        """No-op dispatch verifies complete streams and finite strict/late termination."""
        for name in ("Scenario1", "Scenario2", "Scenario3"):
            s = load_scenario(ROOT / "Scenarios" / name)
            g = build_bayesian_graph(s, infer_scenario(s), blocked_threshold=.2)
            for strict in (True, False):
                result = simulate(s, g, lambda view: (), strict_deadlines=strict)
                self.assertEqual(len(result.incidents), len(s.incidents))
                self.assertTrue(all(v.deadline_result == "missed" and v.status == "closed_unassigned"
                                    for v in result.incidents))

    def test_real_commitments_independent_replay(self):
        """Replay Scenario1 commitments without consulting the controller's private state."""
        s = load_scenario(ROOT / "Scenarios/Scenario1")
        graph = build_bayesian_graph(s, infer_scenario(s), blocked_threshold=.2)
        script = load_script(ROOT / "examples/scenario1_script.json")
        result = simulate(s, graph, script, decision_times=script.decision_times)
        responders = {r.id: r for r in s.responders}
        incidents = {i.id: i for i in s.incidents}
        locations = {r.id: r.start_location for r in s.responders}
        ready = {r.id: r.time_until_available for r in s.responders}
        handled = set()
        for record in result.assignments:
            incident_input = incidents[record.incident_id]
            self.assertNotIn(record.incident_id, handled)
            self.assertIn(incident_input.required_capability, responders[record.responder_id].capabilities)
            self.assertGreaterEqual(record.departure_time, incident_input.timestamp)
            self.assertGreaterEqual(record.departure_time, ready[record.responder_id])
            self.assertEqual(record.route.nodes[0], locations[record.responder_id])
            self.assertEqual(record.route.nodes[-1], incident_input.location)
            cost = 0
            for a, b, road in zip(record.route.nodes, record.route.nodes[1:], record.route.roads):
                edge = next(e for e in graph.neighbors(a) if e.target == b and e.road_id == road)
                cost += edge.seconds
            self.assertAlmostEqual(record.route.seconds, cost)
            self.assertAlmostEqual(record.arrival_time, record.departure_time + cost)
            self.assertLessEqual(record.arrival_time, incident_input.deadline)
            self.assertAlmostEqual(record.completion_time, record.arrival_time + incident_input.time_required)
            locations[record.responder_id] = incident_input.location
            ready[record.responder_id] = record.completion_time
            handled.add(record.incident_id)


if __name__ == "__main__":
    unittest.main()
