"""Course A* checked by hand, exhaustive small paths, and actual scenario geometry.

unittest supplies self; each test returns None when its assertions pass. Inputs
are private graphs or read-only scenario files, never modified source data.
"""
from dataclasses import replace
from pathlib import Path
import random
import unittest

from emergency_response.bayesian import infer_scenario
from emergency_response.graph import Graph
from emergency_response.loaders import load_scenario
from emergency_response.models import Node
from emergency_response.risk_routing import build_bayesian_graph
from emergency_response.routing import build_graph
from emergency_response.search import astar, straight_line_heuristic, ucs
from test_simulation import fixture, incident

ROOT = Path(__file__).resolve().parents[1]


def graph_with(nodes, edges):
    """Build a private graph; edges are (source,target,seconds) triples.

    Preconditions: valid finite nonnegative edges and known nodes.
    Postconditions: returns a new graph with a unique ID for every edge.
    """
    graph = Graph(nodes)
    for index, (a, b, seconds) in enumerate(edges):
        graph.add_edge(a, b, seconds, str(index))
    return graph


def exhaustive_cost(graph, start, goal):
    """Enumerate every simple path in a tiny graph; no heap or search code reused.

    Parameters: graph is tiny and nonnegative; start/goal are known nodes.
    Preconditions: only used in tests; exponential enumeration is intentionally small.
    Postconditions: returns the minimum path cost or None; start==goal gives zero.
        With nonnegative costs a cheapest route never needs a cycle.
    """
    costs = []
    def visit(node, visited, cost):
        if node == goal:
            costs.append(cost)
            return
        for edge in graph.neighbors(node):
            if edge.target not in visited:
                visit(edge.target, visited | {edge.target}, cost + edge.seconds)
    visit(start, {start}, 0)
    return min(costs) if costs else None


