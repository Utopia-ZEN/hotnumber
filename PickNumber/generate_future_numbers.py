import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PickNumber.future_engine import generate_future_numbers
from PickNumber.picknumber_analysis import END_ROUND, OUT_DIR, SEED, START_ROUND, picks_to_json_ready


def main():
    parser = argparse.ArgumentParser(description="Generate lottery games with the future inference engine.")
    parser.add_argument("n", nargs="?", type=int, default=6, help="number of games to generate")
    parser.add_argument("--start-round", type=int, default=START_ROUND)
    parser.add_argument("--end-round", type=int, default=END_ROUND)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--candidate-budget", type=int, default=90000)
    parser.add_argument("--output", type=Path, default=OUT_DIR / "future_numbers.json")
    args = parser.parse_args()

    _, _, picks = generate_future_numbers(
        game_count=args.n,
        start_round=args.start_round,
        end_round=args.end_round,
        seed=args.seed,
        candidate_budget=args.candidate_budget,
    )
    payload = picks_to_json_ready(picks)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    for item in payload:
        numbers = " ".join(f"{n:02d}" for n in item["numbers"])
        print(f"{item['rank']}. {numbers} | {item['strategy']} | score={item['final_score']}")
    print(f"saved: {args.output}")


if __name__ == "__main__":
    main()
