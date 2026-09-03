"""Conditional model and holdout test for verified extraction-order data."""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Sequence

from PickNumber.draw_context_collection import (
    DEFAULT_CONTEXT_DIR,
    audit_records,
    read_jsonl,
    require_model_gate,
    utc_now,
)
from PickNumber.order_model import (
    UNIFORM_COMBINATION_PROBABILITY,
    BayesianOrderModel,
    Draw,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "outputs" / "order_experiment" / "context_order_report.json"
DEFAULT_SPECTRUM_OUTPUT = (
    ROOT / "outputs" / "order_experiment" / "context_order_spectrum_5.json"
)
POSITION_COUNT = 6
NUMBER_COUNT = 45
FULL_MASK = (1 << POSITION_COUNT) - 1


def _validate_order(values: Iterable[int]) -> tuple[int, ...]:
    order = tuple(int(value) for value in values)
    if len(order) != POSITION_COUNT or len(set(order)) != POSITION_COUNT:
        raise ValueError("Extraction order must contain six unique numbers")
    if min(order) < 1 or max(order) > NUMBER_COUNT:
        raise ValueError("Extraction-order numbers must be between 1 and 45")
    return order


def _assignment_sum(weights: Sequence[Sequence[float]], numbers: Sequence[int]) -> float:
    """Sum weights over all one-to-one number-to-position assignments."""
    dp = [0.0] * (1 << POSITION_COUNT)
    dp[0] = 1.0
    for number in numbers:
        previous = dp
        dp = previous.copy()
        for mask, subtotal in enumerate(previous):
            if subtotal == 0.0:
                continue
            for position in range(POSITION_COUNT):
                bit = 1 << position
                if not mask & bit:
                    dp[mask | bit] += subtotal * weights[position][number]
    return dp[FULL_MASK]


class ExtractionOrderConditionalModel:
    """Position-specific categorical model, conditioned on six distinct balls."""

    model_id = "extraction-order-conditional-v1"

    def __init__(self, prior_strength: float = 180.0):
        if prior_strength <= 0:
            raise ValueError("prior_strength must be positive")
        self.prior_strength = float(prior_strength)
        self.training_rounds = 0
        self.weights = [[0.0] + [1.0] * NUMBER_COUNT for _ in range(POSITION_COUNT)]
        self._normalizer = math.perm(NUMBER_COUNT, POSITION_COUNT)

    def fit(self, orders: Sequence[Sequence[int]]) -> "ExtractionOrderConditionalModel":
        validated = [_validate_order(order) for order in orders]
        counts = [Counter(order[position] for order in validated) for position in range(POSITION_COUNT)]
        for position in range(POSITION_COUNT):
            raw = [
                (counts[position][number] + self.prior_strength / NUMBER_COUNT)
                / (len(validated) + self.prior_strength)
                for number in range(1, NUMBER_COUNT + 1)
            ]
            geometric_mean = math.exp(sum(math.log(value) for value in raw) / NUMBER_COUNT)
            self.weights[position] = [0.0] + [value / geometric_mean for value in raw]

        # Iterating all 45 numbers and 64 position masks exactly sums every
        # distinct ordered six-ball outcome without enumerating 5.8B orders.
        self._normalizer = _assignment_sum(self.weights, range(1, NUMBER_COUNT + 1))
        self.training_rounds = len(validated)
        return self

    def combination_probability(self, numbers: Iterable[int]) -> float:
        combination = tuple(sorted(_validate_order(numbers)))
        return _assignment_sum(self.weights, combination) / self._normalizer

    def log_probability(self, numbers: Iterable[int]) -> float:
        return math.log(self.combination_probability(numbers))


def _mean_interval(values: Sequence[float]) -> tuple[float, list[float]]:
    mean = statistics.fmean(values)
    if len(values) < 2:
        return mean, [mean, mean]
    margin = 1.96 * statistics.stdev(values) / math.sqrt(len(values))
    return mean, [mean - margin, mean + margin]


def _ordered_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (
            record
            for record in records
            if record.get("review_status") == "verified" and record.get("ordered_numbers")
        ),
        key=lambda record: int(record["round"]),
    )


