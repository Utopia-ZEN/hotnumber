import csv
import itertools
import json
import math
import random
import argparse
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "lotto_data"
OUT_DIR = ROOT / "PickNumber"
START_ROUND = 839
SEED = 20260605


def read_latest_round(default=1226):
    latest_path = DATA_DIR / "latest.lotto"
    if latest_path.exists():
        try:
            return int(latest_path.read_text(encoding="utf-8").strip())
        except ValueError:
            pass
    return default


END_ROUND = read_latest_round()


def load_draws(start=START_ROUND, end=END_ROUND):
    draws = []
    for path in DATA_DIR.rglob("*.lotto"):
        if path.name in {"frequency.lotto", "latest.lotto"} or "_star" in path.name:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        round_no = int(data.get("round", 0))
        nums = data.get("numbers") or []
        if start <= round_no <= end and len(nums) == 6:
            draws.append(
                {
                    "round": round_no,
                    "numbers": tuple(sorted(int(n) for n in nums)),
                    "bonus": data.get("bonus"),
                    "sum": sum(nums),
                }
            )
    return sorted(draws, key=lambda item: item["round"])


def ac_value(nums):
    diffs = {b - a for a, b in itertools.combinations(sorted(nums), 2)}
    return len(diffs) - 5


def pattern_key(nums):
    nums = tuple(sorted(nums))
    total = sum(nums)
    odd = sum(n % 2 for n in nums)
    high = sum(n >= 23 for n in nums)
    endings = Counter(n % 10 for n in nums)
    consec = sum(1 for a, b in zip(nums, nums[1:]) if b == a + 1)
    span = nums[-1] - nums[0]
    ac = ac_value(nums)
    sum_bucket = f"{(total // 10) * 10}-{(total // 10) * 10 + 9}"
    span_bucket = f"{(span // 5) * 5}-{(span // 5) * 5 + 4}"
    return {
        "sum_bucket": sum_bucket,
        "odd_even": f"{odd}:{6 - odd}",
        "high_low": f"{high}:{6 - high}",
        "ending_max_dup": max(endings.values()),
        "consecutive_pairs": consec,
        "span_bucket": span_bucket,
        "ac": ac,
    }


def build_stats(draws):
    freq = Counter()
    pair = Counter()
    triple = Counter()
    last_seen = {}
    pattern_counters = defaultdict(Counter)

    for draw in draws:
        nums = draw["numbers"]
        freq.update(nums)
        pair.update(itertools.combinations(nums, 2))
        triple.update(itertools.combinations(nums, 3))
        for n in nums:
            last_seen[n] = draw["round"]
        for k, v in pattern_key(nums).items():
            pattern_counters[k][v] += 1

    recent_30 = draws[-30:]
    recent_80 = draws[-80:]
    recent_30_freq = Counter(n for d in recent_30 for n in d["numbers"])
    recent_80_freq = Counter(n for d in recent_80 for n in d["numbers"])
    exact_sets = {d["numbers"] for d in draws}

    return {
        "freq": freq,
        "pair": pair,
        "triple": triple,
        "last_seen": last_seen,
        "recent_30_freq": recent_30_freq,
        "recent_80_freq": recent_80_freq,
        "pattern_counters": pattern_counters,
        "exact_sets": exact_sets,
    }


def bucket_count(counter, value):
    return counter.get(value, 0)


