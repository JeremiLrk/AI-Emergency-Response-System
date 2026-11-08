"""Required artifacts match execution; independent original-data replay agrees.

unittest supplies self. Scenario files are read-only; all exports go to temporary
directories. Each successful test returns None; failures propagate to unittest.
"""
import contextlib
from dataclasses import replace, asdict
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import run
from emergency_response.allocation import CspDispatcher
from emergency_response.bayesian import infer_scenario
from emergency_response.hmm import infer_traffic
from emergency_response.loaders import load_scenario
from emergency_response.outputs import make_plan, write_outputs
from emergency_response.plan_validation import load_plan, validate_plan
from emergency_response.risk_routing import build_bayesian_graph
from emergency_response.simulation import simulate
from emergency_response.statistics import summarize
from emergency_response.traffic_routing import TrafficRouter
from test_simulation import fixture, incident, scripted

ROOT=Path(__file__).resolve().parents[1]


class OutputTests(unittest.TestCase):
    def test_all_three_scenarios_strict_late_and_three_traffic_policies(self):
        expected={(1,True):(6,6),(1,False):(7,5),(2,True):(11,11),
                  (2,False):(12,10),(3,True):(13,13),(3,False):(20,11)}
        for number in (1,2,3):
            scenario=load_scenario(ROOT/f"Scenarios/Scenario{number}")
            graph=build_bayesian_graph(scenario,infer_scenario(scenario),blocked_threshold=.2)
            traffic=infer_traffic(scenario)
            for strict in (True,False):
                for policy in ("bayesian-only","hmm-tie","hmm-bounded"):
                    with self.subTest(scenario=number,strict=strict,policy=policy):
                        planner=(None if policy=="bayesian-only" else TrafficRouter(scenario.roads,traffic,
                            policy="bounded" if policy=="hmm-bounded" else "tie",max_extra_fraction=.05))
                        result=simulate(scenario,graph,CspDispatcher(),strict_deadlines=strict,route_planner=planner)
                        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
                            exported=write_outputs(scenario,result,directory,routing_policy="bayesian",
                                blocked_threshold=.2,configuration={"traffic_policy":policy})
                            plan=load_plan(exported["plan"])
                            self.assertEqual(plan,make_plan(result))
                            for row,assignment in zip(plan,result.assignments):
                                self.assertEqual(set(row),{"responder_id","incident_id","path","time"})
                                self.assertEqual(row["path"],list(assignment.route.nodes))
                                self.assertEqual(row["time"],assignment.departure_time)
                            validation=validate_plan(scenario,plan,routing_policy="bayesian",
                                blocked_threshold=.2,strict_deadlines=strict)
                            self.assertTrue(validation.valid,validation.errors)
                            self.assertEqual(validation.statistics,summarize(result))
                            self.assertEqual(asdict(validation),exported["validation"])
                            self.assertEqual((validation.statistics.handled,validation.statistics.deadlines_met),expected[(number,strict)])
                            self.assertLess(validation.statistics.responders_used,validation.statistics.handled)
                            text=Path(exported["statistics"]).read_text(encoding="utf-8")
                            self.assertIn(f"* {validation.statistics.handled} incidents handled",text)
                            self.assertIn(f"* Average response time: {validation.statistics.average_response_seconds} s",text)
                            self.assertIn(f"* Deadlines met: {validation.statistics.deadlines_met_percent_all}%",text)
                            self.assertIn("Run configuration:",text)

    def test_export_start_is_departure_not_release_or_arrival(self):
        scenario,graph=fixture([incident(timestamp=1,deadline=100)])
        result=scripted(scenario,graph,{3:[("R","I")]})
        self.assertEqual(make_plan(result)[0]["time"],3)
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
            files=write_outputs(scenario,result,directory)
            text=Path(files["statistics"]).read_text(encoding="utf-8")
            self.assertIn("* Average response time: 7.0 s",text)
            self.assertEqual(files["validation"]["assignments"][0]["completion_time"],10)

    def test_unhandled_and_empty_stream_have_explicit_denominators(self):
        for incidents in ([incident()],[]):
            scenario,graph=fixture(incidents)
            result=scripted(scenario,graph,{})
            with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
                files=write_outputs(scenario,result,directory)
                self.assertEqual(load_plan(files["plan"]),[])
                text=Path(files["statistics"]).read_text(encoding="utf-8")
                self.assertIn("Average response time: N/A",text)
                self.assertIn("Deadlines met: 0.0%" if incidents else "Deadlines met: N/A",text)

    def test_tampered_timing_and_summary_refused_before_writing(self):
        scenario,graph=fixture([incident()])
        result=scripted(scenario,graph,{0:[("R","I")]})
        assignment=result.assignments[0]
        bad_results=[replace(result,assignments=(replace(assignment,arrival_time=0),)),
                     replace(result,assignments=(replace(assignment,completion_time=1),)),
                     replace(result,assignments=(replace(assignment,route=replace(assignment.route,seconds=0)),)),
                     replace(result,incidents=(replace(result.incidents[0],status="unassigned"),))]
        for bad in bad_results:
            with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
                with self.assertRaises(ValueError):
                    write_outputs(scenario,bad,directory)
                self.assertFalse((Path(directory)/"plan.json").exists())
                self.assertFalse((Path(directory)/"statistics.txt").exists())

    def test_late_text_distinguishes_validity_and_deadline_compliance(self):
        scenario,graph=fixture([incident(deadline=1)])
        result=scripted(scenario,graph,{0:[("R","I")]},strict_deadlines=False)
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
            files=write_outputs(scenario,result,directory)
            text=Path(files["statistics"]).read_text(encoding="utf-8")
            self.assertIn("under selected policy: VALID",text)
            self.assertIn("Every assigned arrival meets its deadline: no",text)
            self.assertIn("experimental; permits assignment-deadline violations",text)