def run_holdout_test(
    records: Iterable[dict[str, Any]],
    prior_grid: Sequence[float] = (45.0, 90.0, 180.0, 360.0),
    validation_size: int = 20,
    test_size: int = 20,
    minimum_sample: int = 100,
) -> dict[str, Any]:
    observations = _ordered_records(records)
    if len(observations) < minimum_sample:
        raise ValueError(f"At least {minimum_sample} verified ordered observations are required")
    if validation_size < 1 or test_size < 2 or len(observations) <= validation_size + test_size:
        raise ValueError("Train, validation, and test partitions must all be non-empty")

    test_start = len(observations) - test_size
    validation_start = test_start - validation_size
    validation_scores: dict[str, float] = {}
    for prior in prior_grid:
        improvements = []
        for index in range(validation_start, test_start):
            history = observations[:index]
            model = ExtractionOrderConditionalModel(prior).fit(
                [record["ordered_numbers"] for record in history]
            )
            probability = model.combination_probability(observations[index]["ordered_numbers"])
            improvements.append(math.log(probability) - math.log(UNIFORM_COMBINATION_PROBABILITY))
        validation_scores[str(prior)] = statistics.fmean(improvements)

    selected_prior = max(prior_grid, key=lambda value: validation_scores[str(value)])
    improvements = []
    baseline_improvements = []
    per_round = []
    for index in range(test_start, len(observations)):
        history = observations[:index]
        actual = observations[index]
        order_model = ExtractionOrderConditionalModel(selected_prior).fit(
            [record["ordered_numbers"] for record in history]
        )
        baseline_draws = [
            Draw(round=int(record["round"]), numbers=tuple(sorted(record["ordered_numbers"])))
            for record in history
        ]
        baseline = BayesianOrderModel(prior_strength=selected_prior).fit(baseline_draws)
        conditional_log = order_model.log_probability(actual["ordered_numbers"])
        baseline_log = baseline.log_probability(actual["ordered_numbers"])
        uniform_log = math.log(UNIFORM_COMBINATION_PROBABILITY)
        improvements.append(conditional_log - uniform_log)
        baseline_improvements.append(baseline_log - uniform_log)
        per_round.append(
            {
                "round": int(actual["round"]),
                "conditional_log_loss": -conditional_log,
                "uniform_log_loss": -uniform_log,
                "unconditional_baseline_log_loss": -baseline_log,
            }
        )

    mean_improvement, interval = _mean_interval(improvements)
    mean_baseline = statistics.fmean(baseline_improvements)
    accepted = interval[0] > 0.0 and mean_improvement > mean_baseline
    return {
        "generated_at_utc": utc_now(),
        "model_id": ExtractionOrderConditionalModel.model_id,
        "minimum_sample": minimum_sample,
        "verified_ordered_records": len(observations),
        "partition": {
            "training_count": validation_start,
            "validation_count": validation_size,
            "test_count": test_size,
            "training_rounds": [int(observations[0]["round"]), int(observations[validation_start - 1]["round"])],
            "validation_rounds": [int(observations[validation_start]["round"]), int(observations[test_start - 1]["round"])],
            "test_rounds": [int(observations[test_start]["round"]), int(observations[-1]["round"])],
        },
        "prior_validation_mean_log_improvement": validation_scores,
        "selected_prior_strength": selected_prior,
        "test_mean_log_loss_improvement_vs_uniform": mean_improvement,
        "test_log_loss_improvement_95pct_interval": interval,
        "unconditional_baseline_mean_log_loss_improvement_vs_uniform": mean_baseline,
        "accepted_for_live_predictions": accepted,
        "decision": "accepted" if accepted else "rejected",
        "per_round": per_round,
    }


