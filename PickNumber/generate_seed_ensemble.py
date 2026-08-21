import argparse
import copy
import itertools
import json
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from StarNumber import StarNumberGenerator, get_star_file_path


DEFAULT_CHECKPOINT = ROOT / "lotto_data" / "star" / "seed_search_continuous.json"


def result_key(item):
    return (
        item.get("rounds_with_best_6", 0),
        item.get("rounds_with_best_5plus", 0),
        item.get("rounds_with_best_4plus", 0),
        item.get("rounds_with_best_3plus", 0),
        item.get("average_best_match_per_round", 0),
        item.get("average_match_per_game", 0),
    )


def select_seed_specs(checkpoint, hit_games):
    top = checkpoint.get("top") or []
    if not top:
        raise RuntimeError("The checkpoint does not contain a current best seed")

    best = top[0]
    best_seed = int(best["seed"])
    exact6_hits = sorted(checkpoint.get("exact6_hits") or [], key=result_key, reverse=True)
    selected_hits = []
    seen = {best_seed}
    for item in exact6_hits:
        seed = int(item["seed"])
        if seed in seen:
            continue
        seen.add(seed)
        selected_hits.append(item)
        if len(selected_hits) == hit_games:
            break

    if len(selected_hits) < hit_games:
        raise RuntimeError(
            f"Need {hit_games} exact-six seeds excluding best seed, found {len(selected_hits)}"
        )

    return [("best", best), *[("exact6", item) for item in selected_hits]]


def choose_unique_game(generator, selected_games, used_numbers, used_pairs, engine):
    candidates, _ = generator.generate_games(12, engine=engine, write_output=False)
    ranked = []
    for candidate in candidates:
        numbers = tuple(candidate["numbers"])
        if numbers in used_numbers:
            continue
        number_set = set(numbers)
        max_overlap = max(
            (len(number_set & set(chosen["numbers"])) for chosen in selected_games),
            default=0,
        )
        pair_load = sum(used_pairs[pair] for pair in itertools.combinations(numbers, 2))
        ranked.append((max_overlap, pair_load, -candidate["final_score"], candidate))
    if ranked:
        max_overlap, pair_load, _, candidate = min(ranked)
        numbers = tuple(candidate["numbers"])
        used_numbers.add(numbers)
        used_pairs.update(itertools.combinations(numbers, 2))
        game = copy.deepcopy(candidate)
        game["ensemble_max_overlap"] = max_overlap
        game["ensemble_pair_load"] = pair_load
        return game
    raise RuntimeError(f"Seed {generator.seed} did not produce a unique game")


def build_comment(target_round, start_round, end_round, engine, payload, checkpoint_path):
    exact6_games = sum(1 for item in payload if item["seed_role"] == "exact6")
    lines = [
        f"# StarNumber {target_round} round seed-ensemble picks",
        "",
        f"- Range: {start_round}-{end_round}",
        f"- Games: {len(payload)}",
        f"- Engine: {engine}",
        f"- Checkpoint: {checkpoint_path}",
        f"- Mix: 1 current best seed + {exact6_games} top exact-six seeds",
        "- Note: lottery draws are independent random events; this is data-based combination design, not a guarantee.",
        "",
        "## Picks",
    ]
    for item in payload:
        nums = " ".join(f"{number:02d}" for number in item["numbers"])
        lines.append(
            f"{item['rank']}. {nums} | role={item['seed_role']} | seed={item['source_seed']} | "
            f"historical_exact6={item['seed_metrics']['rounds_with_best_6']} | "
            f"strategy={item['strategy']} | score={item['final_score']}"
        )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(
        description="Generate one game from the current best seed and games from exact-six seeds."
    )
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--hit-games", type=int, default=4)
    parser.add_argument("--start-round", type=int, default=1)
    parser.add_argument("--end-round", type=int)
    parser.add_argument("--target-round", type=int)
    parser.add_argument("--engine", choices=["pick", "star", "hybrid", "future"], default="future")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    checkpoint = json.loads(args.checkpoint.read_text(encoding="utf-8"))
    seed_specs = select_seed_specs(checkpoint, args.hit_games)
    used_numbers = set()
    used_pairs = Counter()
    payload = []
    target_round = None
    end_round = None

    for rank, (role, seed_result) in enumerate(seed_specs, start=1):
        seed = int(seed_result["seed"])
        generator = StarNumberGenerator(
            start_round=args.start_round,
            end_round=args.end_round,
            seed=seed,
            engine=args.engine,
        )
        game = choose_unique_game(
            generator,
            payload,
            used_numbers,
            used_pairs,
            args.engine,
        )
        game["rank"] = rank
        game["seed_role"] = role
        game["source_seed"] = seed
        game["seed_metrics"] = {
            "rounds_with_best_6": seed_result.get("rounds_with_best_6", 0),
            "rounds_with_best_5plus": seed_result.get("rounds_with_best_5plus", 0),
            "rounds_with_best_4plus": seed_result.get("rounds_with_best_4plus", 0),
            "rounds_with_best_3plus": seed_result.get("rounds_with_best_3plus", 0),
            "checked_rounds": seed_result.get("checked_rounds", 0),
        }
        payload.append(game)
        end_round = generator.end_round
        target_round = args.target_round or end_round + 1

    if target_round <= end_round:
        raise ValueError("target-round must be greater than end-round")

    output_path = args.output or get_star_file_path(target_round, "star.lotto")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    comment_path = output_path.with_suffix(".txt") if args.output else get_star_file_path(target_round, "comment.txt")
    comment_path.write_text(
        build_comment(
            target_round,
            args.start_round,
            end_round,
            args.engine,
            payload,
            args.checkpoint,
        ),
        encoding="utf-8",
    )

    for item in payload:
        nums = " ".join(f"{number:02d}" for number in item["numbers"])
        print(f"{item['rank']}. {nums} | role={item['seed_role']} | seed={item['source_seed']}")
    print(f"saved: {output_path}")
    print(f"comment: {comment_path}")


if __name__ == "__main__":
    main()
