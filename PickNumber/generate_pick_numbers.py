import argparse
import json
from pathlib import Path

from picknumber_analysis import (
    END_ROUND,
    OUT_DIR,
    SEED,
    START_ROUND,
    generate_pick_numbers,
    picks_to_json_ready,
)


def main():
    parser = argparse.ArgumentParser(
        description="Generate 1..n lottery games with the PickNumber scoring engine."
    )
    parser.add_argument("n", type=int, help="number of games to generate")
    parser.add_argument(
        "--output",
        type=Path,
        default=OUT_DIR / "generated_pick_numbers.json",
        help="JSON output path",
    )
    parser.add_argument("--start-round", type=int, default=START_ROUND)
    parser.add_argument("--end-round", type=int, default=END_ROUND)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()

    _, _, picks = generate_pick_numbers(
        game_count=args.n,
        start_round=args.start_round,
        end_round=args.end_round,
        seed=args.seed,
    )
    payload = picks_to_json_ready(picks)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    for item in payload:
        numbers = " ".join(f"{n:02d}" for n in item["numbers"])
        print(f"{item['rank']}. {numbers} | score={item['final_score']}")
    print(f"saved: {args.output}")


if __name__ == "__main__":
    main()