def run_frozen_acquisition_holdout_test(
    records: Iterable[dict[str, Any]],
    development_rounds: Iterable[int],
    holdout_rounds: Iterable[int],
    selected_prior_strength: float,
    minimum_holdout: int = 100,
) -> dict[str, Any]:
    """Evaluate a frozen model on records acquired after model selection."""
    observations = _ordered_records(records)
    by_round = {int(record["round"]): record for record in observations}
    development_ids = {int(round_number) for round_number in development_rounds}
    holdout_ids = {int(round_number) for round_number in holdout_rounds}
    if development_ids & holdout_ids:
        raise ValueError("Development and acquisition-holdout rounds must be disjoint")
    if len(holdout_ids) < minimum_holdout:
        raise ValueError(f"At least {minimum_holdout} acquisition-holdout rounds are required")

    missing = (development_ids | holdout_ids) - by_round.keys()
    if missing:
        raise ValueError(f"Missing verified ordered observations for rounds: {sorted(missing)}")

    development = [by_round[round_number] for round_number in sorted(development_ids)]
    holdout = [by_round[round_number] for round_number in sorted(holdout_ids)]
    order_model = ExtractionOrderConditionalModel(selected_prior_strength).fit(
        [record["ordered_numbers"] for record in development]
    )
    baseline_draws = [
        Draw(round=int(record["round"]), numbers=tuple(sorted(record["ordered_numbers"])))
        for record in development
    ]
    baseline = BayesianOrderModel(prior_strength=selected_prior_strength).fit(baseline_draws)

    uniform_log = math.log(UNIFORM_COMBINATION_PROBABILITY)
    improvements = []
    baseline_improvements = []
    per_round = []
    for actual in holdout:
        conditional_log = order_model.log_probability(actual["ordered_numbers"])
        baseline_log = baseline.log_probability(actual["ordered_numbers"])
        improvements.append(conditional_log - uniform_log)
        baseline_improvements.append(baseline_log - uniform_log)
        per_round.append(
            {
                "round": int(actual["round"]),
                "conditional_log_loss": -conditional_log,
                "uniform_log_loss": -uniform_log,
                "unconditional_baseline_log_loss": -baseline_log,
            }
        )

    mean_improvement, interval = _mean_interval(improvements)
    mean_baseline = statistics.fmean(baseline_improvements)
    accepted = interval[0] > 0.0 and mean_improvement > mean_baseline
    return {
        "generated_at_utc": utc_now(),
        "model_id": ExtractionOrderConditionalModel.model_id,
        "evaluation_design": "frozen_acquisition_holdout",
        "development_count": len(development),
        "development_rounds": [int(development[0]["round"]), int(development[-1]["round"])],
        "holdout_count": len(holdout),
        "holdout_rounds": [int(holdout[0]["round"]), int(holdout[-1]["round"])],
        "selected_prior_strength": selected_prior_strength,
        "holdout_mean_log_loss_improvement_vs_uniform": mean_improvement,
        "holdout_log_loss_improvement_95pct_interval": interval,
        "unconditional_baseline_mean_log_loss_improvement_vs_uniform": mean_baseline,
        "accepted_for_live_predictions": accepted,
        "decision": "accepted" if accepted else "rejected",
        "per_round": per_round,
    }


def _sample_order(model: ExtractionOrderConditionalModel, rng: random.Random) -> tuple[int, ...]:
    remaining = list(range(1, NUMBER_COUNT + 1))
    order = []
    for position in range(POSITION_COUNT):
        weights = [model.weights[position][number] for number in remaining]
        selected = rng.choices(remaining, weights=weights, k=1)[0]
        order.append(selected)
        remaining.remove(selected)
    return tuple(sorted(order))


def _select_spectrum_game(
    model: ExtractionOrderConditionalModel,
    seed: int,
    selected_games: Sequence[Sequence[int]],
    candidate_samples: int,
) -> tuple[tuple[int, ...], float]:
    rng = random.Random(seed)
    candidates = {_sample_order(model, rng) for _ in range(candidate_samples)}
    scored = sorted(
        ((model.combination_probability(candidate), candidate) for candidate in candidates),
        reverse=True,
    )
    selected_sets = [set(game) for game in selected_games]
    for maximum_overlap in (2, 3, 4, 6):
        for probability, candidate in scored:
            if candidate in selected_games:
                continue
            if all(len(set(candidate) & game) <= maximum_overlap for game in selected_sets):
                return candidate, probability
    raise RuntimeError("Unable to generate a distinct spectrum game")


