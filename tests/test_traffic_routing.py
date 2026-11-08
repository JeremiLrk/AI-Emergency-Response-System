"""Separate-criterion routing, resource constraints and actual-time simulation.

Tests take unittest self and return None on successful assertions. Synthetic graphs
isolate policy choices; actual scenario checks preserve source inputs unchanged.
"""
from dataclasses import replace
from pathlib import Path
import json
import random
import subprocess
import sys
import unittest

from emergency_response.graph import Graph
from emergency_response.hmm import TrafficBelief, infer_traffic
from emergency_response.loaders import load_scenario
from emergency_response.models import Road, Node, Incident, Responder
from emergency_response.routing import build_graph
from emergency_response.bayesian import infer_scenario
from emergency_response.risk_routing import build_bayesian_graph
from emergency_response.search import ucs, Route
from emergency_response.simulation import simulate
from emergency_response.baseline import NearestDispatcher
from emergency_response.traffic_routing import TrafficRouter, TrafficSearchLimit

ROOT = Path(__file__).resolve().parents[1]


def network(arcs, **options):
    """Build directed fixture from (source,target,time,PHigh) rows.

    Parameters: arcs are unique edges; options configure TrafficRouter.
    Preconditions: valid finite costs/probabilities; speed1 makes normal time=cost.
    Postconditions: graph, roads, router; graph times remain independent of score.
    """
    roads = tuple(Road(a,b,t,1,"main") for a,b,t,p in arcs)
    graph = Graph({n for a,b,t,p in arcs for n in (a,b)})
    beliefs = {}
    for road, (_,_,_,p) in zip(roads, arcs):
        graph.add_edge(road.source, road.target, road.normal_seconds, road.id)
        beliefs[road.key] = TrafficBelief({"Low": 1-p,"Medium": 0.,"High": p}, 1)
    return graph, roads, TrafficRouter(roads, beliefs, **options)


