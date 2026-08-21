import argparse
import json
import random
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PickNumber.picknumber_analysis import START_ROUND, build_stats, load_draws, score_candidate, select_diverse


OUT_DIR = ROOT / "lotto_data" / "star"


def build_weighted_pool(stats, end_round, start_round):
    all_nums = list(range(1, 46))
    freq = stats["freq"]
    recent = stats["recent_30_freq"]
    last_seen = stats["last_seen"]
    return [
        (
            n,
            1.0
            + freq.get(n, 0) * 0.08
            + recent.get(n, 0) * 0.9
            + max(0, end_round - last_seen.get(n, start_round - 1)) * 0.12
        )
        for n in all_nums
    ]


def weighted_unique_sample(rng, weighted_pool, k=6):
    available = list(weighted_pool)
    selected = []
    while len(selected) < k and available:
        nums = [item[0] for item in available]
        weights = [max(0.01, item[1]) for item in available]
        pick = rng.choices(nums, weights=weights, k=1)[0]
        selected.append(pick)
        available = [item for item in available if item[0] != pick]
    return sorted(selected)


def generate_probe_games(seed, target_round, stats, games, samples, start_round):
    rng = random.Random(seed * 1_000_003 + target_round * 97)
    weighted_pool = build_weighted_pool(stats, target_round - 1, start_round)
    top_freq = [n for n, _ in stats["freq"].most_common(18)]
    overdue = sorted(
        range(1, 46),
        key=lambda n: (target_round - 1) - stats["last_seen"].get(n, start_round - 1),
        reverse=True,
    )[:18]
    pair_numbers = [n for pair, _ in stats["pair"].most_common(24) for n in pair]
    pools = [
        weighted_pool,
        [(n, 1.0 + stats["recent_30_freq"].get(n, 0)) for n in sorted(set(top_freq + overdue))],
        [(n, 1.0 + stats["freq"].get(n, 0) * 0.05) for n in sorted(set(pair_numbers + overdue))],
    ]

    candidates = []
    seen = set()
    per_pool = max(1, samples // len(pools))
    for pool in pools:
        clean_pool = [(n, w) for n, w in pool if 1 <= n <= 45]
        if len(clean_pool) < 6:
            continue
        for _ in range(per_pool):
            nums = tuple(weighted_unique_sample(rng, clean_pool, 6))
            if nums in seen:
                continue
            seen.add(nums)
            scored = score_candidate(
                nums,
                stats,
                target_round - start_round,
                start_round,
                target_round - 1,
            )
            if scored:
                candidates.append(scored)

    picks = select_diverse(candidates, limit=games)
    return picks


def prize_tier(match_count, bonus_matched=False):
    if match_count == 6:
        return "1st"
    if match_count == 5 and bonus_matched:
        return "2nd"
    if match_count == 5:
        return "3rd"
    if match_count == 4:
        return "4th"
    if match_count == 3:
        return "5th"
    return "none"


def score_summary(summary):
    return round(
        summary["rounds_with_best_6"] * 10000000
        + summary["rounds_with_best_5plus"] * 100000
        + summary["rounds_with_best_4plus"] * 1000
        + summary["rounds_with_best_3plus"] * 25
        + summary["average_best_match_per_round"] * 10
        + summary["average_match_per_game"],
        4,
    )


def evaluate_seed(seed, draws, stats_by_target, start_round, end_round, games, samples):
    draw_by_round = {draw["round"]: draw for draw in draws}
    match_distribution = Counter()
    best_match_distribution = Counter()
    prize_distribution = Counter()
    checked_rounds = 0
    failed_rounds = 0

    for target_round in range(start_round + 1, end_round + 1):
        actual = draw_by_round.get(target_round)
        stats = stats_by_target.get(target_round)
        if not actual or not stats:
            failed_rounds += 1
            continue

        picks = generate_probe_games(seed, target_round, stats, games, samples, start_round)
        if len(picks) < games:
            failed_rounds += 1
            continue

        actual_numbers = set(actual["numbers"])
        actual_bonus = actual.get("bonus")
        best_match = 0
        best_bonus = False
        for item in picks:
            predicted = set(item["numbers"])
            match_count = len(predicted & actual_numbers)
            bonus_matched = actual_bonus in predicted if actual_bonus else False
            match_distribution[match_count] += 1
            prize_distribution[prize_tier(match_count, bonus_matched)] += 1
            if (match_count, bonus_matched) > (best_match, best_bonus):
                best_match = match_count
                best_bonus = bonus_matched
        best_match_distribution[best_match] += 1
        checked_rounds += 1

    total_games = checked_rounds * games
    summary = {
        "seed": seed,
        "checked_rounds": checked_rounds,
        "failed_rounds": failed_rounds,
        "games_per_round": games,
        "total_games": total_games,
        "average_match_per_game": round(
            sum(k * v for k, v in match_distribution.items()) / total_games,
            4,
        )
        if total_games
        else 0,
        "average_best_match_per_round": round(
            sum(k * v for k, v in best_match_distribution.items()) / checked_rounds,
            4,
        )
        if checked_rounds
        else 0,
        "match_distribution": {str(k): match_distribution.get(k, 0) for k in range(7)},
        "best_match_distribution": {str(k): best_match_distribution.get(k, 0) for k in range(7)},
        "prize_distribution": dict(sorted(prize_distribution.items())),
        "rounds_with_best_3plus": sum(v for k, v in best_match_distribution.items() if k >= 3),
        "rounds_with_best_4plus": sum(v for k, v in best_match_distribution.items() if k >= 4),
        "rounds_with_best_5plus": sum(v for k, v in best_match_distribution.items() if k >= 5),
        "rounds_with_best_6": best_match_distribution.get(6, 0),
    }
    summary["score"] = score_summary(summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description="Fast full-history seed search for StarNumber probes.")
    parser.add_argument("--seed-start", type=int, default=0)
    parser.add_argument("--seed-end", type=int, default=999)
    parser.add_argument("--start-round", type=int, default=START_ROUND)
    parser.add_argument("--end-round", type=int)
    parser.add_argument("--games", type=int, default=5)
    parser.add_argument("--samples", type=int, default=90)
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--output", type=Path, default=OUT_DIR / "seed_search_summary.json")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    draws = load_draws(args.start_round, args.end_round or 9999)
    if not draws:
        raise RuntimeError("No lotto draws loaded")
    end_round = args.end_round or draws[-1]["round"]
    draws = [draw for draw in draws if args.start_round <= draw["round"] <= end_round]
    if len(draws) < 2:
        raise RuntimeError("Need at least two rounds for seed search")

    stats_by_target = {}
    history = []
    for draw in draws:
        if draw["round"] > args.start_round:
            stats_by_target[draw["round"]] = build_stats(history)
        history.append(draw)

    results = []
    for seed in range(args.seed_start, args.seed_end + 1):
        result = evaluate_seed(seed, draws, stats_by_target, args.start_round, end_round, args.games, args.samples)
        results.append(result)
        if not args.quiet:
            print(
                f"seed={seed} score={result['score']} "
                f"avg_best={result['average_best_match_per_round']} "
                f"3+={result['rounds_with_best_3plus']} "
                f"4+={result['rounds_with_best_4plus']} "
                f"5+={result['rounds_with_best_5plus']} "
                f"6={result['rounds_with_best_6']}"
            )

    results.sort(
        key=lambda item: (
            item["score"],
            item["rounds_with_best_6"],
            item["rounds_with_best_5plus"],
            item["rounds_with_best_4plus"],
            item["rounds_with_best_3plus"],
            item["average_best_match_per_round"],
            item["average_match_per_game"],
        ),
        reverse=True,
    )
    report = {
        "summary": {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "mode": "fast_seed_probe",
            "seed_start": args.seed_start,
            "seed_end": args.seed_end,
            "seed_count": args.seed_end - args.seed_start + 1,
            "best_seed": results[0]["seed"],
            "best_score": results[0]["score"],
            "start_round": args.start_round + 1,
            "end_round": end_round,
            "games_per_round": args.games,
            "samples_per_round": args.samples,
            "score_rule": "best_6*10000000 + best_5plus*100000 + best_4plus*1000 + best_3plus*25 + avg_best*10 + avg_game",
        },
        "top": results[: args.top],
        "seeds": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {args.output}")
    print(
        f"best: seed={results[0]['seed']} score={results[0]['score']} "
        f"avg_best={results[0]['average_best_match_per_round']} "
        f"3+={results[0]['rounds_with_best_3plus']} "
        f"4+={results[0]['rounds_with_best_4plus']} "
        f"5+={results[0]['rounds_with_best_5plus']} "
        f"6={results[0]['rounds_with_best_6']}"
    )


if __name__ == "__main__":
    main()