def run_performance_spectrum(
    records: Iterable[dict[str, Any]],
    development_rounds: Iterable[int],
    holdout_rounds: Iterable[int],
    prior_grid: Sequence[float] = (45.0, 90.0, 135.0, 180.0, 360.0),
    seed: int = 20260822,
    candidate_samples: int = 2000,
) -> dict[str, Any]:
    """Build five exploratory games spanning rejected holdout performance."""
    priors = tuple(float(value) for value in prior_grid)
    if len(priors) != 5 or len(set(priors)) != 5 or any(value <= 0 for value in priors):
        raise ValueError("Performance spectrum requires five unique positive prior strengths")
    if candidate_samples < 10:
        raise ValueError("candidate_samples must be at least 10")

    observations = _ordered_records(records)
    by_round = {int(record["round"]): record for record in observations}
    development_ids = {int(value) for value in development_rounds}
    holdout_ids = {int(value) for value in holdout_rounds}
    if not development_ids or not holdout_ids or development_ids & holdout_ids:
        raise ValueError("Development and holdout rounds must be non-empty and disjoint")
    missing = (development_ids | holdout_ids) - by_round.keys()
    if missing:
        raise ValueError(f"Missing verified ordered observations for rounds: {sorted(missing)}")

    development_orders = [
        by_round[round_number]["ordered_numbers"] for round_number in sorted(development_ids)
    ]
    holdout_orders = [
        by_round[round_number]["ordered_numbers"] for round_number in sorted(holdout_ids)
    ]
    uniform_log = math.log(UNIFORM_COMBINATION_PROBABILITY)
    evaluated = []
    for prior in priors:
        model = ExtractionOrderConditionalModel(prior).fit(development_orders)
        improvements = [model.log_probability(order) - uniform_log for order in holdout_orders]
        evaluated.append(
            {
                "prior_strength": prior,
                "holdout_mean_log_loss_improvement_vs_uniform": statistics.fmean(improvements),
            }
        )

    evaluated.sort(
        key=lambda item: (
            item["holdout_mean_log_loss_improvement_vs_uniform"],
            item["prior_strength"],
        )
    )
    category_labels = (
        ("worst", 1, "최악 1"),
        ("worst", 2, "최악 2"),
        ("median", 1, "중간값"),
        ("best", 2, "최고 2"),
        ("best", 1, "최고 1"),
    )
    all_orders = [record["ordered_numbers"] for record in observations]
    selected_games: list[tuple[int, ...]] = []
    variants = []
    for performance_rank, (evaluation, category) in enumerate(
        zip(evaluated, category_labels), start=1
    ):
        model = ExtractionOrderConditionalModel(evaluation["prior_strength"]).fit(all_orders)
        numbers, probability = _select_spectrum_game(
            model,
            seed=seed + performance_rank * 1009,
            selected_games=selected_games,
            candidate_samples=candidate_samples,
        )
        selected_games.append(numbers)
        category_key, category_rank, category_label = category
        variants.append(
            {
                "performance_rank_low_to_high": performance_rank,
                "category": category_key,
                "category_rank": category_rank,
                "category_label": category_label,
                **evaluation,
                "numbers": list(numbers),
                "combination_probability": probability,
                "relative_to_uniform": probability / UNIFORM_COMBINATION_PROBABILITY,
            }
        )

    return {
        "generated_at_utc": utc_now(),
        "model_id": ExtractionOrderConditionalModel.model_id,
        "decision_context": "rejected",
        "accepted_for_live_predictions": False,
        "experimental_only": True,
        "selection_rule": "two worst, one median, and two best frozen-holdout variants",
        "development_count": len(development_ids),
        "holdout_count": len(holdout_ids),
        "verified_ordered_records_used_for_generation": len(observations),
        "target_round": max(by_round) + 1,
        "seed": seed,
        "candidate_samples_per_variant": candidate_samples,
        "variants": variants,
    }


