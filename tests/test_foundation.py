import tempfile
import unittest
from pathlib import Path

from emergency_response.graph import Graph
from emergency_response.loaders import read_csv, read_json
from emergency_response.search import ucs


class SearchTests(unittest.TestCase):
    def test_cheaper_indirect_route_and_goal_not_on_discovery(self):
        g = Graph(["S", "A", "G", "X"])
        for s, t, c, r in [("S", "G", 9, "direct"), ("S", "A", 2, "sa"),
                            ("A", "G", 3, "ag"), ("A", "S", 0, "cycle")]:
            g.add_edge(s, t, c, r)
        route = ucs(g, "S", "G")
        self.assertEqual((route.nodes, route.roads, route.seconds),
                         (("S", "A", "G"), ("sa", "ag"), 5))
        self.assertIsNone(ucs(g, "S", "X"))
        self.assertIsNone(ucs(g, "G", "S"))

    def test_stale_frontier_entry(self):
        g = Graph(["S", "A", "B", "G"])
        for s, t, c in [("S", "A", 10), ("S", "B", 1), ("B", "A", 1), ("A", "G", 20)]:
            g.add_edge(s, t, c, s+t)
        self.assertEqual(ucs(g, "S", "G").seconds, 22)

    def test_parallel_edges_and_zero_cycle(self):
        g = Graph(["S", "G"])
        g.add_edge("S", "S", 0, "loop")
        g.add_edge("S", "G", 8, "slow")
        g.add_edge("S", "G", 2, "fast")
        self.assertEqual(ucs(g, "S", "G").roads, ("fast",))
        self.assertEqual(ucs(g, "S", "S").seconds, 0)

    def test_bad_inputs(self):
        g = Graph(["S", "G"])
        for cost in [-1, float("nan"), float("inf"), True]:
            with self.assertRaises(ValueError):
                g.add_edge("S", "G", cost, "road")
        with self.assertRaises(ValueError):
            g.add_edge("S", "missing", 1, "road")
        with self.assertRaises(ValueError):
            ucs(g, "missing", "G")
        with self.assertRaises(ValueError):
            Graph(["S", "S"])


class LoaderTests(unittest.TestCase):
    def test_raw_readers_preserve_ids_and_reject_malformed_input(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            path = Path(directory) / "input"
            path.write_text('\ufeffid,capability\n001,"rescue, first aid"\n', encoding="utf-8")
            self.assertEqual(read_csv(path), [{"id": "001", "capability": "rescue, first aid"}])
            for content in ["id,id\na,b\n", "id,x\na\n", "id\na,b\n"]:
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    read_csv(path)
            path.write_text('{"nodes": ["N1"]}', encoding="utf-8")
            self.assertEqual(read_json(path), {"nodes": ["N1"]})
            for content in ['{"x": 1, "x": 2}', '{"x": NaN}']:
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    read_json(path)


if __name__ == "__main__":
    unittest.main()