class AstarTests(unittest.TestCase):
    def test_goal_must_be_removed_not_first_discovered(self):
        graph = graph_with(['S', 'A', 'G'], [('S','G',9), ('S','A',2), ('A','G',3)])
        route = astar(graph, 'S', 'G', {'S':4, 'A':3, 'G':0}.__getitem__)
        self.assertEqual(route.nodes, ('S','A','G'))
        self.assertEqual(route.seconds, 5)

    def test_directed_unreachable_and_same_node(self):
        graph = graph_with(['S','G','X'], [('S','G',2)])
        self.assertIsNone(astar(graph, 'G', 'S', lambda n: 0))
        self.assertIsNone(astar(graph, 'S', 'X', lambda n: 0))
        route = astar(graph, 'S', 'S', lambda n: 0)
        self.assertEqual((route.nodes, route.roads, route.seconds), (('S',), (), 0))

    def test_parallel_edges_and_zero_cycles(self):
        graph = graph_with(['S','G'], [('S','S',0), ('S','G',8), ('S','G',2), ('G','S',0)])
        self.assertEqual(astar(graph, 'S','G', lambda n: 0).roads, ('2',))

    def test_stale_entries_do_not_replace_a_better_path(self):
        graph = graph_with(['S','A','B','G'], [('S','A',10), ('S','B',1), ('B','A',1), ('A','G',20)])
        self.assertEqual(astar(graph, 'S','G', lambda n: 0).seconds, 22)

    def test_admissible_inconsistent_heuristic_reopens_node(self):
        graph = graph_with(['S','A','B','G'], [('S','A',3), ('S','B',1), ('B','A',1), ('A','G',2)])
        # A is expanded at g=3, then improved to g=2 through B. h(B)=3 is
        # admissible but inconsistent with B->A because h(A)=0.
        route = astar(graph, 'S','G', {'S':0,'A':0,'B':3,'G':0}.__getitem__)
        self.assertEqual((route.nodes, route.seconds), (('S','B','A','G'), 4))

    def test_zero_heuristic_matches_ucs_including_ties(self):
        graph = graph_with(['S','A','B','G'], [('S','A',1), ('S','B',1), ('A','G',2), ('B','G',2)])
        self.assertEqual(astar(graph, 'S','G', lambda n: 0), ucs(graph, 'S','G'))

    def test_invalid_endpoints_and_heuristic_values(self):
        graph = graph_with(['S','A','G'], [('S','A',1), ('A','G',1)])
        for bad in (-1, True, '1', None, float('nan'), float('inf')):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                astar(graph, 'S','G', lambda n: 0 if n == 'G' else bad)
        for start, goal in [('X','G'), ('S','X')]:
            with self.assertRaises(ValueError):
                astar(graph, start, goal, lambda n: 0)
        with self.assertRaises(ValueError):
            astar(graph, 'S','G', None)
        with self.assertRaises(ValueError):
            astar(graph, 'S','G', lambda n: 1)

    def test_travel_overflow_is_reported(self):
        graph = graph_with(['S','A','G'], [('S','A',1e308), ('A','G',1e308)])
        with self.assertRaisesRegex(ValueError, 'overflow'):
            astar(graph, 'S','G', lambda n: 0)

    def test_priority_overflow_is_reported(self):
        graph = graph_with(['S','A','G'], [('S','A',1e308), ('A','G',1e308)])
        with self.assertRaisesRegex(ValueError, 'priority overflow'):
            astar(graph, 'S','G', lambda n: 1e308 if n == 'A' else 0)

    def test_exhaustive_small_graphs_independently_check_both_algorithms(self):
        random_source = random.Random(42)
        nodes = ['A','B','C','D','E']
        for example in range(30):
            edges = [(a,b,random_source.randrange(7)) for a in nodes for b in nodes
                     if random_source.random() < .3]
            graph = graph_with(nodes, edges)
            for goal in nodes:
                expected = {start: exhaustive_cost(graph,start,goal) for start in nodes}
                # Exact remaining costs come from enumeration, not UCS. Scaling
                # each bound separately also exercises admissible inconsistent h.
                h = {n: (expected[n] or 0) * random_source.random() for n in nodes}
                for start in nodes:
                    with self.subTest(example=example,start=start,goal=goal):
                        for route in (ucs(graph,start,goal), astar(graph,start,goal,h.__getitem__)):
                            if expected[start] is None:
                                self.assertIsNone(route)
                            else:
                                self.assertEqual(route.seconds, expected[start])
                                self.assertEqual((route.nodes[0],route.nodes[-1]),(start,goal))
                                total = 0
                                for a,b,r in zip(route.nodes,route.nodes[1:],route.roads):
                                    edge, = [e for e in graph.neighbors(a) if e.target == b and e.road_id == r]
                                    total += edge.seconds
                                self.assertEqual(route.seconds,total)

    def test_actual_heuristic_is_consistent_and_admissible_on_both_graphs(self):
        for number in (1,2,3):
            scenario = load_scenario(ROOT/f'Scenarios/Scenario{number}')
            graphs = [build_graph(scenario), build_bayesian_graph(scenario,infer_scenario(scenario),blocked_threshold=.2)]
            for graph in graphs:
                for goal in (n.id for n in scenario.nodes):
                    h = straight_line_heuristic(scenario,graph,goal)
                    self.assertEqual(h(goal),0)
                    for node in (n.id for n in scenario.nodes):
                        self.assertGreaterEqual(h(node),0)
                        route = ucs(graph,node,goal)
                        if route is not None:
                            self.assertLessEqual(h(node),route.seconds+1e-10)
                        for edge in graph.neighbors(node):
                            self.assertLessEqual(h(node),edge.seconds+h(edge.target)+1e-10)

    def test_simple_geometry_has_nonzero_bound_and_no_mutation(self):
        scenario, _ = fixture([incident()])
        scenario = replace(scenario,nodes=(Node('A','A',0,0,'normal'),Node('B','B',3,0,'normal'),Node('C','C',0,0,'normal')))
        graph = build_graph(scenario)
        before = {n.id: graph.neighbors(n.id) for n in scenario.nodes}
        h = straight_line_heuristic(scenario,graph,'B')
        self.assertEqual(h('A'),3)
        self.assertEqual(astar(graph,'A','B',h).seconds,5)
        self.assertEqual(before,{n.id: graph.neighbors(n.id) for n in scenario.nodes})

    def test_heuristic_rejects_unjustified_geometry(self):
        scenario, graph = fixture([incident()])
        bad = replace(scenario,nodes=tuple(replace(n,x=100) if n.id=='B' else n for n in scenario.nodes))
        with self.assertRaisesRegex(ValueError,'geometry'):
            straight_line_heuristic(bad,graph,'B')
        with self.assertRaises(ValueError):
            straight_line_heuristic(scenario,graph,'X')
        with self.assertRaises(ValueError):
            straight_line_heuristic(scenario,Graph(['A','B']),'B')

    def test_heuristic_rejects_invented_or_too_fast_edges(self):
        scenario, _ = fixture([incident()])
        for road_id, seconds in [('invented',5), ('A->B',1)]:
            graph = Graph(['A','B','C'])
            graph.add_edge('A','B',seconds,road_id)
            with self.assertRaisesRegex(ValueError,'Graph edge'):
                straight_line_heuristic(scenario,graph,'B')

    def test_no_roads_or_all_filtered_edges_are_supported(self):
        scenario, graph = fixture([incident()],edges=())
        h = straight_line_heuristic(scenario,graph,'B')
        self.assertIsNone(astar(graph,'A','B',h))
        self.assertEqual(astar(graph,'B','B',h).seconds,0)
        scenario = load_scenario(ROOT/'Scenarios/Scenario1')
        graph = build_bayesian_graph(scenario,infer_scenario(scenario),blocked_threshold=0)
        h = straight_line_heuristic(scenario,graph,'N1')
        self.assertIsNone(astar(graph,'H1','N1',h))
