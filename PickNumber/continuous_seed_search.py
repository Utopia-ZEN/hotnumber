import argparse
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PickNumber.picknumber_analysis import START_ROUND, build_stats, load_draws
from PickNumber.search_seed import evaluate_seed


OUT_DIR = ROOT / "lotto_data" / "star"
COMBINED_RE = re.compile(r"seed_search_0_(\d+)_exact6\.json$")
WORKER_CONTEXT = {}


def sort_key(item):
    return (
        item.get("rounds_with_best_6", 0),
        item.get("rounds_with_best_5plus", 0),
        item.get("rounds_with_best_4plus", 0),
        item.get("rounds_with_best_3plus", 0),
        item.get("average_best_match_per_round", 0),
        item.get("average_match_per_game", 0),
    )


def init_worker(draws, stats_by_target, start_round, end_round, games, samples):
    WORKER_CONTEXT["draws"] = draws
    WORKER_CONTEXT["stats_by_target"] = stats_by_target
    WORKER_CONTEXT["start_round"] = start_round
    WORKER_CONTEXT["end_round"] = end_round
    WORKER_CONTEXT["games"] = games
    WORKER_CONTEXT["samples"] = samples


def evaluate_seed_worker(seed):
    return evaluate_seed(
        seed,
        WORKER_CONTEXT["draws"],
        WORKER_CONTEXT["stats_by_target"],
        WORKER_CONTEXT["start_round"],
        WORKER_CONTEXT["end_round"],
        WORKER_CONTEXT["games"],
        WORKER_CONTEXT["samples"],
    )


def load_latest_combined():
    best_path = None
    best_end = -1
    for path in OUT_DIR.glob("seed_search_0_*_exact6.json"):
        match = COMBINED_RE.match(path.name)
        if not match:
            continue
        end_seed = int(match.group(1))
        if end_seed > best_end:
            best_end = end_seed
            best_path = path

    if not best_path:
        return None, None
    return json.loads(best_path.read_text(encoding="utf-8")), best_path


def load_checkpoint(path):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))

    combined, combined_path = load_latest_combined()
    if not combined:
        return None

    summary = combined["summary"]
    seeds = combined.get("seeds", [])
    exact6_hits = [item for item in seeds if item.get("rounds_with_best_6", 0) > 0]
    top = sorted(seeds, key=sort_key, reverse=True)[:100]
    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "source": str(combined_path),
        "next_seed": int(summary["seed_end"]) + 1,
        "last_completed_seed": int(summary["seed_end"]),
        "seed_start": int(summary["seed_start"]),
        "seed_end": int(summary["seed_end"]),
        "seed_count": int(summary["seed_count"]),
        "target_exact6": 2,
        "found": None,
        "top": top,
        "exact6_hits": sorted(exact6_hits, key=sort_key, reverse=True),
        "chunks": [],
    }


def save_json(path, payload, retries=5):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, indent=2)
    tmp_path = path.with_name(f"{path.name}.tmp")
    last_error = None
    for attempt in range(retries):
        try:
            tmp_path.write_text(data, encoding="utf-8")
            os.replace(tmp_path, path)
            return
        except OSError as exc:
            last_error = exc
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            time.sleep(0.2 * (attempt + 1))
    raise last_error


