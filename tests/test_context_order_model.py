import math
import unittest

from PickNumber.context_order_model import (
    ExtractionOrderConditionalModel,
    batch_observation_rounds,
    resolve_frozen_cohorts,
    run_frozen_acquisition_holdout_test,
    run_holdout_test,
    run_performance_spectrum,
)
from PickNumber.order_model import UNIFORM_COMBINATION_PROBABILITY


def make_records(count):
    records = []
    for index in range(count):
        start = (index * 7) % 45
        order = [((start + position * 8) % 45) + 1 for position in range(6)]
        records.append(
            {
                "round": index + 1,
                "review_status": "verified",
                "ordered_numbers": order,
            }
        )
    return records


class ExtractionOrderConditionalModelTests(unittest.TestCase):
    def test_empty_model_is_uniform_over_unordered_combinations(self):
        model = ExtractionOrderConditionalModel().fit([])
        probability = model.combination_probability([1, 2, 3, 4, 5, 6])
        self.assertAlmostEqual(probability, UNIFORM_COMBINATION_PROBABILITY, places=18)

    def test_position_history_changes_combination_probability(self):
        orders = [[1, 2, 3, 4, 5, 6] for _ in range(30)]
        model = ExtractionOrderConditionalModel(prior_strength=45).fit(orders)
        self.assertGreater(
            model.combination_probability([1, 2, 3, 4, 5, 6]),
            model.combination_probability([40, 41, 42, 43, 44, 45]),
        )
        self.assertTrue(math.isfinite(model.log_probability([1, 2, 3, 4, 5, 6])))

    def test_holdout_report_keeps_latest_records_for_test(self):
        report = run_holdout_test(
            make_records(100),
            prior_grid=(90.0, 180.0),
            validation_size=20,
            test_size=20,
        )
        self.assertEqual(report["partition"]["training_count"], 60)
        self.assertEqual(report["partition"]["test_rounds"], [81, 100])
        self.assertIn(report["decision"], {"accepted", "rejected"})

    def test_frozen_acquisition_holdout_keeps_cohorts_separate(self):
        records = make_records(200)
        report = run_frozen_acquisition_holdout_test(
            records,
            development_rounds=range(1, 101),
            holdout_rounds=range(101, 201),
            selected_prior_strength=180.0,
        )
        self.assertEqual(report["evaluation_design"], "frozen_acquisition_holdout")
        self.assertEqual(report["development_count"], 100)
        self.assertEqual(report["holdout_count"], 100)
        self.assertEqual(len(report["per_round"]), 100)
        self.assertEqual(report["per_round"][0]["round"], 101)

    def test_frozen_acquisition_holdout_rejects_overlap(self):
        with self.assertRaisesRegex(ValueError, "must be disjoint"):
            run_frozen_acquisition_holdout_test(
                make_records(200),
                development_rounds=range(1, 101),
                holdout_rounds=range(100, 200),
                selected_prior_strength=180.0,
            )

    def test_resolve_frozen_cohorts_excludes_prior_holdout(self):
        development = resolve_frozen_cohorts(
            set(range(1, 301)),
            set(range(201, 301)),
            set(range(101, 201)),
            expected_development=100,
        )
        self.assertEqual(development, set(range(1, 101)))

        with self.assertRaisesRegex(ValueError, "must be disjoint"):
            resolve_frozen_cohorts(
                set(range(1, 301)),
                set(range(200, 301)),
                set(range(101, 201)),
                expected_development=100,
            )

    def test_batch_observation_rounds_excludes_rejected_selection(self):
        batch = {
            "rounds": [3, 2, 1],
            "reviewed_rows": [{"round": 3}, {"round": 1}],
            "rejected_rows": [{"round": 2, "reason": "missing draw footage"}],
        }
        self.assertEqual(batch_observation_rounds(batch), {1, 3})
        self.assertEqual(batch_observation_rounds({"rounds": [5, 4]}), {4, 5})

    def test_performance_spectrum_returns_two_worst_median_and_two_best(self):
        records = make_records(200)
        report = run_performance_spectrum(
            records,
            development_rounds=range(1, 101),
            holdout_rounds=range(101, 201),
            candidate_samples=100,
        )
        variants = report["variants"]
        self.assertEqual(len(variants), 5)
        self.assertEqual(
            [variant["category"] for variant in variants],
            ["worst", "worst", "median", "best", "best"],
        )
        self.assertEqual(len({tuple(variant["numbers"]) for variant in variants}), 5)
        self.assertTrue(all(len(variant["numbers"]) == 6 for variant in variants))
        scores = [variant["holdout_mean_log_loss_improvement_vs_uniform"] for variant in variants]
        self.assertEqual(scores, sorted(scores))
        self.assertTrue(report["experimental_only"])
        self.assertFalse(report["accepted_for_live_predictions"])
        self.assertEqual(report["target_round"], 201)


if __name__ == "__main__":
    unittest.main()
