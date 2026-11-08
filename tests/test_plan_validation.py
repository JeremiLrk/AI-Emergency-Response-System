"""Independent operational replay, including malformed and deliberately bad plans.

unittest supplies self. Controlled original scenario fixtures are used; tests
return None when assertions pass and never alter supplied input files.
"""
import copy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from emergency_response.plan_validation import load_plan, validate_plan
from test_simulation import fixture, incident, responder

ROOT = Path(__file__).resolve().parents[1]


def entry(responder_id="R",incident_id="I",path=None,time=0):
    """Return a fresh assignment-format row for tests.

    Parameters: IDs, node path (default A->B), departure seconds.
    Preconditions: values appropriate to each good/bad case.
    Postconditions: fresh dict with the exact assignment keys; no I/O.
    """
    return {"responder_id":responder_id,"incident_id":incident_id,
            "path":["A","B"] if path is None else path,"time":time}


class PlanValidationTests(unittest.TestCase):
    def setUp(self):
        """Create original scenario with five-second travel and two-second treatment."""
        self.scenario,_=fixture([incident(deadline=5)])

    def codes(self,plan,**options):
        """Validate fixture plan; return error codes for targeted assertions.

        Parameters: plan decoded rows; options override policy.
        Preconditions: scenario fixture valid. Postconditions: error-code set.
        """
        return {i.code for i in validate_plan(self.scenario,plan,**options).errors}

    def test_valid_plan_reconstructed_deadline_is_arrival_not_completion(self):
        report=validate_plan(self.scenario,[entry()])
        self.assertTrue(report.valid)
        self.assertTrue(report.deadline_compliant)
        self.assertEqual((report.assignments[0].arrival_time,report.assignments[0].completion_time),(5,7))
        self.assertEqual(report.statistics.average_response_seconds,5)
        self.assertEqual(report.statistics.deadlines_met,1)

    def test_empty_valid_plan_can_have_poor_performance(self):
        report=validate_plan(self.scenario,[])
        self.assertTrue(report.valid)
        self.assertEqual(report.unhandled_incident_ids,("I",))
        self.assertEqual(report.statistics.handled,0)
        self.assertEqual(report.statistics.deadlines_met_percent_all,0)
        self.assertIsNone(report.statistics.average_response_seconds)

    def test_schema_and_numbers_rejected(self):
        for plan in ({"assignments":[]},[{}],[entry(path=[])],[entry(path=["unknown"])],
                     [entry(time=True)],[entry(time=float("nan"))],[entry(time=float("inf"))],
                     [entry(time=-1)],[entry(time="0")],[entry(time=10**1000)],
                     [{**entry(),"arrival_time":5}],[entry(responder_id=[])],
                     [entry(path="A->B")]):
            with self.subTest(plan=str(plan)[:80]):
                self.assertFalse(validate_plan(self.scenario,plan).valid)

    def test_unknown_references_and_duplicate_incidents(self):
        self.assertIn("reference",self.codes([entry(responder_id="R999")]))
        self.assertIn("reference",self.codes([entry(incident_id="I999")]))
        self.assertIn("duplicate_incident",self.codes([entry(),entry(time=10)]))

    def test_capability_release_and_initial_busy_checks(self):
        wrong=replace(self.scenario,incidents=(incident(capability="CPR"),))
        self.assertIn("capability",{i.code for i in validate_plan(wrong,[entry()]).errors})
        future=replace(self.scenario,incidents=(incident(timestamp=1),))
        self.assertIn("release",{i.code for i in validate_plan(future,[entry()]).errors})
        busy=replace(self.scenario,responders=(responder(ready=3,busy=True),),
                     incidents=(incident(deadline=100),))
        self.assertIn("availability",{i.code for i in validate_plan(busy,[entry(time=2)]).errors})
        self.assertTrue(validate_plan(busy,[entry(time=3)]).valid)

    def test_directed_roads_and_endpoints_checked(self):
        self.assertIn("endpoint",self.codes([entry(path=["B"])]))
        self.assertIn("directed_road",self.codes([entry(path=["A","C","B"])]))
        one_way,_=fixture([incident(location="A")],responders=[responder(location="B")],edges=(("A","B",5),))
        report=validate_plan(one_way,[entry(path=["B","A"])])
        self.assertIn("directed_road",{e.code for e in report.errors})

    def test_late_mode_validity_distinct_from_deadline_compliance(self):
        strict=validate_plan(self.scenario,[entry(time=1)])
        self.assertFalse(strict.valid)
        self.assertIn("deadline",{e.code for e in strict.errors})
        self.assertIsNone(strict.statistics)
        late=validate_plan(self.scenario,[entry(time=1)],strict_deadlines=False)
        self.assertTrue(late.valid)
        self.assertFalse(late.deadline_compliant)
        self.assertEqual(late.statistics.handled,1)
        self.assertEqual(late.statistics.deadlines_met,0)
        self.assertEqual(late.warnings[0].code,"deadline")

    def test_multiple_jobs_wait_for_treatment_and_update_location(self):
        scenario,_=fixture([incident(id="I1",deadline=100,treatment=2),
                            incident(id="I2",location="A",deadline=100)])
        plan=[entry(incident_id="I1"),entry(incident_id="I2",path=["B","A"],time=7)]
        report=validate_plan(scenario,plan)
        self.assertTrue(report.valid)
        self.assertEqual(report.assignments[1].arrival_time,10)
        overlap=copy.deepcopy(plan)
        overlap[1]["time"]=6
        self.assertIn("availability",{e.code for e in validate_plan(scenario,overlap).errors})
        stale_location=copy.deepcopy(plan)
        stale_location[1]["path"]=["A"]
        self.assertIn("endpoint",{e.code for e in validate_plan(scenario,stale_location).errors})
        self.assertTrue(validate_plan(scenario,list(reversed(plan))).valid)

    def test_zero_duration_reuse_same_time_is_valid(self):
        scenario,_=fixture([incident(id="I1",location="A",treatment=0),
                            incident(id="I2",location="A",treatment=0)])
        report=validate_plan(scenario,[entry(incident_id="I1",path=["A"]),
                                       entry(incident_id="I2",path=["A"])])
        self.assertTrue(report.valid)
        self.assertEqual(report.statistics.handled,2)

    def test_two_responders_cannot_handle_same_incident(self):
        scenario=replace(self.scenario,responders=(responder(id="R1"),responder(id="R2")))
        report=validate_plan(scenario,[entry(responder_id="R1"),entry(responder_id="R2")])
        self.assertFalse(report.valid)
        self.assertIn("duplicate_incident",{e.code for e in report.errors})

    def test_bayesian_reconstruction_and_rejected_edge(self):
        # Controlled Bayesian belief isolates the independent formula: conditional
        # cost=5*(.2+1.5*.6)/.8=6.875, not normal5 or unnormalized5.5.
        belief={r.key:{"Open":.2,"Congested":.6,"Blocked":.2} for r in self.scenario.roads}
        with patch("emergency_response.plan_validation.infer_scenario",return_value=belief):
            report=validate_plan(self.scenario,[entry()],routing_policy="bayesian",blocked_threshold=.3,
                                 strict_deadlines=False)
            self.assertAlmostEqual(report.assignments[0].travel_seconds,6.875)
            blocked=validate_plan(self.scenario,[entry()],routing_policy="bayesian",blocked_threshold=.2)
            self.assertIn("blocked_road",{e.code for e in blocked.errors})

    def test_independent_of_simulator_search_and_graph_builder(self):
        with patch("emergency_response.simulation.simulate",side_effect=AssertionError("must not simulate")), \
             patch("emergency_response.search.ucs",side_effect=AssertionError("must not search")), \
             patch("emergency_response.risk_routing.build_bayesian_graph",side_effect=AssertionError("must not build")):
            self.assertTrue(validate_plan(self.scenario,[entry()]).valid)

    def test_strict_json_decoder_rejects_duplicates_and_nonstandard_constants(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
            path=Path(directory)/"plan.json"
            for text in ('[{"time":0,"time":1}]','[NaN]','[Infinity]','[-Infinity]','['):
                path.write_text(text,encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_plan(path)
            path.write_text(json.dumps([entry()]),encoding="utf-8")
            self.assertEqual(load_plan(path),[entry()])

    def test_policy_configuration_rejected_and_input_unchanged(self):
        for options in ({"routing_policy":"unknown"},{"strict_deadlines":1},
                        {"blocked_threshold":.2},{"routing_policy":"bayesian"},
                        {"routing_policy":"bayesian","blocked_threshold":float("nan")}):
            with self.assertRaises(ValueError):
                validate_plan(self.scenario,[],**options)
        scenario_before=copy.deepcopy(self.scenario)
        plan=[entry()]
        plan_before=copy.deepcopy(plan)
        validate_plan(self.scenario,plan)
        self.assertEqual(self.scenario,scenario_before)
        self.assertEqual(plan,plan_before)


if __name__ == "__main__":
    unittest.main()