def resolve_frozen_cohorts(
    all_rounds: set[int],
    holdout_rounds: set[int],
    prior_holdout_rounds: set[int],
    expected_development: int,
) -> set[int]:
    overlap = holdout_rounds & prior_holdout_rounds
    if overlap:
        raise ValueError("Current and prior holdout batches must be disjoint")
    development_rounds = all_rounds - holdout_rounds - prior_holdout_rounds
    if len(development_rounds) != expected_development:
        raise ValueError(
            f"Frozen development cohort mismatch: expected {expected_development}, "
            f"found {len(development_rounds)}"
        )
    return development_rounds


def batch_observation_rounds(batch: dict) -> set[int]:
    rows = batch.get("reviewed_rows")
    if isinstance(rows, list):
        return {int(row["round"]) for row in rows}
    return {int(round_number) for round_number in batch["rounds"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context-dir", type=Path, default=DEFAULT_CONTEXT_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--minimum-sample", type=int, default=100)
    parser.add_argument("--validation-size", type=int, default=20)
    parser.add_argument("--test-size", type=int, default=20)
    parser.add_argument("--frozen-development-report", type=Path)
    parser.add_argument("--holdout-batch", type=Path, action="append", default=[])
    parser.add_argument("--prior-holdout-batch", type=Path, action="append", default=[])
    parser.add_argument("--spectrum", action="store_true")
    parser.add_argument(
        "--spectrum-priors",
        type=float,
        nargs=5,
        default=(45.0, 90.0, 135.0, 180.0, 360.0),
    )
    parser.add_argument("--spectrum-seed", type=int, default=20260822)
    parser.add_argument("--spectrum-candidates", type=int, default=2000)
    args = parser.parse_args()

    records = read_jsonl(args.context_dir / "observations.jsonl")
    gate = audit_records(records, args.minimum_sample)
    require_model_gate(gate, "ordered_sequence")
    if args.frozen_development_report:
        if not args.holdout_batch:
            parser.error("--holdout-batch is required with --frozen-development-report")
        development_report = json.loads(args.frozen_development_report.read_text(encoding="utf-8"))
        holdout_rounds = set()
        for batch_path in args.holdout_batch:
            batch = json.loads(batch_path.read_text(encoding="utf-8"))
            holdout_rounds.update(batch_observation_rounds(batch))
        prior_holdout_rounds = set()
        for batch_path in args.prior_holdout_batch:
            batch = json.loads(batch_path.read_text(encoding="utf-8"))
            prior_holdout_rounds.update(batch_observation_rounds(batch))
        all_rounds = {int(record["round"]) for record in _ordered_records(records)}
        expected_development = int(development_report["verified_ordered_records"])
        development_rounds = resolve_frozen_cohorts(
            all_rounds,
            holdout_rounds,
            prior_holdout_rounds,
            expected_development,
        )
        if args.spectrum:
            report = run_performance_spectrum(
                records,
                development_rounds=development_rounds,
                holdout_rounds=holdout_rounds,
                prior_grid=args.spectrum_priors,
                seed=args.spectrum_seed,
                candidate_samples=args.spectrum_candidates,
            )
            if args.output == DEFAULT_OUTPUT:
                args.output = DEFAULT_SPECTRUM_OUTPUT
        else:
            report = run_frozen_acquisition_holdout_test(
                records,
                development_rounds=development_rounds,
                holdout_rounds=holdout_rounds,
                selected_prior_strength=float(development_report["selected_prior_strength"]),
                minimum_holdout=args.minimum_sample,
            )
        report["frozen_development_report"] = str(args.frozen_development_report)
        report["holdout_batches"] = [str(path) for path in args.holdout_batch]
        report["prior_holdout_batches"] = [str(path) for path in args.prior_holdout_batch]
    else:
        if args.spectrum:
            parser.error("--spectrum requires --frozen-development-report")
        report = run_holdout_test(
            records,
            validation_size=args.validation_size,
            test_size=args.test_size,
            minimum_sample=args.minimum_sample,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