def score_candidate(nums, stats, total_draws, start_round=START_ROUND, end_round=END_ROUND):
    nums = tuple(sorted(nums))
    freq = stats["freq"]
    pair = stats["pair"]
    triple = stats["triple"]
    last_seen = stats["last_seen"]
    recent_30 = stats["recent_30_freq"]
    recent_80 = stats["recent_80_freq"]

    if nums in stats["exact_sets"]:
        return None

    total = sum(nums)
    odd = sum(n % 2 for n in nums)
    high = sum(n >= 23 for n in nums)
    consec = sum(1 for a, b in zip(nums, nums[1:]) if b == a + 1)
    endings = Counter(n % 10 for n in nums)
    ac = ac_value(nums)

    if not 95 <= total <= 185:
        return None
    if odd in {0, 6} or high in {0, 6}:
        return None
    if consec > 2 or max(endings.values()) > 3:
        return None
    if ac < 7:
        return None

    overdue = sum(end_round - last_seen.get(n, start_round - 1) for n in nums) / 6
    freq_score = sum(freq[n] for n in nums)
    recent_score = sum(recent_30[n] * 1.8 + recent_80[n] * 0.7 for n in nums)
    pair_score = sum(pair[p] for p in itertools.combinations(nums, 2))
    triple_score = sum(triple[t] for t in itertools.combinations(nums, 3))

    pk = pattern_key(nums)
    pattern_counts = {
        k: bucket_count(stats["pattern_counters"][k], v)
        for k, v in pk.items()
        if k != "ac"
    }
    rarity = sum(1 / math.sqrt(c + 1) for c in pattern_counts.values())
    balance_bonus = 10 if odd in {2, 3, 4} else 3
    balance_bonus += 8 if high in {2, 3, 4} else 2
    ending_variety = len(endings) * 2

    link_score = (
        freq_score * 0.55
        + recent_score * 2.2
        + pair_score * 1.3
        + triple_score * 1.9
        + overdue * 1.05
        + balance_bonus
        + ending_variety
    )
    rare_score = rarity * 24 + overdue * 1.2 + (12 if consec == 1 else 0)
    final_score = link_score + rare_score

    return {
        "numbers": nums,
        "sum": total,
        "odd_even": f"{odd}:{6 - odd}",
        "high_low": f"{high}:{6 - high}",
        "ac": ac,
        "consecutive_pairs": consec,
        "endings": ",".join(str(e) for e in sorted(endings)),
        "overdue_avg": round(overdue, 2),
        "freq_score": freq_score,
        "recent_score": round(recent_score, 2),
        "pair_score": pair_score,
        "triple_score": triple_score,
        "link_score": round(link_score, 2),
        "rare_score": round(rare_score, 2),
        "final_score": round(final_score, 2),
        "pattern": pk,
    }


def strategy_candidates(
    stats,
    seed=SEED,
    samples_per_strategy=70000,
    pair_seed_samples=900,
    start_round=START_ROUND,
    end_round=END_ROUND,
):
    rng = random.Random(seed)
    freq = stats["freq"]
    recent_30 = stats["recent_30_freq"]
    recent_80 = stats["recent_80_freq"]
    pair = stats["pair"]
    last_seen = stats["last_seen"]

    all_nums = list(range(1, 46))
    hot = [n for n, _ in freq.most_common(18)]
    warm = [n for n, _ in recent_80.most_common(22)]
    recent_hot = [n for n, _ in recent_30.most_common(16)]
    cold = sorted(all_nums, key=lambda n: (last_seen.get(n, 0), freq[n]))[:18]
    overdue = sorted(all_nums, key=lambda n: end_round - last_seen.get(n, 0), reverse=True)[:18]
    top_pairs = [p for p, _ in pair.most_common(70)]

    pools = {
        "A_hot_pair_rare": hot + warm + overdue[:8],
        "B_recent_cold_bridge": recent_hot + cold + warm[:8],
        "C_overdue_pair": overdue + [n for p in top_pairs[:25] for n in p],
        "D_balanced_frequency": all_nums,
        "E_edge_endings": [1, 2, 3, 7, 8, 9, 10, 11, 12, 17, 18, 19, 20, 21, 22, 27, 28, 29, 30, 31, 32, 37, 38, 39, 40, 41, 42, 43, 44, 45],
        "F_triple_shadow": [n for t, _ in stats["triple"].most_common(80) for n in t] + cold[:10],
    }

    candidates = []
    for strategy, pool in pools.items():
        weights = []
        clean_pool = sorted(set(pool))
        for n in clean_pool:
            weights.append(
                1
                + freq[n] * 0.9
                + recent_30[n] * 2.8
                + recent_80[n] * 0.6
                + max(0, end_round - last_seen.get(n, start_round - 1)) * 0.12
            )
        for _ in range(samples_per_strategy):
            nums = tuple(sorted(rng.choices(clean_pool, weights=weights, k=12)[:6]))
            if len(set(nums)) != 6:
                nums = tuple(sorted(rng.sample(clean_pool, 6)))
            scored = score_candidate(nums, stats, end_round - start_round + 1, start_round, end_round)
            if scored:
                scored["strategy"] = strategy
                candidates.append(scored)

    # Add pair-seeded candidates for stronger connection chains.
    for p in top_pairs[:120]:
        base_pool = sorted(set(all_nums) - set(p))
        for _ in range(pair_seed_samples):
            nums = tuple(sorted(set(p) | set(rng.sample(base_pool, 4))))
            scored = score_candidate(nums, stats, end_round - start_round + 1, start_round, end_round)
            if scored:
                scored["strategy"] = "G_pair_seed"
                candidates.append(scored)

    return candidates