class TrafficRoutingTests(unittest.TestCase):
    def test_cli_bounded_run_and_explicit_configuration(self):
        args=[sys.executable,str(ROOT/"run.py"),str(ROOT/"Scenarios/Scenario3"),
              "--routing-policy","bayesian","--block-threshold",".2",
              "--traffic-policy","hmm-bounded","--max-extra-fraction",".05","--route","N3","H1"]
        completed=subprocess.run(args,capture_output=True,text=True,check=True)
        data=json.loads(completed.stdout)
        self.assertEqual(data["route"]["nodes"],["N3","N5","N8","H1"])
        self.assertGreater(data["traffic_route_exposure"]["extra_seconds"],0)
        self.assertEqual(len(data["traffic_beliefs"]),60)
        invalid=subprocess.run(args[:-6],capture_output=True,text=True)
        self.assertNotEqual(invalid.returncode,0)

    def test_metadata_and_reverse_direction_checked(self):
        graph,roads,router=network([("A","B",1,.9),("B","A",1,.1)])
        self.assertEqual(router.exposure(router(graph,"A","B")),.9)
        self.assertEqual(router.exposure(router(graph,"B","A")),.1)
        with self.assertRaises(ValueError):
            TrafficRouter(roads,{})
        bad=Graph(["A","B"])
        bad.add_edge("A","B",1,"B->A")
        with self.assertRaises(ValueError):
            router(bad,"A","B")

    def test_exact_tie_chooses_lower_exposure(self):
        graph, roads, router = network([("A","B",10,.9),("B","D",10,.9),
                                       ("A","C",10,.1),("C","D",10,.1)])
        self.assertEqual(ucs(graph,"A","D").nodes, ("A","B","D"))
        route = router(graph,"A","D")
        self.assertEqual(route.nodes, ("A","C","D"))
        self.assertEqual(route.seconds,20)
        self.assertEqual(router.exposure(route),2)
        self.assertEqual(ucs(graph,"A","D").seconds,20)

    def test_near_tie_is_not_exact_tie(self):
        graph, _, router = network([("A","B",1,.9),("B","D",1,.9),
                                   ("A","C",1,0),("C","D",1.0000000001,0)])
        self.assertEqual(router(graph,"A","D").nodes, ("A","B","D"))

    def test_bounded_acceptance_time_cap_and_improvement_gate(self):
        arcs = [("A","B",10,.9),("B","D",10,.9),("A","C",10,.1),("C","D",11,.1)]
        graph, _, router = network(arcs, policy="bounded", max_extra_fraction=.05)
        route = router(graph,"A","D")
        self.assertEqual(route.nodes, ("A","C","D"))
        self.assertEqual(route.seconds,21)
        self.assertEqual(router(graph,"A","D",max_seconds=20.5).seconds,20)
        self.assertIsNone(router(graph,"A","D",max_seconds=19))
        graph, _, router = network(arcs, policy="bounded", max_extra_fraction=.049)
        self.assertEqual(router(graph,"A","D").seconds,20)
        graph, _, router = network(arcs, policy="bounded", max_extra_fraction=.05, min_exposure_reduction=.99)
        self.assertEqual(router(graph,"A","D").seconds,20)

    def test_pareto_labels_preserve_faster_dirty_and_slower_clean_prefix(self):
        graph, _, router = network([("A","B",1,1),("B","X",1,1),
            ("A","C",1,0),("C","X",2,0),("X","D",20,0)],
            policy="bounded",max_extra_fraction=.05)
        route = router(graph,"A","D")
        self.assertEqual(route.nodes,("A","C","X","D"))
        self.assertEqual(route.seconds,23)

    def test_zero_exposure_zero_cost_cycles_start_goal_and_direction(self):
        graph, _, router = network([("A","B",0,0),("B","A",0,0),("B","D",1,0)],
            policy="bounded",max_extra_fraction=.05)
        self.assertEqual(router(graph,"A","D").seconds,1)
        self.assertEqual(router(graph,"A","A"),Route(("A",),(),0))
        self.assertIsNone(router(graph,"D","A"))

    def test_label_guard_and_settings(self):
        arcs = [("A","B",1,.9),("B","D",1,.9)]
        graph, _, router = network(arcs,policy="bounded",max_extra_fraction=.05,label_limit=1)
        with self.assertRaises(TrafficSearchLimit):
            router(graph,"A","D")
        for options in ({"max_extra_fraction":float("nan")},{"max_extra_fraction":-.1},
                        {"min_exposure_reduction":1.1},{"label_limit":True},{"policy":"unknown"}):
            with self.assertRaises(ValueError):
                network(arcs,**options)

    def test_bounded_matches_exhaustive_simple_paths(self):
        rng = random.Random(274)
        for trial in range(30):
            arcs = [(str(a),str(b),rng.randint(1,10),rng.random()) for a in range(5)
                    for b in range(a+1,5) if b==a+1 or rng.random()<.6]
            graph, _, router = network(arcs,policy="bounded",max_extra_fraction=.2)
            paths = []
            def visit(node, nodes, roads, time):
                if node=="4":
                    route=Route(tuple(nodes),tuple(roads),time)
                    paths.append((time,router.exposure(route),route))
                for edge in graph.neighbors(node):
                    visit(edge.target,nodes+[edge.target],roads+[edge.road_id],time+edge.seconds)
            visit("0",["0"],[],0.)
            shortest = min(paths,key=lambda x:x[:2])
            choice = min((p for p in paths if p[0]<=1.2*shortest[0]),key=lambda x:(x[1],x[0]))
            expected = choice if choice[1]<shortest[1] and choice[1]<=.9*shortest[1] else shortest
            actual = router(graph,"0","4")
            self.assertEqual((actual.seconds,router.exposure(actual)),expected[:2])

    def test_simulation_uses_selected_travel_seconds_and_deadline_cap(self):
        arcs=[("A","B",10,.9),("B","D",10,.9),("A","C",10,.1),("C","D",11,.1)]
        graph, roads, router=network(arcs,policy="bounded",max_extra_fraction=.05)
        base=load_scenario(ROOT/"Scenarios/Scenario1")
        scenario=replace(base,nodes=tuple(Node(n,n,0,0,"normal") for n in "ABCD"), roads=roads,
            responders=(Responder("R","Ambulance","A",frozenset({"First aid"}),"Available",0),),
            incidents=(Incident("I","D","High",100,"First aid",0,7),),
            road_reports=(),traffic_history={},warnings=())
        result=simulate(scenario,graph,NearestDispatcher(),route_planner=router)
        assignment=result.assignments[0]
        self.assertEqual((assignment.arrival_time,assignment.completion_time),(21,28))
        self.assertNotEqual(router.exposure(assignment.route),assignment.route.seconds)
        tight=replace(scenario,incidents=(replace(scenario.incidents[0],deadline=20.5),))
        result=simulate(tight,graph,NearestDispatcher(),route_planner=router)
        self.assertEqual(result.assignments[0].arrival_time,20)
        late=simulate(tight,graph,NearestDispatcher(),route_planner=router,strict_deadlines=False)
        self.assertEqual(late.assignments[0].arrival_time,21)
        self.assertEqual(late.incidents[0].deadline_result,"missed")
        def forged(graph,start,goal,**kwargs):
            return Route(("A","B","D"),("A->B","B->D"),0.)
        with self.assertRaisesRegex(ValueError,"duration"):
            simulate(scenario,graph,NearestDispatcher(),route_planner=forged)

    def test_actual_scenarios_tie_and_bounded_preserve_bayesian_times(self):
        for number in (1,2,3):
            scenario=load_scenario(ROOT/f"Scenarios/Scenario{number}")
            graph=build_bayesian_graph(scenario,infer_scenario(scenario),blocked_threshold=.2)
            traffic=infer_traffic(scenario)
            tie=TrafficRouter(scenario.roads,traffic)
            bounded=TrafficRouter(scenario.roads,traffic,policy="bounded",max_extra_fraction=.05)
            before=tuple((n.id,graph.neighbors(n.id)) for n in scenario.nodes)
            for a in scenario.nodes:
                for b in scenario.nodes:
                    shortest=ucs(graph,a.id,b.id)
                    route=bounded(graph,a.id,b.id)
                    if shortest is None:
                        self.assertIsNone(route)
                        continue
                    self.assertEqual(tie(graph,a.id,b.id).seconds,shortest.seconds)
                    self.assertLessEqual(route.seconds,shortest.seconds*1.05)
                    total=0.
                    for node,road_id in zip(route.nodes,route.roads):
                        total+=next(e.seconds for e in graph.neighbors(node) if e.road_id==road_id)
                    self.assertEqual(route.seconds,total)
            self.assertEqual(before,tuple((n.id,graph.neighbors(n.id)) for n in scenario.nodes))


if __name__ == "__main__":
    unittest.main()
