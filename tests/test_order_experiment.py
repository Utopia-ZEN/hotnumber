import json
import math
import tempfile
import unittest
from pathlib import Path

from PickNumber.order_experiment import PredictionLedger, run_walk_forward
from PickNumber.order_model import (
    COMBINATION_COUNT,
    UNIFORM_COMBINATION_PROBABILITY,
    BayesianOrderModel,
    Draw,
    draw_data_digest,
    generate_uniform_portfolio,
)


def make_draw(round_number, offset=0):
    numbers = tuple(sorted((((round_number * 7 + offset + index * 6) % 45) + 1) for index in range(6)))
    if len(set(numbers)) < 6:
        numbers = tuple(range(1, 7))
    return Draw(round=round_number, numbers=numbers, bonus=45)


class BayesianOrderModelTests(unittest.TestCase):
    def test_empty_model_is_exactly_uniform(self):
        model = BayesianOrderModel().fit([])
        probability = model.combination_probability((1, 2, 3, 4, 5, 6))
        self.assertAlmostEqual(probability, UNIFORM_COMBINATION_PROBABILITY, places=18)
        self.assertEqual(COMBINATION_COUNT, 8_145_060)

    def test_posterior_prefers_repeated_numbers_but_remains_normalized(self):
        draws = [Draw(round=index, numbers=(1, 2, 3, 4, 5, 6)) for index in range(1, 31)]
        model = BayesianOrderModel(prior_strength=180).fit(draws)
        favored = model.combination_probability((1, 2, 3, 4, 5, 6))
        unfavored = model.combination_probability((40, 41, 42, 43, 44, 45))
        self.assertGreater(favored, unfavored)
        self.assertGreater(model._normalizer, 0)

    def test_portfolio_is_unique_and_diversified(self):
        draws = [make_draw(index) for index in range(1, 80)]
        games = BayesianOrderModel().fit(draws).generate_portfolio(game_count=5, random_candidates=100)
        combinations = [game.numbers for game in games]
        self.assertEqual(len(combinations), len(set(combinations)))
        self.assertTrue(all(len(set(game)) == 6 for game in combinations))
        self.assertGreaterEqual(len(set().union(*map(set, combinations))), 24)

    def test_uniform_portfolio_is_reproducible_and_uniform(self):
        first = generate_uniform_portfolio(game_count=5, seed=99)
        second = generate_uniform_portfolio(game_count=5, seed=99)
        self.assertEqual(first, second)
        self.assertTrue(all(game.relative_to_uniform == 1.0 for game in first))


class LedgerTests(unittest.TestCase):
    def test_ledger_detects_tampering_and_blocks_duplicate_prediction(self):
        draws = [make_draw(index) for index in range(1, 40)]
        model = BayesianOrderModel().fit(draws)
        games = model.generate_portfolio(game_count=2, random_candidates=50)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ledger.jsonl"
            ledger = PredictionLedger(path)
            ledger.append_prediction(40, draws, model, games, seed=7)
            self.assertEqual(len(ledger.records()), 1)
            with self.assertRaises(ValueError):
                ledger.append_prediction(40, draws, model, games, seed=7)

            record = json.loads(path.read_text(encoding="utf-8"))
            record["target_round"] = 41
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                ledger.records()

    def test_owner_pick_set_and_group_evaluation_are_sealed(self):
        draws = [make_draw(index) for index in range(1, 40)]
        model = BayesianOrderModel().fit(draws)
        model_games = model.generate_portfolio(game_count=5, random_candidates=50)
        random_games = generate_uniform_portfolio(game_count=5, seed=77)
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = PredictionLedger(Path(temp_dir) / "ledger.jsonl")
            ledger.append_prediction(40, draws, model, model_games, seed=7)
            owner_set = ledger.append_owner_pick_set(40, 77, random_games)
            self.assertEqual(len(owner_set["games"]), 10)
            self.assertEqual({game["group"] for game in owner_set["games"]}, {"order_model", "uniform_random"})
            evaluation = ledger.append_evaluation(make_draw(40))
            self.assertEqual(set(evaluation["group_summary"]), {"order_model", "uniform_random"})
            self.assertEqual(len(evaluation["games"]), 10)

    def test_digest_changes_with_draw_data(self):
        original = [make_draw(index) for index in range(1, 5)]
        changed = [*original[:-1], make_draw(4, offset=1)]
        self.assertNotEqual(draw_data_digest(original), draw_data_digest(changed))


class WalkForwardTests(unittest.TestCase):
    def test_walk_forward_uses_only_prior_rounds(self):
        draws = [make_draw(index) for index in range(1, 24)]
        report = run_walk_forward(draws, min_train_rounds=20, games_per_round=2)
        self.assertEqual(report["first_evaluated_round"], 21)
        self.assertEqual(report["last_evaluated_round"], 23)
        self.assertEqual(report["evaluated_rounds"], 3)
        self.assertTrue(math.isfinite(report["average_log_loss"]))
        self.assertEqual(len(report["log_loss_improvement_95pct_interval"]), 2)


if __name__ == "__main__":
    unittest.main()
