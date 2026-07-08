import argparse
import itertools
import json
import random
from collections import Counter
from datetime import datetime
from pathlib import Path

from PickNumber.picknumber_analysis import (
    SEED,
    START_ROUND,
    build_stats,
    generate_pick_numbers,
    load_draws,
    picks_to_json_ready,
    score_candidate,
    select_diverse,
)
from PickNumber.future_engine import generate_future_numbers


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "lotto_data"
STAR_DIR = DATA_DIR / "star"
STAR_BUCKET_SIZE = 500


def get_star_round_dir(round_no):
    start = ((int(round_no) - 1) // STAR_BUCKET_SIZE) * STAR_BUCKET_SIZE + 1
    return STAR_DIR / f"{start}-{start + STAR_BUCKET_SIZE - 1}"


def get_star_file_path(round_no, suffix):
    return get_star_round_dir(round_no) / f"{round_no}_{suffix}"


class StarNumberGenerator:
    """StarNumber hybrid generator.

    engine="pick" uses the PickNumber frequency/pair/rarity engine only.
    engine="star" uses the old StarNumber chaos/entanglement/genetic engine
    and scores those candidates with PickNumber filters.
    engine="hybrid" mixes PickNumber and StarNumber candidate pools.
    engine="future" mixes PickNumber, StarNumber, and the future inference
    ensemble, and is the default.
    """

    def __init__(self, start_round=START_ROUND, end_round=None, seed=SEED, engine="future"):
        self.start_round = start_round
        self.latest_round = self._get_latest_round()
        self.end_round = end_round or self.latest_round
        self.seed = seed
        self.engine = engine
        STAR_DIR.mkdir(parents=True, exist_ok=True)

    def _get_latest_round(self):
        latest_path = DATA_DIR / "latest.lotto"
        if latest_path.exists():
            return int(latest_path.read_text(encoding="utf-8").strip())
        return 0

    def _history(self, end_round=None):
        end = end_round or self.end_round
        return load_draws(1, end)

    def _build_entanglement_matrix(self, history):
        matrix = {n: Counter() for n in range(1, 46)}
        recent_weight = 2.0

        for i, draw in enumerate(history):
            nums = draw["numbers"]
            weight = recent_weight if i >= len(history) - 50 else 1.0
            for n1 in nums:
                for n2 in nums:
                    if n1 != n2:
                        matrix[n1][n2] += weight
        return matrix

    def _analyze_chaos(self, history):
        scores = Counter()
        if len(history) < 20:
            return scores, []

        recent_sums = [sum(d["numbers"]) for d in history[-5:]]
        recent_volatility = sum(
            abs(recent_sums[i] - recent_sums[i - 1]) for i in range(1, 5)
        )

        chaos_points = []
        for i in range(len(history) - 10):
            past_sums = [sum(d["numbers"]) for d in history[i : i + 5]]
            past_volatility = sum(
                abs(past_sums[j] - past_sums[j - 1]) for j in range(1, 5)
            )
            diff = abs(recent_volatility - past_volatility)
            if diff < 10:
                for n in history[i + 5]["numbers"]:
                    scores[n] += 5.0 / (1.0 + diff)
                chaos_points.append(history[i + 5]["round"])

        return scores, chaos_points[-3:]

    def _fitness(self, combo, weights, entanglement):
        combo = sorted(combo)
        score = sum(weights[n] for n in combo)

        entangle_score = 0
        for a, b in itertools.combinations(combo, 2):
            entangle_score += entanglement[a][b] * 0.01
        score += entangle_score

        total = sum(combo)
        if not 100 <= total <= 175:
            score -= 50

        odd = sum(1 for n in combo if n % 2)
        if not 2 <= odd <= 4:
            score -= 30

        for i in range(4):
            if combo[i + 2] == combo[i + 1] + 1 == combo[i] + 2:
                score -= 100

        return score

    def _genetic_algorithm(self, weights, entanglement, rng, generations=55):
        population_size = 120
        mutation_rate = 0.12
        nums = list(range(1, 46))
        weight_list = [max(0.1, weights[n]) for n in nums]

        population = []
        for _ in range(population_size):
            individual = set()
            while len(individual) < 6:
                individual.update(rng.choices(nums, weights=weight_list, k=6 - len(individual)))
            population.append(sorted(individual))

        best_history = []
        best_individual = population[0]

        for _ in range(generations):
            fitness_scores = [self._fitness(ind, weights, entanglement) for ind in population]
            best_idx = max(range(len(fitness_scores)), key=lambda i: fitness_scores[i])
            best_individual = population[best_idx]
            best_history.append(fitness_scores[best_idx])

            min_fit = min(fitness_scores)
            adjusted = [s - min_fit + 1 for s in fitness_scores]

            elite_indices = sorted(
                range(len(fitness_scores)), key=lambda i: fitness_scores[i], reverse=True
            )[:4]
            new_population = [population[i] for i in elite_indices]

            while len(new_population) < population_size:
                parent_1, parent_2 = rng.choices(population, weights=adjusted, k=2)
                cut = rng.randint(1, 5)
                child = list(set(parent_1[:cut] + parent_2[cut:]))

                while len(child) < 6:
                    n = rng.choices(nums, weights=weight_list, k=1)[0]
                    if n not in child:
                        child.append(n)

                if rng.random() < mutation_rate:
                    idx = rng.randint(0, 5)
                    n = rng.randint(1, 45)
                    while n in child:
                        n = rng.randint(1, 45)
                    child[idx] = n

                new_population.append(sorted(child[:6]))

            population = new_population

        return sorted(best_individual), best_history

    def _star_candidates(self, game_count, stats, history, generations=55, attempts_multiplier=10):
        if len(history) < 50:
            return []

        rng = random.Random(self.seed + 991)
        recent_10 = Counter(n for d in history[-10:] for n in d["numbers"])
        chaos_scores, chaos_rounds = self._analyze_chaos(history)
        entanglement = self._build_entanglement_matrix(history)

        weights = {n: 1.0 + recent_10.get(n, 0) for n in range(1, 46)}
        for n, score in chaos_scores.items():
            weights[n] += score

        raw = []
        seen = set()
        attempts = max(3, game_count * attempts_multiplier)
        for _ in range(attempts):
            combo, fit_history = self._genetic_algorithm(weights, entanglement, rng, generations=generations)
            legacy_fitness = fit_history[-1] if fit_history else self._fitness(combo, weights, entanglement)
            variants = [combo]
            weighted_nums = list(range(1, 46))
            weighted_values = [max(0.1, weights[n]) for n in weighted_nums]

            for _ in range(24):
                variant = set(combo)
                remove_count = rng.choice([1, 1, 2])
                for n in rng.sample(list(variant), remove_count):
                    variant.remove(n)
                while len(variant) < 6:
                    n = rng.choices(weighted_nums, weights=weighted_values, k=1)[0]
                    variant.add(n)
                variants.append(sorted(variant))

            for variant in variants:
                nums_key = tuple(sorted(variant))
                if nums_key in seen:
                    continue
                seen.add(nums_key)
                scored = score_candidate(
                    variant,
                    stats,
                    self.end_round - self.start_round + 1,
                    self.start_round,
                    self.end_round,
                )
                if not scored:
                    continue

                variant_fitness = self._fitness(variant, weights, entanglement)
                quantum_score = sum(entanglement[a][b] for a, b in itertools.combinations(variant, 2))
                scored["strategy"] = "H_star_chaos_quantum"
                scored["star_fitness"] = round(max(legacy_fitness, variant_fitness), 2)
                scored["quantum_score"] = round(quantum_score, 2)
                scored["chaos_rounds"] = chaos_rounds
                scored["final_score"] = round(
                    scored["final_score"] + min(45, max(legacy_fitness, variant_fitness) * 1.4),
                    2,
                )
                raw.append(scored)

        return raw

    def generate_games(
        self,
        n,
        output_path=None,
        engine=None,
        write_output=True,
        pick_samples_per_strategy=35000,
        pair_seed_samples=500,
        future_candidate_budget=70000,
        future_min_pool_iterations=2000,
        future_pair_iterations=350,
        future_triple_iterations=220,
        star_generations=55,
        star_attempts_multiplier=10,
    ):
        engine = engine or self.engine
        if engine not in {"pick", "star", "hybrid", "future"}:
            raise ValueError("engine must be one of: pick, star, hybrid, future")

        history = self._history(self.end_round)
        stats = build_stats([d for d in history if self.start_round <= d["round"] <= self.end_round])

        candidates = []
        if engine in {"pick", "hybrid", "future"}:
            _, _, pick_picks = generate_pick_numbers(
                game_count=max(n, 6),
                start_round=self.start_round,
                end_round=self.end_round,
                seed=self.seed,
                samples_per_strategy=pick_samples_per_strategy,
                pair_seed_samples=pair_seed_samples,
            )
            candidates.extend(pick_picks)

        if engine in {"star", "hybrid", "future"}:
            candidates.extend(
                self._star_candidates(
                    n,
                    stats,
                    history,
                    generations=star_generations,
                    attempts_multiplier=star_attempts_multiplier,
                )
            )

        if engine == "future":
            _, _, future_picks = generate_future_numbers(
                game_count=max(n, 6),
                start_round=self.start_round,
                end_round=self.end_round,
                seed=self.seed,
                candidate_budget=future_candidate_budget,
                min_pool_iterations=future_min_pool_iterations,
                pair_iterations=future_pair_iterations,
                triple_iterations=future_triple_iterations,
            )
            candidates.extend(future_picks)

        picks = select_diverse(candidates, limit=n)
        if len(picks) < n:
            raise RuntimeError(f"Could not produce {n} games with {engine} engine")

        payload = picks_to_json_ready(picks)
        if not write_output:
            return payload, None

        path = Path(output_path) if output_path else get_star_file_path(self.end_round + 1, "star.lotto")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload, path

    def build_comment(self, target_round, payload, engine=None):
        engine = engine or self.engine
        lines = [
            f"# StarNumber {target_round} round picks",
            "",
            f"- Range: {self.start_round}-{self.end_round}",
            f"- Games: {len(payload)}",
            f"- Engine: {engine}",
            "- Mix: statistical base rates, recency decay, gap pressure, pair/triple lift, pattern likelihood, stability penalty, PickNumber links, and StarNumber genetic candidates",
            "- Note: lottery draws are independent random events; this is data-based combination design, not a guarantee.",
            "",
            "## Picks",
        ]
        for item in payload:
            nums = " ".join(f"{n:02d}" for n in item["numbers"])
            line = (
                f"{item['rank']}. {nums} | strategy={item['strategy']} | "
                f"sum={item['sum']} | odd_even={item['odd_even']} | "
                f"high_low={item['high_low']} | score={item['final_score']}"
            )
            if "star_fitness" in item:
                line += f" | star_fitness={item['star_fitness']}"
            lines.append(line)
        return "\n".join(lines) + "\n"

    def predict_next(self, n=6, engine=None):
        target_round = self.end_round + 1
        payload, json_path = self.generate_games(n, get_star_file_path(target_round, "star.lotto"), engine)
        comment = self.build_comment(target_round, payload, engine)
        comment_path = get_star_file_path(target_round, "comment.txt")
        comment_path.parent.mkdir(parents=True, exist_ok=True)
        comment_path.write_text(comment, encoding="utf-8")
        return payload, json_path, comment_path

    def analyze_and_predict(
        self,
        target_round,
        n=1,
        engine=None,
        pick_samples_per_strategy=35000,
        pair_seed_samples=500,
        future_candidate_budget=70000,
        future_min_pool_iterations=2000,
        future_pair_iterations=350,
        future_triple_iterations=220,
        star_generations=55,
        star_attempts_multiplier=10,
    ):
        if target_round <= self.start_round:
            raise ValueError("target_round must be greater than start_round")
        previous_end_round = self.end_round
        self.end_round = target_round - 1
        try:
            payload, _ = self.generate_games(
                n,
                engine=engine,
                write_output=False,
                pick_samples_per_strategy=pick_samples_per_strategy,
                pair_seed_samples=pair_seed_samples,
                future_candidate_budget=future_candidate_budget,
                future_min_pool_iterations=future_min_pool_iterations,
                future_pair_iterations=future_pair_iterations,
                future_triple_iterations=future_triple_iterations,
                star_generations=star_generations,
                star_attempts_multiplier=star_attempts_multiplier,
            )
            comment = self.build_comment(target_round, payload, engine)
            return payload, comment
        finally:
            self.end_round = previous_end_round

    def run_verification(
        self,
        start_round=None,
        end_round=None,
        games=5,
        engine=None,
        output_path=None,
        pick_samples_per_strategy=6000,
        pair_seed_samples=120,
        future_candidate_budget=12000,
        future_min_pool_iterations=300,
        future_pair_iterations=60,
        future_triple_iterations=40,
        star_generations=12,
        star_attempts_multiplier=3,
    ):
        first = start_round or max(self.start_round + 1, 2)
        first = max(first, self.start_round + 1, 2)
        last = end_round or self.latest_round
        if last < first:
            raise ValueError("verification end round must be greater than or equal to start round")

        rounds = []
        match_distribution = Counter()
        best_match_distribution = Counter()
        prize_distribution = Counter()
        failed_rounds = []

        for target_round in range(first, last + 1):
            actual = self._load_actual_draw(target_round)
            if not actual:
                failed_rounds.append({"round": target_round, "error": "actual draw not found"})
                continue

            try:
                payload, _ = self.analyze_and_predict(
                    target_round,
                    n=games,
                    engine=engine,
                    pick_samples_per_strategy=pick_samples_per_strategy,
                    pair_seed_samples=pair_seed_samples,
                    future_candidate_budget=future_candidate_budget,
                    future_min_pool_iterations=future_min_pool_iterations,
                    future_pair_iterations=future_pair_iterations,
                    future_triple_iterations=future_triple_iterations,
                    star_generations=star_generations,
                    star_attempts_multiplier=star_attempts_multiplier,
                )
            except Exception as exc:
                failed_rounds.append({"round": target_round, "error": str(exc)})
                continue

            actual_numbers = actual["numbers"]
            actual_bonus = actual.get("bonus")
            games_result = []

            for item in payload:
                predicted = sorted(item["numbers"])
                matched = sorted(set(predicted) & set(actual_numbers))
                bonus_matched = actual_bonus in predicted if actual_bonus else False
                prize_tier = self._prize_tier(len(matched), bonus_matched)
                match_distribution[len(matched)] += 1
                prize_distribution[prize_tier] += 1
                games_result.append(
                    {
                        "rank": item.get("rank"),
                        "predicted_numbers": predicted,
                        "match_count": len(matched),
                        "matched_numbers": matched,
                        "bonus_matched": bonus_matched,
                        "prize_tier": prize_tier,
                        "final_score": item.get("final_score"),
                        "strategy": item.get("strategy"),
                    }
                )

            best_game = max(games_result, key=lambda item: (item["match_count"], item["bonus_matched"]))
            best_match_distribution[best_game["match_count"]] += 1
            rounds.append(
                {
                    "round": target_round,
                    "trained_range": f"{self.start_round}-{target_round - 1}",
                    "actual_numbers": actual_numbers,
                    "bonus": actual_bonus,
                    "best_match_count": best_game["match_count"],
                    "best_rank": best_game["rank"],
                    "games": games_result,
                }
            )

        checked_rounds = len(rounds)
        total_games = sum(len(item["games"]) for item in rounds)
        summary = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "engine": engine or self.engine,
            "start_round": first,
            "end_round": last,
            "checked_rounds": checked_rounds,
            "failed_rounds": len(failed_rounds),
            "games_per_round": games,
            "total_games": total_games,
            "pick_samples_per_strategy": pick_samples_per_strategy,
            "pair_seed_samples": pair_seed_samples,
            "future_candidate_budget": future_candidate_budget,
            "future_min_pool_iterations": future_min_pool_iterations,
            "future_pair_iterations": future_pair_iterations,
            "future_triple_iterations": future_triple_iterations,
            "star_generations": star_generations,
            "star_attempts_multiplier": star_attempts_multiplier,
            "average_match_per_game": round(
                sum(k * v for k, v in match_distribution.items()) / total_games, 4
            )
            if total_games
            else 0,
            "average_best_match_per_round": round(
                sum(k * v for k, v in best_match_distribution.items()) / checked_rounds, 4
            )
            if checked_rounds
            else 0,
            "match_distribution": {str(k): match_distribution.get(k, 0) for k in range(7)},
            "best_match_distribution": {str(k): best_match_distribution.get(k, 0) for k in range(7)},
            "prize_distribution": dict(sorted(prize_distribution.items())),
            "rounds_with_best_3plus": sum(v for k, v in best_match_distribution.items() if k >= 3),
            "rounds_with_best_4plus": sum(v for k, v in best_match_distribution.items() if k >= 4),
            "rounds_with_best_5plus": sum(v for k, v in best_match_distribution.items() if k >= 5),
        }

        report = {
            "summary": summary,
            "failed": failed_rounds,
            "rounds": rounds,
        }
        output_path = Path(output_path) if output_path else STAR_DIR / "verification_summary.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report, output_path

    def _prize_tier(self, match_count, bonus_matched=False):
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

    def _load_actual_draw(self, round_no):
        for path in DATA_DIR.rglob(f"{round_no}.lotto"):
            if "_star" in path.name:
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if data.get("round") == round_no:
                return {
                    "numbers": sorted(data.get("numbers", [])),
                    "bonus": data.get("bonus"),
                }
        return None

    def _load_actual_numbers(self, round_no):
        draw = self._load_actual_draw(round_no)
        return draw["numbers"] if draw else None


