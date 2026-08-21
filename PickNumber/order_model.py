"""Evidence-first probability model for Lotto 6/45.

The model deliberately treats historical effects as weak evidence. Number
inclusion rates are shrunk toward the uniform 6/45 rate, then converted into a
proper probability distribution over all C(45, 6) unordered combinations.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


NUMBER_MIN = 1
NUMBER_MAX = 45
PICK_COUNT = 6
COMBINATION_COUNT = math.comb(NUMBER_MAX, PICK_COUNT)
UNIFORM_COMBINATION_PROBABILITY = 1.0 / COMBINATION_COUNT


@dataclass(frozen=True)
class Draw:
    round: int
    numbers: tuple[int, ...]
    bonus: int | None = None


@dataclass(frozen=True)
class PortfolioGame:
    numbers: tuple[int, ...]
    probability: float
    relative_to_uniform: float


def _validate_numbers(numbers: Iterable[int]) -> tuple[int, ...]:
    values = tuple(sorted(int(number) for number in numbers))
    if len(values) != PICK_COUNT or len(set(values)) != PICK_COUNT:
        raise ValueError("A Lotto 6/45 combination must contain six unique numbers")
    if values[0] < NUMBER_MIN or values[-1] > NUMBER_MAX:
        raise ValueError("Lotto numbers must be between 1 and 45")
    return values


def load_draws(data_dir: Path, start_round: int = 1, end_round: int | None = None) -> list[Draw]:
    """Load canonical draw files while ignoring prediction and summary files."""
    draws_by_round: dict[int, Draw] = {}
    for path in data_dir.rglob("*.lotto"):
        if path.name in {"frequency.lotto", "latest.lotto"} or "_star" in path.name:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            round_number = int(payload["round"])
            numbers = _validate_numbers(payload["numbers"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError):
            continue
        if round_number < start_round or (end_round is not None and round_number > end_round):
            continue
        bonus = payload.get("bonus")
        draws_by_round[round_number] = Draw(
            round=round_number,
            numbers=numbers,
            bonus=int(bonus) if bonus is not None else None,
        )
    return [draws_by_round[round_number] for round_number in sorted(draws_by_round)]


def draw_data_digest(draws: Sequence[Draw]) -> str:
    canonical = [
        {"round": draw.round, "numbers": list(draw.numbers), "bonus": draw.bonus}
        for draw in draws
    ]
    encoded = json.dumps(canonical, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def elementary_symmetric(weights: Sequence[float], degree: int) -> float:
    """Return the elementary symmetric polynomial of the requested degree."""
    coefficients = [0.0] * (degree + 1)
    coefficients[0] = 1.0
    for weight in weights:
        for index in range(degree, 0, -1):
            coefficients[index] += coefficients[index - 1] * weight
    return coefficients[degree]


class BayesianOrderModel:
    """Strongly regularized inclusion model with a normalized combo likelihood."""

    model_id = "bayesian-order-v1"

    def __init__(self, prior_strength: float = 180.0):
        if prior_strength <= 0:
            raise ValueError("prior_strength must be positive")
        self.prior_strength = float(prior_strength)
        self.training_rounds = 0
        self.weights: dict[int, float] = {number: 1.0 for number in range(1, 46)}
        self._normalizer = float(COMBINATION_COUNT)

    def fit(self, draws: Sequence[Draw]) -> "BayesianOrderModel":
        counts = Counter(number for draw in draws for number in draw.numbers)
        expected_rate = PICK_COUNT / NUMBER_MAX
        raw_weights: dict[int, float] = {}
        for number in range(NUMBER_MIN, NUMBER_MAX + 1):
            posterior = (counts[number] + self.prior_strength * expected_rate) / (
                len(draws) + self.prior_strength
            )
            raw_weights[number] = posterior / (1.0 - posterior)

        # A shared scale cancels out after normalization. Geometric centering
        # keeps the dynamic range numerically stable and makes uniform == 1.
        geometric_mean = math.exp(sum(math.log(value) for value in raw_weights.values()) / NUMBER_MAX)
        self.weights = {number: value / geometric_mean for number, value in raw_weights.items()}
        self._normalizer = elementary_symmetric(list(self.weights.values()), PICK_COUNT)
        self.training_rounds = len(draws)
        return self

    def combination_probability(self, numbers: Iterable[int]) -> float:
        combination = _validate_numbers(numbers)
        numerator = math.prod(self.weights[number] for number in combination)
        return numerator / self._normalizer

    def log_probability(self, numbers: Iterable[int]) -> float:
        return math.log(self.combination_probability(numbers))

    def model_config(self) -> dict[str, float | str]:
        return {"model_id": self.model_id, "prior_strength": self.prior_strength}

    def generate_portfolio(
        self,
        game_count: int = 5,
        seed: int = 20260605,
        top_pool_size: int = 16,
        random_candidates: int = 1200,
        overlap_penalty: float = 0.22,
    ) -> list[PortfolioGame]:
        if not 1 <= game_count <= 5:
            raise ValueError("game_count must be between 1 and 5")
        if not PICK_COUNT <= top_pool_size <= NUMBER_MAX:
            raise ValueError("top_pool_size must be between 6 and 45")

        ranked_numbers = sorted(self.weights, key=lambda number: self.weights[number], reverse=True)
        candidates = set(itertools.combinations(sorted(ranked_numbers[:top_pool_size]), PICK_COUNT))

        # Keep every number reachable even when its posterior weight is weak.
        for number in range(NUMBER_MIN, NUMBER_MAX + 1):
            companions = [candidate for candidate in ranked_numbers if candidate != number][: PICK_COUNT - 1]
            candidates.add(tuple(sorted([number, *companions])))

        rng = random.Random(seed)
        population = list(range(NUMBER_MIN, NUMBER_MAX + 1))
        sample_weights = [self.weights[number] for number in population]
        for _ in range(random_candidates):
            available = population.copy()
            available_weights = sample_weights.copy()
            picked: list[int] = []
            while len(picked) < PICK_COUNT:
                number = rng.choices(available, weights=available_weights, k=1)[0]
                index = available.index(number)
                picked.append(number)
                available.pop(index)
                available_weights.pop(index)
            candidates.add(tuple(sorted(picked)))

        scored = sorted(
            ((self.combination_probability(candidate), candidate) for candidate in candidates),
            reverse=True,
        )
        best_probability = scored[0][0]
        selected: list[tuple[int, ...]] = []
        probabilities: dict[tuple[int, ...], float] = {}
        number_load = Counter()

        while len(selected) < game_count:
            best_candidate = None
            best_utility = -math.inf
            constraint_levels = (
                (0, 1),
                (1, 1),
                (2, 1),
                (2, 2),
                (3, 2),
                (4, 3),
                (5, game_count),
            )
            for maximum_overlap, maximum_number_load in constraint_levels:
                for probability, candidate in scored:
                    if candidate in selected:
                        continue
                    overlaps = [len(set(candidate) & set(chosen)) for chosen in selected]
                    if overlaps and max(overlaps) > maximum_overlap:
                        continue
                    if any(number_load[number] >= maximum_number_load for number in candidate):
                        continue
                    overlap_cost = sum((overlap / PICK_COUNT) ** 2 for overlap in overlaps)
                    load_cost = sum(number_load[number] ** 2 for number in candidate) / PICK_COUNT
                    probability_score = math.log(probability / best_probability)
                    utility = probability_score - overlap_penalty * overlap_cost - overlap_penalty * 0.18 * load_cost
                    if utility > best_utility:
                        best_utility = utility
                        best_candidate = candidate
                if best_candidate is not None:
                    break
            if best_candidate is None:
                raise RuntimeError("Unable to construct a complete portfolio")
            selected.append(best_candidate)
            probabilities[best_candidate] = self.combination_probability(best_candidate)
            number_load.update(best_candidate)

        return [
            PortfolioGame(
                numbers=combination,
                probability=probabilities[combination],
                relative_to_uniform=probabilities[combination] / UNIFORM_COMBINATION_PROBABILITY,
            )
            for combination in selected
        ]


def best_match(games: Sequence[PortfolioGame], actual: Iterable[int]) -> int:
    actual_set = set(_validate_numbers(actual))
    return max((len(set(game.numbers) & actual_set) for game in games), default=0)


def generate_uniform_portfolio(game_count: int = 5, seed: int = 20260605) -> list[PortfolioGame]:
    """Generate a reproducible, genuinely uniform ticket baseline."""
    if not 1 <= game_count <= 5:
        raise ValueError("game_count must be between 1 and 5")
    rng = random.Random(seed)
    combinations: set[tuple[int, ...]] = set()
    while len(combinations) < game_count:
        combinations.add(tuple(sorted(rng.sample(range(NUMBER_MIN, NUMBER_MAX + 1), PICK_COUNT))))
    return [
        PortfolioGame(
            numbers=numbers,
            probability=UNIFORM_COMBINATION_PROBABILITY,
            relative_to_uniform=1.0,
        )
        for numbers in sorted(combinations)
    ]