class OutputCLITests(unittest.TestCase):
    def call_cli(self,directory,*options):
        """Run real CLI entry in-process with captured output and temporary destination.

        Parameters: directory writable destination; options are CLI flags.
        Preconditions: Scenario1 readable. Postconditions: decoded stdout; argv restored.
        """
        stream=io.StringIO()
        with patch("sys.argv",["run.py",str(ROOT/"Scenarios/Scenario1"),"--output-dir",str(directory),*options]),contextlib.redirect_stdout(stream):
            run.main()
        return json.loads(stream.getvalue())

    def test_normal_and_comparison_outputs_match_stdout(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
            normal=self.call_cli(directory,"--routing-policy","bayesian","--block-threshold",".2")
            self.assertEqual(load_plan(Path(directory)/"plan.json"),[
                {"responder_id":a["responder_id"],"incident_id":a["incident_id"],
                 "path":a["route"]["nodes"],"time":a["departure_time"]}
                for a in normal["simulation"]["assignments"]])
            compared=self.call_cli(directory,"--compare","--routing-policy","bayesian","--block-threshold",".2")
            for allocator in ("csp","nearest"):
                self.assertTrue((Path(directory)/allocator/"plan.json").is_file())
                self.assertTrue((Path(directory)/allocator/"statistics.txt").is_file())
                report=compared["comparison"][allocator]["output_files"]["validation"]
                self.assertTrue(report["valid"])
                self.assertEqual(report["statistics"],compared["comparison"][allocator]["statistics"])

    def test_default_output_directory_is_working_directory(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
            completed=subprocess.run([sys.executable,str(ROOT/"run.py"),str(ROOT/"Scenarios/Scenario1"),
                "--allocator","nearest"],cwd=directory,capture_output=True,text=True,check=True)
            data=json.loads(completed.stdout)
            self.assertTrue((Path(directory)/"plan.json").is_file())
            self.assertTrue((Path(directory)/"statistics.txt").is_file())
            self.assertTrue(data["output_files"]["validation"]["valid"])

    def test_standalone_validator_and_late_policy_exit_codes(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
            data=self.call_cli(directory,"--routing-policy","bayesian","--block-threshold",".2")
            command=[sys.executable,str(ROOT/"validate_plan.py"),str(ROOT/"Scenarios/Scenario1"),
                     data["output_files"]["plan"],"--routing-policy","bayesian","--block-threshold",".2"]
            completed=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(completed.returncode,0,completed.stderr)
            self.assertTrue(json.loads(completed.stdout)["valid"])
            path=Path(directory)/"plan.json"
            plan=load_plan(path)
            plan[0]["responder_id"]="unknown"
            path.write_text(json.dumps(plan),encoding="utf-8")
            invalid=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(invalid.returncode,1)
            self.assertFalse(json.loads(invalid.stdout)["valid"])

    def test_route_only_diagnostic_does_not_write_artifacts(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
            subprocess.run([sys.executable,str(ROOT/"run.py"),str(ROOT/"Scenarios/Scenario1"),
                "--route","N1","N2"],cwd=directory,capture_output=True,text=True,check=True)
            self.assertFalse((Path(directory)/"plan.json").exists())
            self.assertFalse((Path(directory)/"statistics.txt").exists())

    def test_scripted_late_export_requires_explicit_late_validation(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
            script=Path(directory)/"script.json"
            script.write_text(json.dumps([{"time":100,"responder_id":"R2","incident_id":"I1"}]),encoding="utf-8")
            result=self.call_cli(directory,"--simulate-script",str(script),"--allow-late")
            self.assertTrue(result["output_files"]["validation"]["valid"])
            self.assertFalse(result["output_files"]["validation"]["deadline_compliant"])
            command=[sys.executable,str(ROOT/"validate_plan.py"),str(ROOT/"Scenarios/Scenario1"),str(Path(directory)/"plan.json")]
            strict=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(strict.returncode,1,strict.stderr)
            self.assertIn("deadline",{e["code"] for e in json.loads(strict.stdout)["errors"]})
            late=subprocess.run(command+["--allow-late"],capture_output=True,text=True)
            self.assertEqual(late.returncode,0,late.stderr)
            self.assertFalse(json.loads(late.stdout)["deadline_compliant"])


if __name__ == "__main__":
    unittest.main()