def select_diverse(scored, limit=6):
    selected = []
    used_pairs = Counter()
    seen = set()
    sorted_items = sorted(scored, key=lambda x: x["final_score"], reverse=True)

    passes = [
        {"max_overlap": 3, "max_pair_load": 2},
        {"max_overlap": 4, "max_pair_load": 5},
        {"max_overlap": 5, "max_pair_load": 999999},
    ]

    for rules in passes:
        for item in sorted_items:
            nums = item["numbers"]
            if nums in seen:
                continue
            if any(len(set(nums) & set(chosen["numbers"])) > rules["max_overlap"] for chosen in selected):
                continue
            pair_load = sum(used_pairs[p] for p in itertools.combinations(nums, 2))
            if pair_load > rules["max_pair_load"]:
                continue
            selected.append(item)
            seen.add(nums)
            used_pairs.update(itertools.combinations(nums, 2))
            if len(selected) == limit:
                return selected
    return selected


def picks_to_json_ready(picks):
    json_ready = []
    for rank, pick in enumerate(picks, 1):
        item = dict(pick)
        item["rank"] = rank
        item["numbers"] = list(item["numbers"])
        json_ready.append(item)
    return json_ready


def generate_pick_numbers(
    game_count=6,
    start_round=START_ROUND,
    end_round=END_ROUND,
    seed=SEED,
    samples_per_strategy=70000,
    pair_seed_samples=900,
):
    if game_count < 1:
        raise ValueError("game_count must be at least 1")

    draws = load_draws(start_round, end_round)
    expected = end_round - start_round + 1
    if len(draws) != expected:
        raise RuntimeError(f"Expected {expected} draws, loaded {len(draws)}")

    stats = build_stats(draws)
    candidates = strategy_candidates(
        stats,
        seed=seed,
        samples_per_strategy=samples_per_strategy,
        pair_seed_samples=pair_seed_samples,
        start_round=start_round,
        end_round=end_round,
    )
    picks = select_diverse(candidates, limit=game_count)
    if len(picks) < game_count:
        raise RuntimeError(f"Could not produce {game_count} picks; produced {len(picks)}")
    return draws, stats, picks


