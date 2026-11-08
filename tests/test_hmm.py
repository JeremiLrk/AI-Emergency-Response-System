"""Forward math and actual directed historical data; no simulation clock involved.

Each unittest method takes self, requires readable supplied scenarios, and returns
None on successful assertions. Fixtures never modify source scenario files.
"""
import copy
from dataclasses import replace
from itertools import product
from pathlib import Path
import unittest

from emergency_response.hmm import STATES, forward_filter, infer_traffic
from emergency_response.loaders import load_scenario
from emergency_response.models import TrafficObservation

ROOT = Path(__file__).resolve().parents[1]


class ForwardTests(unittest.TestCase):
    def setUp(self):
        """Load actual Scenario2 for each independent test; no input changes."""
        self.scenario = load_scenario(ROOT / "Scenarios/Scenario2")

    def test_worked_actual_sequence_all_prefixes(self):
        rows = self.scenario.traffic_history[("H2", "N8")]
        sequence = [r.traffic_observation for r in rows]
        self.assertEqual(sequence, ["Low", "Medium", "High", "Medium", "High"])
        expected = [(.8781558726673985,.11525795828759605,.006586169045005488),
            (.37657944935979654,.5963661116062694,.027054439033934046),
            (.041359105118473086,.4213486764615951,.5372922184199318),
            (.049706783669628204,.7397306328923715,.2105625834380003),
            (.010113305926110006,.2822202734116272,.7076664206622628)]
        for n, target in enumerate(expected, 1):
            actual = forward_filter(self.scenario.traffic_probabilities, sequence[:n])
            for state, value in zip(STATES, target):
                self.assertAlmostEqual(actual[state], value, places=13)

    def test_forward_matches_enumeration_of_hidden_sequences(self):
        model = self.scenario.traffic_probabilities
        observations = ["Low", "Medium", "High"]
        weights = dict.fromkeys(STATES, 0.0)
        for hidden in product(STATES, repeat=3):
            probability = model["initial"][hidden[0]]*model["emission"][hidden[0]][observations[0]]
            for k in range(1, 3):
                probability *= model["transition"][hidden[k-1]][hidden[k]]*model["emission"][hidden[k]][observations[k]]
            weights[hidden[-1]] += probability
        actual = forward_filter(model, observations)
        for state in STATES:
            self.assertAlmostEqual(actual[state], weights[state]/sum(weights.values()), places=14)

    def test_missing_history_uses_own_prior_and_direction(self):
        traffic = infer_traffic(self.scenario)
        self.assertEqual(traffic[("N8", "H2")].probabilities, {"Low": .5, "Medium": .35, "High": .15})
        self.assertTrue(traffic[("N8", "H2")].prior_only)
        self.assertFalse(traffic[("H2", "N8")].prior_only)
        s3 = load_scenario(ROOT / "Scenarios/Scenario3")
        self.assertEqual(forward_filter(s3.traffic_probabilities, []), {"Low": .6, "Medium": .3, "High": .1})

    def test_all_scenarios_coverage_counts_and_no_mutation(self):
        for number, histories, observations in ((1,14,140),(2,3,15),(3,10,100)):
            scenario = load_scenario(ROOT / f"Scenarios/Scenario{number}")
            before = copy.deepcopy(scenario)
            result = infer_traffic(scenario)
            self.assertEqual(set(result), {r.key for r in scenario.roads})
            self.assertEqual(sum(not b.prior_only for b in result.values()), histories)
            self.assertEqual(sum(b.observation_count for b in result.values()), observations)
            for belief in result.values():
                self.assertAlmostEqual(sum(belief.probabilities.values()), 1)
                self.assertEqual(set(belief.probabilities), set(STATES))
            self.assertEqual(scenario, before)

    def test_history_order_sorted_without_mutation(self):
        s = self.scenario
        history = dict(s.traffic_history)
        history[("H2", "N8")] = tuple(reversed(history[("H2", "N8")]))
        self.assertEqual(infer_traffic(replace(s, traffic_history=history)), infer_traffic(s))

    def test_invalid_histories_rejected(self):
        for rows in ((TrafficObservation(2,"H2","N8","Low"),),
                     (TrafficObservation(1,"H2","N8","Low"),)*2,
                     (TrafficObservation(True,"H2","N8","Low"),),
                     (TrafficObservation(1,"N8","H2","Low"),)):
            with self.assertRaises(ValueError):
                infer_traffic(replace(self.scenario, traffic_history={("H2","N8"): rows}))
        with self.assertRaises(ValueError):
            infer_traffic(replace(self.scenario, traffic_history={("unknown","road"): ()}))

    def test_invalid_label_and_zero_likelihood(self):
        with self.assertRaises(ValueError):
            forward_filter(self.scenario.traffic_probabilities, ["Blocked"])
        model = copy.deepcopy(self.scenario.traffic_probabilities)
        for state in STATES:
            model["emission"][state] = {"Low": 1., "Medium": 0., "High": 0.}
        with self.assertRaisesRegex(ValueError, "zero likelihood"):
            forward_filter(model, ["High"])

    def test_long_sequence_normalized_and_not_underflowed(self):
        result = forward_filter(self.scenario.traffic_probabilities, ["High"]*10000)
        self.assertAlmostEqual(sum(result.values()), 1)
        self.assertGreater(result["High"], .9)


if __name__ == "__main__":
    unittest.main()
