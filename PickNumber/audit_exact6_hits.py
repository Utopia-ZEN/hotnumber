import argparse
import csv
import json
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PickNumber.continuous_seed_search import build_stats_by_target
from PickNumber.picknumber_analysis import START_ROUND, load_draws
from PickNumber.search_seed import generate_probe_games


OUT_DIR = ROOT / "lotto_data" / "star"
WORKER_CONTEXT = {}


def init_worker(draws, stats_by_target, start_round, end_round, games, samples):
    WORKER_CONTEXT["draws"] = draws
    WORKER_CONTEXT["stats_by_target"] = stats_by_target
    WORKER_CONTEXT["start_round"] = start_round
    WORKER_CONTEXT["end_round"] = end_round
    WORKER_CONTEXT["games"] = games
    WORKER_CONTEXT["samples"] = samples


def audit_seed(seed_and_expected_rounds):
    seed, expected_rounds = seed_and_expected_rounds
    start_round = WORKER_CONTEXT["start_round"]
    games = WORKER_CONTEXT["games"]
    samples = WORKER_CONTEXT["samples"]
    draw_by_round = {draw["round"]: draw for draw in WORKER_CONTEXT["draws"]}
    matches = []

    for target_round in range(start_round + 1, WORKER_CONTEXT["end_round"] + 1):
        actual = draw_by_round.get(target_round)
        stats = WORKER_CONTEXT["stats_by_target"].get(target_round)
        if not actual or not stats:
            continue

        picks = generate_probe_games(
            seed,
            target_round,
            stats,
            games,
            samples,
            start_round,
        )
        actual_numbers = tuple(actual["numbers"])
        for game_number, item in enumerate(picks, start=1):
            predicted_numbers = tuple(item["numbers"])
            if predicted_numbers == actual_numbers:
                matches.append(
                    {
                        "seed": seed,
                        "round": target_round,
                        "winning_numbers": list(actual_numbers),
                        "predicted_numbers": list(predicted_numbers),
                        "game_number": game_number,
                        "bonus": actual.get("bonus"),
                    }
                )
        if len({item["round"] for item in matches}) >= expected_rounds:
            break

    return {"seed": seed, "matches": matches}


def write_csv(path, fieldnames, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(
        description="Reconstruct the round and number combination for each exact-6 seed hit."
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=OUT_DIR / "seed_search_continuous.json",
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--output-prefix", type=Path, default=OUT_DIR / "seed_search_exact6")
    args = parser.parse_args()

    checkpoint = json.loads(args.checkpoint.read_text(encoding="utf-8"))
    exact6_items = checkpoint.get("exact6_hits") or []
    seeds = sorted({int(item["seed"]) for item in exact6_items})
    items_by_seed = {
        int(item["seed"]): item
        for item in exact6_items
    }
    expected_round_counts = {
        int(item["seed"]): int(item.get("rounds_with_best_6", 0))
        for item in exact6_items
    }
    if not seeds:
        raise RuntimeError("The checkpoint contains no exact-6 seed hits")

    games = int(checkpoint.get("games_per_round", 5))
    samples = int(checkpoint.get("samples_per_round", 30))

    matches = []
    jobs_by_config = defaultdict(list)
    for seed in seeds:
        item = items_by_seed[seed]
        checked_rounds = int(item.get("checked_rounds", 0))
        failed_rounds = int(item.get("failed_rounds", 0))
        start_round = 1 if checked_rounds > 500 else START_ROUND
        end_round = start_round + checked_rounds + failed_rounds
        jobs_by_config[(start_round, end_round)].append(
            (seed, expected_round_counts[seed])
        )

    evaluation_configurations = []
    for (start_round, end_round), seed_jobs in sorted(jobs_by_config.items()):
        draws = load_draws(start_round, end_round)
        draws = [draw for draw in draws if start_round <= draw["round"] <= end_round]
        stats_by_target = build_stats_by_target(draws, start_round)
        evaluation_configurations.append(
            {
                "start_round": start_round,
                "end_round": end_round,
                "seed_count": len(seed_jobs),
            }
        )
        with ProcessPoolExecutor(
            max_workers=max(1, args.workers),
            initializer=init_worker,
            initargs=(draws, stats_by_target, start_round, end_round, games, samples),
        ) as executor:
            for result in executor.map(audit_seed, seed_jobs):
                matches.extend(result["matches"])

    matches.sort(key=lambda item: (item["round"], item["seed"], item["game_number"]))
    actual_round_counts = defaultdict(set)
    grouped = defaultdict(list)
    for item in matches:
        actual_round_counts[item["seed"]].add(item["round"])
        grouped[(item["round"], tuple(item["winning_numbers"]))].append(item)

    mismatches = []
    for seed in seeds:
        expected = expected_round_counts[seed]
        actual = len(actual_round_counts[seed])
        if expected != actual:
            mismatches.append({"seed": seed, "expected_rounds": expected, "actual_rounds": actual})

    by_round = []
    for (round_no, numbers), items in sorted(grouped.items()):
        hit_seeds = sorted({item["seed"] for item in items})
        by_round.append(
            {
                "round": round_no,
                "winning_numbers": list(numbers),
                "seed_count": len(hit_seeds),
                "seeds": hit_seeds,
            }
        )

    prefix = args.output_prefix
    prefix.parent.mkdir(parents=True, exist_ok=True)
    detail_csv = prefix.with_name(f"{prefix.name}_details.csv")
    round_csv = prefix.with_name(f"{prefix.name}_by_round.csv")
    report_json = prefix.with_name(f"{prefix.name}_report.json")

    detail_rows = [
        {
            "seed": item["seed"],
            "round": item["round"],
            "winning_numbers": " ".join(map(str, item["winning_numbers"])),
            "predicted_numbers": " ".join(map(str, item["predicted_numbers"])),
            "game_number": item["game_number"],
            "bonus": item["bonus"],
        }
        for item in matches
    ]
    round_rows = [
        {
            "round": item["round"],
            "winning_numbers": " ".join(map(str, item["winning_numbers"])),
            "seed_count": item["seed_count"],
            "seeds": " ".join(map(str, item["seeds"])),
        }
        for item in by_round
    ]
    write_csv(
        detail_csv,
        ["seed", "round", "winning_numbers", "predicted_numbers", "game_number", "bonus"],
        detail_rows,
    )
    write_csv(round_csv, ["round", "winning_numbers", "seed_count", "seeds"], round_rows)

    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "checkpoint": str(args.checkpoint.resolve()),
        "checkpoint_updated_at": checkpoint.get("updated_at"),
        "checkpoint_last_completed_seed": checkpoint.get("last_completed_seed"),
        "checkpoint_next_seed": checkpoint.get("next_seed"),
        "evaluation_configurations": evaluation_configurations,
        "games_per_round": games,
        "samples_per_round": samples,
        "audited_seed_count": len(seeds),
        "exact6_game_hit_count": len(matches),
        "unique_exact6_round_count": len(by_round),
        "validation_mismatches": mismatches,
        "by_round": by_round,
        "details": matches,
    }
    report_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "audited_seed_count": len(seeds),
                "exact6_game_hit_count": len(matches),
                "unique_exact6_round_count": len(by_round),
                "validation_mismatch_count": len(mismatches),
                "detail_csv": str(detail_csv.resolve()),
                "round_csv": str(round_csv.resolve()),
                "report_json": str(report_json.resolve()),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