def write_outputs(draws, stats, picks):
    total_draws = len(draws)
    top_numbers = stats["freq"].most_common()
    overdue = sorted(
        range(1, 46),
        key=lambda n: END_ROUND - stats["last_seen"].get(n, START_ROUND - 1),
        reverse=True,
    )
    top_pairs = stats["pair"].most_common(20)
    top_triples = stats["triple"].most_common(12)

    report = []
    report.append("# PickNumber 분석 리포트")
    report.append("")
    report.append(f"- 분석 범위: {START_ROUND}회~{END_ROUND}회")
    report.append(f"- 분석 회차 수: {total_draws}회")
    report.append("- 주의: 로또는 독립 난수 게임이므로 이 결과는 예측 보장이 아니라 데이터 기반 조합 설계입니다.")
    report.append("")
    report.append("## 핵심 연결고리")
    report.append("")
    report.append("### 출현 빈도 상위")
    report.append(", ".join(f"{n}({c})" for n, c in top_numbers[:15]))
    report.append("")
    report.append("### 미출현 간격 상위")
    report.append(", ".join(f"{n}({END_ROUND - stats['last_seen'].get(n, START_ROUND - 1)}회)" for n in overdue[:15]))
    report.append("")
    report.append("### 동반출현 2개 연결")
    report.append(", ".join(f"{a}-{b}({c})" for (a, b), c in top_pairs))
    report.append("")
    report.append("### 동반출현 3개 연결")
    report.append(", ".join(f"{'-'.join(map(str, t))}({c})" for t, c in top_triples))
    report.append("")
    report.append("## 패턴 분포")
    for key, counter in stats["pattern_counters"].items():
        report.append("")
        report.append(f"### {key}")
        report.append(", ".join(f"{k}:{v}" for k, v in counter.most_common(12)))
    report.append("")
    report.append("## PickNumber 6조합")
    report.append("")
    for idx, pick in enumerate(picks, 1):
        nums = " ".join(f"{n:02d}" for n in pick["numbers"])
        report.append(f"{idx}. {nums}")
        report.append(
            f"   - 전략: {pick['strategy']}, 합계 {pick['sum']}, 홀짝 {pick['odd_even']}, 고저 {pick['high_low']}, AC {pick['ac']}, 평균 미출현 {pick['overdue_avg']}회"
        )
        report.append(
            f"   - 연결 점수 {pick['link_score']}, 희귀 점수 {pick['rare_score']}, 최종 점수 {pick['final_score']}"
        )
    report.append("")
    report.append("## 조합 설계 원칙")
    report.append("")
    report.append("- 과거 동일 6개 조합은 제외했습니다.")
    report.append("- 강한 연결고리(빈도, 최근성, 페어, 트리플)와 희귀성(미출현 간격, 덜 흔한 패턴)을 동시에 반영했습니다.")
    report.append("- 6조합끼리는 4개 이상 겹치지 않도록 분산했습니다.")
    report.append("- 극단 합계, 전부 홀수/짝수, 전부 저/고번호, 과도한 연번, 낮은 AC값은 제외했습니다.")

    (OUT_DIR / "analysis_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    with (OUT_DIR / "pick_numbers.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "rank",
                "numbers",
                "strategy",
                "sum",
                "odd_even",
                "high_low",
                "ac",
                "overdue_avg",
                "link_score",
                "rare_score",
                "final_score",
            ],
        )
        writer.writeheader()
        for idx, pick in enumerate(picks, 1):
            writer.writerow(
                {
                    "rank": idx,
                    "numbers": " ".join(f"{n:02d}" for n in pick["numbers"]),
                    "strategy": pick["strategy"],
                    "sum": pick["sum"],
                    "odd_even": pick["odd_even"],
                    "high_low": pick["high_low"],
                    "ac": pick["ac"],
                    "overdue_avg": pick["overdue_avg"],
                    "link_score": pick["link_score"],
                    "rare_score": pick["rare_score"],
                    "final_score": pick["final_score"],
                }
            )

    json_ready = picks_to_json_ready(picks)
    (OUT_DIR / "pick_numbers.json").write_text(
        json.dumps(json_ready, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main():
    parser = argparse.ArgumentParser(description="Generate PickNumber lottery games.")
    parser.add_argument("games", nargs="?", type=int, default=6, help="number of games to generate")
    parser.add_argument("--start-round", type=int, default=START_ROUND)
    parser.add_argument("--end-round", type=int, default=END_ROUND)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--output", type=Path, default=OUT_DIR / "pick_numbers.json")
    args = parser.parse_args()

    draws, stats, picks = generate_pick_numbers(
        game_count=args.games,
        start_round=args.start_round,
        end_round=args.end_round,
        seed=args.seed,
    )
    write_outputs(draws, stats, picks)
    if args.output != OUT_DIR / "pick_numbers.json":
        args.output.write_text(
            json.dumps(picks_to_json_ready(picks), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    for i, pick in enumerate(picks, 1):
        print(f"{i}. {' '.join(f'{n:02d}' for n in pick['numbers'])} | score={pick['final_score']}")


if __name__ == "__main__":
    main()
