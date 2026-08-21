"""CLI and immutable experiment ledger for the evidence-first lotto model."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PickNumber.order_model import (  # noqa: E402
    COMBINATION_COUNT,
    UNIFORM_COMBINATION_PROBABILITY,
    BayesianOrderModel,
    Draw,
    PortfolioGame,
    best_match,
    draw_data_digest,
    generate_uniform_portfolio,
    load_draws,
)


DEFAULT_DATA_DIR = ROOT / "lotto_data"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "order_experiment"
DEFAULT_LEDGER = DEFAULT_OUTPUT_DIR / "prediction_ledger.jsonl"
STAR_BUCKET_SIZE = 500


def owner_pick_path(target_round: int, suffix: str = "star.lotto") -> Path:
    start = ((int(target_round) - 1) // STAR_BUCKET_SIZE) * STAR_BUCKET_SIZE + 1
    return DEFAULT_DATA_DIR / "star" / f"{start}-{start + STAR_BUCKET_SIZE - 1}" / f"{target_round}_{suffix}"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _record_hash(record_without_hash: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(record_without_hash).encode("utf-8")).hexdigest()


class PredictionLedger:
    """Append-only SHA-256 hash chain for predictions and evaluations."""

    def __init__(self, path: Path):
        self.path = path

    def records(self, verify: bool = True) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        previous_hash = None
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            record = json.loads(line)
            if verify:
                stored_hash = record.get("record_hash")
                unsigned = {key: value for key, value in record.items() if key != "record_hash"}
                if unsigned.get("previous_hash") != previous_hash:
                    raise ValueError(f"Ledger chain mismatch at line {line_number}")
                if stored_hash != _record_hash(unsigned):
                    raise ValueError(f"Ledger hash mismatch at line {line_number}")
                previous_hash = stored_hash
            records.append(record)
        return records

    def append(self, payload: dict[str, Any]) -> dict[str, Any]:
        records = self.records(verify=True)
        unsigned = dict(payload)
        unsigned["previous_hash"] = records[-1]["record_hash"] if records else None
        record = {**unsigned, "record_hash": _record_hash(unsigned)}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(_canonical_json(record) + "\n")
        return record

    def append_prediction(
        self,
        target_round: int,
        training_draws: Sequence[Draw],
        model: BayesianOrderModel,
        games: Sequence[PortfolioGame],
        seed: int,
    ) -> dict[str, Any]:
        for record in self.records():
            if (
                record.get("event") == "prediction"
                and record.get("target_round") == target_round
                and record.get("model", {}).get("model_id") == model.model_id
            ):
                raise ValueError(f"Prediction for round {target_round} and {model.model_id} is already sealed")
        if not training_draws or training_draws[-1].round >= target_round:
            raise ValueError("Training data must end before the target round")
        return self.append(
            {
                "event": "prediction",
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "target_round": target_round,
                "training_start_round": training_draws[0].round,
                "training_end_round": training_draws[-1].round,
                "training_draw_count": len(training_draws),
                "training_data_sha256": draw_data_digest(training_draws),
                "model": model.model_config(),
                "generation_seed": seed,
                "games": [
                    {
                        "numbers": list(game.numbers),
                        "probability": game.probability,
                        "relative_to_uniform": game.relative_to_uniform,
                    }
                    for game in games
                ],
            }
        )

    def append_evaluation(self, draw: Draw) -> dict[str, Any]:
        records = self.records()
        owner_pick_set = next(
            (
                record
                for record in reversed(records)
                if record.get("event") == "owner_pick_set" and record.get("target_round") == draw.round
            ),
            None,
        )
        if owner_pick_set is None:
            raise ValueError(f"No sealed owner pick set exists for round {draw.round}")
        if any(record.get("event") == "evaluation" and record.get("target_round") == draw.round for record in records):
            raise ValueError(f"Round {draw.round} is already evaluated")
        games = owner_pick_set["games"]
        game_results = []
        for game in games:
            matched = sorted(set(game["numbers"]) & set(draw.numbers))
            bonus_matched = draw.bonus in game["numbers"] if draw.bonus is not None else False
            game_results.append(
                {
                    "rank": game["rank"],
                    "group": game["group"],
                    "group_rank": game["group_rank"],
                    "numbers": game["numbers"],
                    "match_count": len(matched),
                    "matched_numbers": matched,
                    "bonus_matched": bonus_matched,
                }
            )
        group_summary = {}
        for group in ("order_model", "uniform_random"):
            group_results = [result for result in game_results if result["group"] == group]
            group_summary[group] = {
                "best_match": max((result["match_count"] for result in group_results), default=0),
                "match_distribution": dict(sorted(Counter(result["match_count"] for result in group_results).items())),
            }
        return self.append(
            {
                "event": "evaluation",
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "target_round": draw.round,
                "owner_pick_record_hash": owner_pick_set["record_hash"],
                "actual_numbers": list(draw.numbers),
                "bonus": draw.bonus,
                "games": game_results,
                "group_summary": group_summary,
                "best_match": max((result["match_count"] for result in game_results), default=0),
            }
        )

    def append_owner_pick_set(
        self,
        target_round: int,
        random_seed: int,
        random_games: Sequence[PortfolioGame],
    ) -> dict[str, Any]:
        records = self.records()
        if any(
            record.get("event") == "owner_pick_set" and record.get("target_round") == target_round
            for record in records
        ):
            raise ValueError(f"Owner pick set for round {target_round} is already sealed")
        prediction = next(
            (
                record
                for record in reversed(records)
                if record.get("event") == "prediction" and record.get("target_round") == target_round
            ),
            None,
        )
        if prediction is None:
            raise ValueError(f"No sealed model prediction exists for round {target_round}")
        if len(prediction["games"]) != 5 or len(random_games) != 5:
            raise ValueError("Owner picks require exactly five model games and five random games")

        games = []
        for group, source_games in (
            ("order_model", prediction["games"]),
            (
                "uniform_random",
                [
                    {
                        "numbers": list(game.numbers),
                        "probability": game.probability,
                        "relative_to_uniform": game.relative_to_uniform,
                    }
                    for game in random_games
                ],
            ),
        ):
            for group_rank, game in enumerate(source_games, 1):
                numbers = list(game["numbers"])
                odd = sum(number % 2 for number in numbers)
                high = sum(number >= 23 for number in numbers)
                games.append(
                    {
                        "rank": len(games) + 1,
                        "group": group,
                        "group_label": "질서 모델" if group == "order_model" else "무작위 기준",
                        "group_rank": group_rank,
                        "numbers": numbers,
                        "strategy": BayesianOrderModel.model_id if group == "order_model" else "uniform-random-v1",
                        "sum": sum(numbers),
                        "odd_even": f"{odd}:{6 - odd}",
                        "high_low": f"{high}:{6 - high}",
                        "probability": game["probability"],
                        "relative_to_uniform": game["relative_to_uniform"],
                        "final_score": game["relative_to_uniform"],
                    }
                )
        return self.append(
            {
                "event": "owner_pick_set",
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "target_round": target_round,
                "prediction_record_hash": prediction["record_hash"],
                "random_seed": random_seed,
                "games": games,
            }
        )


def run_walk_forward(
    draws: Sequence[Draw],
    min_train_rounds: int = 200,
    prior_strength: float = 180.0,
    games_per_round: int = 5,
    seed: int = 20260605,
) -> dict[str, Any]:
    if len(draws) <= min_train_rounds:
        raise ValueError("Not enough draws for the requested walk-forward test")
    rounds = [draw.round for draw in draws]
    expected_rounds = list(range(rounds[0], rounds[-1] + 1))
    if rounds != expected_rounds:
        missing = sorted(set(expected_rounds) - set(rounds))
        raise ValueError(f"Draw history must be contiguous; missing rounds: {missing[:10]}")

    model_log_loss = 0.0
    uniform_log_loss = 0.0
    log_loss_improvements: list[float] = []
    model_matches = Counter()
    uniform_matches = Counter()
    evaluated = 0

    for index in range(min_train_rounds, len(draws)):
        training = draws[:index]
        target = draws[index]
        model = BayesianOrderModel(prior_strength=prior_strength).fit(training)
        target_model_loss = -model.log_probability(target.numbers)
        target_uniform_loss = -math.log(UNIFORM_COMBINATION_PROBABILITY)
        model_log_loss += target_model_loss
        uniform_log_loss += target_uniform_loss
        log_loss_improvements.append(target_uniform_loss - target_model_loss)

        model_games = model.generate_portfolio(
            game_count=games_per_round,
            seed=seed + target.round * 97,
            top_pool_size=14,
            random_candidates=250,
        )
        uniform_games = generate_uniform_portfolio(
            game_count=games_per_round,
            seed=seed + target.round * 97,
        )
        model_matches[best_match(model_games, target.numbers)] += 1
        uniform_matches[best_match(uniform_games, target.numbers)] += 1
        evaluated += 1

    average_model_loss = model_log_loss / evaluated
    average_uniform_loss = uniform_log_loss / evaluated
    improvement = average_uniform_loss - average_model_loss
    improvement_standard_error = (
        statistics.stdev(log_loss_improvements) / math.sqrt(evaluated) if evaluated > 1 else 0.0
    )
    return {
        "protocol": "strict_walk_forward",
        "first_evaluated_round": draws[min_train_rounds].round,
        "last_evaluated_round": draws[-1].round,
        "evaluated_rounds": evaluated,
        "games_per_round": games_per_round,
        "model": {"model_id": BayesianOrderModel.model_id, "prior_strength": prior_strength},
        "average_log_loss": average_model_loss,
        "uniform_average_log_loss": average_uniform_loss,
        "log_loss_improvement": improvement,
        "log_loss_improvement_standard_error": improvement_standard_error,
        "log_loss_improvement_95pct_interval": [
            improvement - 1.96 * improvement_standard_error,
            improvement + 1.96 * improvement_standard_error,
        ],
        "model_better_than_uniform": average_model_loss < average_uniform_loss,
        "model_best_match_distribution": dict(sorted(model_matches.items())),
        "uniform_best_match_distribution": dict(sorted(uniform_matches.items())),
        "data_sha256": draw_data_digest(draws),
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_owner_pick_files(record: dict[str, Any]) -> tuple[Path, Path]:
    target_round = int(record["target_round"])
    json_path = owner_pick_path(target_round)
    comment_path = owner_pick_path(target_round, "comment.txt")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(record["games"], ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# Owner Picks round {target_round}",
        "",
        "- Games: 10 (order model 5 + sealed uniform random 5)",
        f"- Owner-pick ledger hash: {record['record_hash']}",
        f"- Prediction ledger hash: {record['prediction_record_hash']}",
        f"- Uniform random seed: {record['random_seed']}",
        "- Evaluation: compare both groups after the draw; no game may be replaced.",
        "",
        "## Picks",
    ]
    for game in record["games"]:
        numbers = " ".join(f"{number:02d}" for number in game["numbers"])
        lines.append(
            f"{game['rank']}. [{game['group_label']} {game['group_rank']}] {numbers} | "
            f"relative_to_uniform={game['relative_to_uniform']:.6f}"
        )
    comment_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, comment_path


def _find_record(records: Sequence[dict[str, Any]], event: str, target_round: int) -> dict[str, Any] | None:
    return next(
        (
            record
            for record in reversed(records)
            if record.get("event") == event and record.get("target_round") == target_round
        ),
        None,
    )


def command_predict(args: argparse.Namespace) -> None:
    draws = load_draws(args.data_dir, args.start_round, args.end_round)
    if not draws:
        raise RuntimeError("No draw data found")
    target_round = args.target_round or draws[-1].round + 1
    training = [draw for draw in draws if draw.round < target_round]
    model = BayesianOrderModel(prior_strength=args.prior_strength).fit(training)
    games = model.generate_portfolio(game_count=args.games, seed=args.seed)
    record = PredictionLedger(args.ledger).append_prediction(target_round, training, model, games, args.seed)
    _write_json(args.output_dir / f"round_{target_round}_prediction.json", record)
    print(f"sealed prediction: round {target_round}")
    for rank, game in enumerate(games, 1):
        numbers = " ".join(f"{number:02d}" for number in game.numbers)
        print(f"{rank}. {numbers} | relative-to-uniform={game.relative_to_uniform:.6f}")
    print(f"ledger: {args.ledger}")


def command_backtest(args: argparse.Namespace) -> None:
    draws = load_draws(args.data_dir, args.start_round, args.end_round)
    report = run_walk_forward(
        draws,
        min_train_rounds=args.min_train_rounds,
        prior_strength=args.prior_strength,
        games_per_round=args.games,
        seed=args.seed,
    )
    output = args.output_dir / "walk_forward_report.json"
    _write_json(output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"saved: {output}")


def command_settle(args: argparse.Namespace) -> None:
    draws = load_draws(args.data_dir, args.round, args.round)
    if not draws:
        raise RuntimeError(f"Draw data for round {args.round} is not available")
    record = PredictionLedger(args.ledger).append_evaluation(draws[0])
    print(json.dumps(record, ensure_ascii=False, indent=2))


def command_verify(args: argparse.Namespace) -> None:
    records = PredictionLedger(args.ledger).records(verify=True)
    print(f"ledger valid: {len(records)} records")


def command_owner_cycle(args: argparse.Namespace) -> None:
    draws = load_draws(args.data_dir, args.start_round, args.end_round)
    if not draws:
        raise RuntimeError("No draw data found")
    latest_draw = draws[-1]
    ledger = PredictionLedger(args.ledger)
    records = ledger.records()

    if _find_record(records, "owner_pick_set", latest_draw.round) and not _find_record(
        records, "evaluation", latest_draw.round
    ):
        ledger.append_evaluation(latest_draw)
        records = ledger.records()
        print(f"settled owner picks: round {latest_draw.round}")

    target_round = latest_draw.round + 1
    prediction = _find_record(records, "prediction", target_round)
    if prediction is None:
        model = BayesianOrderModel(prior_strength=args.prior_strength).fit(draws)
        games = model.generate_portfolio(game_count=5, seed=args.seed)
        prediction = ledger.append_prediction(target_round, draws, model, games, args.seed)
        records = ledger.records()
        print(f"sealed model prediction: round {target_round}")

    owner_set = _find_record(records, "owner_pick_set", target_round)
    if owner_set is None:
        random_seed = args.random_seed
        if random_seed is None:
            random_seed = args.seed ^ (target_round * 1_000_003)
        random_games = generate_uniform_portfolio(game_count=5, seed=random_seed)
        owner_set = ledger.append_owner_pick_set(target_round, random_seed, random_games)
        print(f"sealed random baseline: round {target_round}")

    json_path, comment_path = write_owner_pick_files(owner_set)
    print(f"owner picks: {json_path}")
    print(f"comment: {comment_path}")
    for game in owner_set["games"]:
        numbers = " ".join(f"{number:02d}" for number in game["numbers"])
        print(f"{game['rank']:02d}. {game['group_label']} {game['group_rank']} | {numbers}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run evidence-first Lotto 6/45 experiments")
    commands = parser.add_subparsers(dest="command", required=True)

    def add_common_arguments(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
        command_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
        command_parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
        command_parser.add_argument("--start-round", type=int, default=1)
        command_parser.add_argument("--end-round", type=int)
        command_parser.add_argument("--prior-strength", type=float, default=180.0)
        command_parser.add_argument("--seed", type=int, default=20260605)

    predict = commands.add_parser("predict", help="seal a future prediction")
    add_common_arguments(predict)
    predict.add_argument("--target-round", type=int)
    predict.add_argument("--games", type=int, default=5)
    predict.set_defaults(handler=command_predict)

    backtest = commands.add_parser("backtest", help="run a strict walk-forward comparison")
    add_common_arguments(backtest)
    backtest.add_argument("--min-train-rounds", type=int, default=200)
    backtest.add_argument("--games", type=int, default=5)
    backtest.set_defaults(handler=command_backtest)

    settle = commands.add_parser("settle", help="append an evaluation for a sealed prediction")
    add_common_arguments(settle)
    settle.add_argument("--round", type=int, required=True)
    settle.set_defaults(handler=command_settle)

    verify = commands.add_parser("verify-ledger", help="verify the complete prediction hash chain")
    add_common_arguments(verify)
    verify.set_defaults(handler=command_verify)

    owner_cycle = commands.add_parser(
        "owner-cycle",
        help="settle the latest owner picks and seal the next 5+5 owner set",
    )
    add_common_arguments(owner_cycle)
    owner_cycle.add_argument("--random-seed", type=int)
    owner_cycle.set_defaults(handler=command_owner_cycle)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