def main():
    parser = argparse.ArgumentParser(description="Generate StarNumber lottery games.")
    parser.add_argument("n", nargs="?", type=int, default=6, help="number of games to generate")
    parser.add_argument("--start-round", type=int, default=START_ROUND)
    parser.add_argument("--end-round", type=int)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--engine", choices=["pick", "star", "hybrid", "future"], default="future")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", action="store_true", help="run historical verification summary")
    parser.add_argument("--verify-start-round", type=int)
    parser.add_argument("--verify-end-round", type=int)
    parser.add_argument("--verify-games", type=int)
    parser.add_argument("--verify-output", type=Path)
    parser.add_argument("--verify-pick-samples", type=int, default=6000)
    parser.add_argument("--verify-pair-samples", type=int, default=120)
    parser.add_argument("--verify-future-budget", type=int, default=12000)
    parser.add_argument("--verify-future-min-pool-iterations", type=int, default=300)
    parser.add_argument("--verify-future-pair-iterations", type=int, default=60)
    parser.add_argument("--verify-future-triple-iterations", type=int, default=40)
    parser.add_argument("--verify-star-generations", type=int, default=12)
    parser.add_argument("--verify-star-attempts-multiplier", type=int, default=3)
    args = parser.parse_args()

    generator = StarNumberGenerator(
        start_round=args.start_round,
        end_round=args.end_round,
        seed=args.seed,
        engine=args.engine,
    )

    if args.verify:
        report, path = generator.run_verification(
            start_round=args.verify_start_round,
            end_round=args.verify_end_round,
            games=args.verify_games or args.n,
            engine=args.engine,
            output_path=args.verify_output,
            pick_samples_per_strategy=args.verify_pick_samples,
            pair_seed_samples=args.verify_pair_samples,
            future_candidate_budget=args.verify_future_budget,
            future_min_pool_iterations=args.verify_future_min_pool_iterations,
            future_pair_iterations=args.verify_future_pair_iterations,
            future_triple_iterations=args.verify_future_triple_iterations,
            star_generations=args.verify_star_generations,
            star_attempts_multiplier=args.verify_star_attempts_multiplier,
        )
        summary = report["summary"]
        print(f"verification saved: {path}")
        print(
            "summary: "
            f"rounds={summary['checked_rounds']}, "
            f"games={summary['total_games']}, "
            f"avg_match={summary['average_match_per_game']}, "
            f"avg_best={summary['average_best_match_per_round']}, "
            f"best_3plus={summary['rounds_with_best_3plus']}, "
            f"best_4plus={summary['rounds_with_best_4plus']}, "
            f"failed={summary['failed_rounds']}"
        )
        return

    if args.output:
        payload, path = generator.generate_games(args.n, args.output, args.engine)
        target_round = generator.end_round + 1
        comment = generator.build_comment(target_round, payload, args.engine)
        comment_path = Path(args.output).with_suffix(".txt")
        comment_path.write_text(comment, encoding="utf-8")
    else:
        payload, path, comment_path = generator.predict_next(args.n, args.engine)

    for item in payload:
        numbers = " ".join(f"{n:02d}" for n in item["numbers"])
        print(f"{item['rank']}. {numbers} | {item['strategy']} | score={item['final_score']}")
    print(f"saved: {path}")
    print(f"comment: {comment_path}")


if __name__ == "__main__":
    main()
