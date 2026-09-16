import unittest

from PickNumber.future_engine import FutureInferenceEngine


class FutureInferenceEngineTests(unittest.TestCase):
    def test_gap_hazard_requires_100_condition_samples(self):
        engine = object.__new__(FutureInferenceEngine)
        engine.draws = [
            {"round": round_no, "numbers": (1, 2, 3, 4, 5, 6)}
            for round_no in range(1, 10)
        ]

        immediate = engine._gap_hazard_model()["0-0"]

        self.assertLess(immediate["samples"], 100)
        self.assertEqual(immediate["score"], 0.0)

    def test_supported_gap_hazard_uses_observed_rate(self):
        engine = object.__new__(FutureInferenceEngine)
        engine.draws = [
            {"round": round_no, "numbers": (1, 2, 3, 4, 5, 6)}
            for round_no in range(1, 30)
        ]

        immediate = engine._gap_hazard_model()["0-0"]

        self.assertGreaterEqual(immediate["samples"], 100)
        self.assertGreater(immediate["rate"], 6 / 45)
        self.assertGreater(immediate["score"], 0.0)

    def test_candidate_scores_balance_legacy_and_future_scales(self):
        engine = object.__new__(FutureInferenceEngine)
        candidates = [
            {"final_score": 1000.0, "future_score": 0.0},
            {"final_score": 1050.0, "future_score": 100.0},
            {"final_score": 900.0, "future_score": 0.0},
        ]

        engine._balance_candidate_scores(candidates)

        self.assertTrue(all("legacy_score" in item for item in candidates))
        self.assertTrue(
            all(item["score_calibration"] == "legacy_z_plus_future_z" for item in candidates)
        )
        self.assertGreater(candidates[1]["final_score"], candidates[0]["final_score"])

    def test_future_score_weight_can_disable_experimental_signal(self):
        engine = object.__new__(FutureInferenceEngine)
        engine.FUTURE_SCORE_WEIGHT = 0.0
        candidates = [
            {"final_score": 1000.0, "future_score": 0.0},
            {"final_score": 1050.0, "future_score": 100.0},
            {"final_score": 900.0, "future_score": 0.0},
        ]

        engine._balance_candidate_scores(candidates)

        self.assertEqual([item["final_score"] for item in candidates], [1000.0, 950.0, 900.0])
        self.assertTrue(
            all(item["score_calibration"] == "legacy_z_plus_0_future_z" for item in candidates)
        )


if __name__ == "__main__":
    unittest.main()
