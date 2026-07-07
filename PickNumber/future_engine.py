import itertools
import math
import random
from collections import Counter

from PickNumber.picknumber_analysis import (
    SEED,
    START_ROUND,
    build_stats,
    load_draws,
    pattern_key,
    score_candidate,
    select_diverse,
)


class FutureInferenceEngine:
    """Statistical ensemble generator for future lottery combinations.

    This engine does not assume that past draws cause future draws. It treats
    historical data as weak evidence for constructing balanced, information-rich
    candidate sets while penalizing instability and overfit patterns.
    """

    def __init__(self, start_round=START_ROUND, end_round=None, seed=SEED):
        self.start_round = start_round
        self.end_round = end_round or self._latest_round()
        self.seed = seed
        self.draws = load_draws(start_round, self.end_round)
        self.stats = build_stats(self.draws)

    def _latest_round(self):
        latest = load_draws(1, 9999)
        if not latest:
            return START_ROUND
        return latest[-1]["round"]

    def generate(self, game_count=6, candidate_budget=90000):
        candidates = self._build_candidates(candidate_budget)
        picks = select_diverse(candidates, limit=game_count)
        if len(picks) < game_count:
            raise RuntimeError(f"Could not produce {game_count} future inference picks")
        return self.draws, self.stats, picks

    def _build_candidates(self, candidate_budget):
        rng = random.Random(self.seed + 4049)
        number_model = self._number_model()
        top_pairs = self._top_lift_pairs(number_model, 120)
        top_triples = self._top_lift_triples(number_model, 80)

        pools = self._candidate_pools(number_model, top_pairs, top_triples)
        candidates = []
        seen = set()

        for strategy, pool, weight_boost in pools:
            clean_pool = sorted(set(pool))
            weights = [max(0.01, number_model[n]["weight"] * weight_boost.get(n, 1.0)) for n in clean_pool]
            iterations = max(2000, candidate_budget // len(pools))

            for _ in range(iterations):
                nums = self._weighted_unique_sample(rng, clean_pool, weights, 6)
                self._add_scored_candidate(candidates, seen, nums, number_model, strategy)

        all_nums = list(range(1, 46))
        for pair in top_pairs[:90]:
            base = [n for n in all_nums if n not in pair]
            weights = [number_model[n]["weight"] for n in base]
            for _ in range(350):
                nums = sorted(set(pair) | set(self._weighted_unique_sample(rng, base, weights, 4)))
                self._add_scored_candidate(candidates, seen, nums, number_model, "I_future_pair_lift")

        for triple in top_triples[:45]:
            base = [n for n in all_nums if n not in triple]
            weights = [number_model[n]["weight"] for n in base]
            for _ in range(220):
                nums = sorted(set(triple) | set(self._weighted_unique_sample(rng, base, weights, 3)))
                self._add_scored_candidate(candidates, seen, nums, number_model, "J_future_triple_lift")

        return candidates

    def _candidate_pools(self, number_model, top_pairs, top_triples):
        by_weight = sorted(range(1, 46), key=lambda n: number_model[n]["weight"], reverse=True)
        by_gap = sorted(range(1, 46), key=lambda n: number_model[n]["gap_score"], reverse=True)
        by_momentum = sorted(range(1, 46), key=lambda n: number_model[n]["momentum_score"], reverse=True)
        by_stability = sorted(range(1, 46), key=lambda n: number_model[n]["stability_score"], reverse=True)
        pair_nums = [n for pair in top_pairs[:40] for n in pair]
        triple_nums = [n for triple in top_triples[:30] for n in triple]

        return [
            ("I_future_posterior", by_weight[:28], {}),
            ("I_future_momentum_gap", by_momentum[:18] + by_gap[:18], {}),
            ("I_future_lift_bridge", pair_nums + triple_nums + by_stability[:12], {}),
            ("I_future_stable_tail", by_stability[:24] + by_gap[:12], {}),
            ("I_future_anti_overfit", list(range(1, 46)), {n: 1.4 for n in by_gap[:14]}),
        ]

    def _weighted_unique_sample(self, rng, nums, weights, k):
        selected = []
        available = list(nums)
        available_weights = list(weights)
        while len(selected) < k and available:
            pick = rng.choices(available, weights=available_weights, k=1)[0]
            idx = available.index(pick)
            selected.append(pick)
            available.pop(idx)
            available_weights.pop(idx)
        return sorted(selected)

    def _add_scored_candidate(self, candidates, seen, nums, number_model, strategy):
        nums = tuple(sorted(nums))
        if len(nums) != 6 or nums in seen:
            return
        seen.add(nums)

        scored = score_candidate(
            nums,
            self.stats,
            self.end_round - self.start_round + 1,
            self.start_round,
            self.end_round,
        )
        if not scored:
            return

        future = self._future_score(nums, number_model)
        scored.update(future)
        scored["strategy"] = strategy
        scored["final_score"] = round(scored["final_score"] + future["future_score"], 2)
        candidates.append(scored)

    def _number_model(self):
        windows = [30, 80, 180, len(self.draws)]
        expected_rate = 6 / 45
        model = {}

        for n in range(1, 46):
            window_scores = []
            for window in windows:
                subset = self.draws[-window:] if len(self.draws) >= window else self.draws
                observed = sum(1 for draw in subset if n in draw["numbers"])
                expected = len(subset) * expected_rate
                variance = max(1e-9, len(subset) * expected_rate * (1 - expected_rate))
                z = (observed - expected) / math.sqrt(variance)
                posterior = (observed + 1.2) / (len(subset) + 9.0)
                window_scores.append((z, posterior))

            momentum_score = max(0.0, window_scores[0][0]) * 7.5 + max(0.0, window_scores[1][0]) * 4.5
            long_score = max(0.0, window_scores[-1][0]) * 2.0
            posterior_score = sum(p for _, p in window_scores) * 18.0

            last_seen = self.stats["last_seen"].get(n, self.start_round - 1)
            gap = self.end_round - last_seen
            median_gap = 45 / 6
            gap_score = math.log1p(max(0, gap - median_gap)) * 5.5

            z_values = [z for z, _ in window_scores]
            stability_penalty = self._stddev(z_values) * 3.5
            stability_score = max(0.0, 12.0 - stability_penalty)
            weight = 1.0 + posterior_score + momentum_score + long_score + gap_score + stability_score

            model[n] = {
                "weight": weight,
                "posterior_score": posterior_score,
                "momentum_score": momentum_score,
                "gap_score": gap_score,
                "stability_score": stability_score,
                "stability_penalty": stability_penalty,
                "last_gap": gap,
            }

        return model

    def _top_lift_pairs(self, number_model, limit):
        total = len(self.draws)
        pair_counts = self.stats["pair"]
        freq = self.stats["freq"]
        scored = []

        for pair, count in pair_counts.items():
            a, b = pair
            pa = (freq[a] + 1) / (total + 2)
            pb = (freq[b] + 1) / (total + 2)
            pab = (count + 0.5) / (total + 1)
            lift = pab / max(1e-9, pa * pb)
            posterior = number_model[a]["weight"] + number_model[b]["weight"]
            scored.append((lift * 10 + posterior * 0.1 + count, pair))

        return [pair for _, pair in sorted(scored, reverse=True)[:limit]]

    def _top_lift_triples(self, number_model, limit):
        total = len(self.draws)
        triple_counts = self.stats["triple"]
        freq = self.stats["freq"]
        scored = []

        for triple, count in triple_counts.items():
            probs = [(freq[n] + 1) / (total + 2) for n in triple]
            pabc = (count + 0.25) / (total + 1)
            lift = pabc / max(1e-9, probs[0] * probs[1] * probs[2])
            posterior = sum(number_model[n]["weight"] for n in triple)
            scored.append((math.log1p(lift) * 12 + posterior * 0.05 + count, triple))

        return [triple for _, triple in sorted(scored, reverse=True)[:limit]]

    def _future_score(self, nums, number_model):
        number_part = sum(number_model[n]["posterior_score"] for n in nums)
        momentum_part = sum(number_model[n]["momentum_score"] for n in nums)
        gap_part = sum(number_model[n]["gap_score"] for n in nums)
        stability_part = sum(number_model[n]["stability_score"] for n in nums)
        uncertainty_penalty = sum(number_model[n]["stability_penalty"] for n in nums) * 0.6
        lift_part = self._combo_lift_score(nums)
        pattern_part = self._pattern_probability_score(nums)

        future_score = (
            number_part * 0.55
            + momentum_part * 0.85
            + gap_part * 0.55
            + stability_part * 0.45
            + lift_part
            + pattern_part
            - uncertainty_penalty
        )

        return {
            "future_score": round(future_score, 2),
            "posterior_score": round(number_part, 2),
            "momentum_score": round(momentum_part, 2),
            "gap_pressure_score": round(gap_part, 2),
            "lift_score": round(lift_part, 2),
            "pattern_probability_score": round(pattern_part, 2),
            "stability_score": round(stability_part, 2),
            "uncertainty_penalty": round(uncertainty_penalty, 2),
        }

    def _combo_lift_score(self, nums):
        pair_counts = self.stats["pair"]
        triple_counts = self.stats["triple"]
        pair_score = sum(math.log1p(pair_counts[p]) for p in itertools.combinations(nums, 2))
        triple_score = sum(math.log1p(triple_counts[t]) for t in itertools.combinations(nums, 3))
        return pair_score * 0.75 + triple_score * 0.35

    def _pattern_probability_score(self, nums):
        total = len(self.draws)
        pk = pattern_key(nums)
        score = 0.0
        for key, value in pk.items():
            if key == "ac":
                continue
            counter = self.stats["pattern_counters"][key]
            probability = (counter.get(value, 0) + 1) / (total + len(counter) + 1)
            score += math.log(probability + 1e-9) * 3.0
        return score + 60.0

    def _stddev(self, values):
        if not values:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        return math.sqrt(variance)


def generate_future_numbers(
    game_count=6,
    start_round=START_ROUND,
    end_round=None,
    seed=SEED,
    candidate_budget=90000,
):
    engine = FutureInferenceEngine(start_round=start_round, end_round=end_round, seed=seed)
    return engine.generate(game_count=game_count, candidate_budget=candidate_budget)