def append_jsonl(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def build_stats_by_target(draws, start_round):
    stats_by_target = {}
    history = []
    for draw in draws:
        if draw["round"] > start_round:
            stats_by_target[draw["round"]] = build_stats(history)
        history.append(draw)
    return stats_by_target


def refresh_rankings(state, result, top_limit):
    state["top"].append(result)
    state["top"] = sorted(state["top"], key=sort_key, reverse=True)[:top_limit]
    if result.get("rounds_with_best_6", 0) > 0:
        state["exact6_hits"].append(result)
        state["exact6_hits"] = sorted(state["exact6_hits"], key=sort_key, reverse=True)


def main():
    parser = argparse.ArgumentParser(
        description="Run continuous full-history seed search until an exact-six target is found."
    )
    parser.add_argument("--start-seed", type=int)
    parser.add_argument("--max-seed", type=int, default=30_000_000)
    parser.add_argument("--target-exact6", type=int, default=2)
    parser.add_argument("--start-round", type=int, default=START_ROUND)
    parser.add_argument("--end-round", type=int)
    parser.add_argument("--games", type=int, default=5)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--top", type=int, default=100)
    parser.add_argument("--checkpoint", type=Path, default=OUT_DIR / "seed_search_continuous.json")
    parser.add_argument("--progress-log", type=Path, default=OUT_DIR / "seed_search_continuous_progress.jsonl")
    parser.add_argument("--save-every", type=int, default=10)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    parser.add_argument("--batch-size", type=int)
    args = parser.parse_args()

    draws = load_draws(args.start_round, args.end_round or 9999)
    if not draws:
        raise RuntimeError("No lotto draws loaded")
    end_round = args.end_round or draws[-1]["round"]
    draws = [draw for draw in draws if args.start_round <= draw["round"] <= end_round]
    stats_by_target = build_stats_by_target(draws, args.start_round)

    state = load_checkpoint(args.checkpoint) or {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "source": None,
        "next_seed": args.start_seed if args.start_seed is not None else 0,
        "last_completed_seed": None,
        "seed_start": args.start_seed if args.start_seed is not None else 0,
        "seed_end": None,
        "seed_count": 0,
        "target_exact6": args.target_exact6,
        "found": None,
        "top": [],
        "exact6_hits": [],
        "chunks": [],
    }

    if args.start_seed is not None:
        state["next_seed"] = args.start_seed
        state["seed_start"] = min(int(state.get("seed_start", args.start_seed)), args.start_seed)

    state["target_exact6"] = args.target_exact6
    state["max_seed"] = args.max_seed
    state["end_round"] = end_round
    state["games_per_round"] = args.games
    state["samples_per_round"] = args.samples
    state["workers"] = args.workers
    state["batch_size"] = args.batch_size or max(args.workers * 4, 16)
    save_json(args.checkpoint, state)

    seed = int(state["next_seed"])
    chunk_start = seed
    chunk_best = None
    chunk_exact6 = 0

    print(
        f"continuous seed search: seed={seed}..{args.max_seed}, "
        f"target_exact6={args.target_exact6}, workers={args.workers}, "
        f"batch_size={state['batch_size']}, checkpoint={args.checkpoint}"
    )

    batch_size = int(state["batch_size"])
    while seed <= args.max_seed:
        try:
            with ProcessPoolExecutor(
                max_workers=args.workers,
                initializer=init_worker,
                initargs=(draws, stats_by_target, args.start_round, end_round, args.games, args.samples),
            ) as executor:
                while seed <= args.max_seed:
                    batch_end = min(seed + batch_size - 1, args.max_seed)
                    for result in executor.map(evaluate_seed_worker, range(seed, batch_end + 1)):
                        result_seed = int(result["seed"])
                        refresh_rankings(state, result, args.top)
                        state["last_completed_seed"] = result_seed
                        state["seed_end"] = result_seed
                        state["next_seed"] = result_seed + 1
                        state["seed_count"] = int(state.get("seed_count", 0)) + 1
                        state["updated_at"] = datetime.now().isoformat(timespec="seconds")

                        if chunk_best is None or sort_key(result) > sort_key(chunk_best):
                            chunk_best = result
                        if result.get("rounds_with_best_6", 0) > 0:
                            chunk_exact6 += 1

                        if result.get("rounds_with_best_6", 0) >= args.target_exact6:
                            state["found"] = result
                            save_json(args.checkpoint, state)
                            append_jsonl(
                                args.progress_log,
                                {
                                    "event": "found",
                                    "created_at": datetime.now().isoformat(timespec="seconds"),
                                    "seed": result_seed,
                                    "result": result,
                                },
                            )
                            print(
                                f"FOUND seed={result_seed}: exact6={result['rounds_with_best_6']}",
                                flush=True,
                            )
                            return

                        if result_seed % args.save_every == 0:
                            save_json(args.checkpoint, state)

                        if (result_seed - chunk_start + 1) >= 500:
                            chunk = {
                                "created_at": datetime.now().isoformat(timespec="seconds"),
                                "seed_start": chunk_start,
                                "seed_end": result_seed,
                                "best": chunk_best,
                                "exact6_seed_count": chunk_exact6,
                            }
                            state["chunks"].append(chunk)
                            state["chunks"] = state["chunks"][-500:]
                            save_json(args.checkpoint, state)
                            append_jsonl(args.progress_log, {"event": "chunk", **chunk})
                            print(
                                f"chunk {chunk_start}-{result_seed}: "
                                f"best_seed={chunk_best['seed']} exact6={chunk_best['rounds_with_best_6']} "
                                f"5+={chunk_best['rounds_with_best_5plus']} exact6_seed_count={chunk_exact6}",
                                flush=True,
                            )
                            chunk_start = result_seed + 1
                            chunk_best = None
                            chunk_exact6 = 0

                    seed = batch_end + 1
        except BrokenProcessPool as exc:
            seed = int(state["next_seed"])
            state["pool_restart_count"] = int(state.get("pool_restart_count", 0)) + 1
            state["last_pool_error"] = repr(exc)
            state["last_pool_restart_at"] = datetime.now().isoformat(timespec="seconds")
            state["updated_at"] = datetime.now().isoformat(timespec="seconds")
            save_json(args.checkpoint, state)
            append_jsonl(
                args.progress_log,
                {
                    "event": "pool_restart",
                    "created_at": state["last_pool_restart_at"],
                    "next_seed": seed,
                    "restart_count": state["pool_restart_count"],
                    "error": state["last_pool_error"],
                },
            )
            print(
                f"worker pool failed; restarting from seed={seed} "
                f"restart_count={state['pool_restart_count']}",
                flush=True,
            )
            chunk_start = seed
            chunk_best = None
            chunk_exact6 = 0
            time.sleep(min(30, state["pool_restart_count"] * 2))

    save_json(args.checkpoint, state)
    print(f"completed without finding target through seed={args.max_seed}")


if __name__ == "__main__":
    main()
