import unittest

from StarNumber import StarNumberGenerator


class StarNumberVerificationTests(unittest.TestCase):
    def test_uniform_baseline_is_reproducible_and_unique(self):
        first = StarNumberGenerator._uniform_baseline_games(5, 1242)
        second = StarNumberGenerator._uniform_baseline_games(5, 1242)

        self.assertEqual(first, second)
        self.assertEqual(len({tuple(game) for game in first}), 5)
        self.assertTrue(all(len(game) == 6 and len(set(game)) == 6 for game in first))

    def test_mean_95_interval_reports_mean_uncertainty(self):
        interval = StarNumberGenerator._mean_95_interval([1, 1, -1, -1])

        self.assertLess(interval[0], 0)
        self.assertGreater(interval[1], 0)

    def test_theoretical_uniform_best_distribution_is_exact(self):
        distribution = StarNumberGenerator._theoretical_uniform_best_distribution(5)
        expected_best = sum(matches * probability for matches, probability in distribution.items())

        self.assertAlmostEqual(sum(distribution.values()), 1.0)
        self.assertAlmostEqual(expected_best, 1.7289354902)


if __name__ == "__main__":
    unittest.main()
