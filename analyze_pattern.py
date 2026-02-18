import json
import os
from collections import Counter
import statistics
from itertools import combinations

class LottoAnalyzer:
    def __init__(self, start_round, end_round):
        self.start_round = start_round
        self.end_round = end_round
        self.data = []
        self._load_all_data()

    def _get_file_path(self, round_num):
        if 1 <= round_num <= 1000:
            return os.path.join("lotto_data/1-1000", f"{round_num}.lotto")
        elif 1001 <= round_num <= 2000:
            return os.path.join("lotto_data/1001-2000", f"{round_num}.lotto")
        else:
            return None

    def _load_all_data(self):
        print(f"데이터 로딩 중 ({self.start_round}회 ~ {self.end_round}회)...")
        for r in range(self.start_round, self.end_round + 1):
            path = self._get_file_path(r)
            if path and os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        self.data.append(json.load(f))
                except Exception as e:
                    print(f"Error reading {r}회: {e}")
        # 회차순 정렬 보장
        self.data.sort(key=lambda x: x['round'])
        print(f"총 {len(self.data)}개 회차 데이터 로드 완료.\n")

    def _print_group_stats(self, group, title):
        if not group:
            print(f"  [{title}] 데이터 없음")
            return

        nums = []
        sums = []
        for d in group:
            nums.extend(d['numbers'])
            sums.append(d['analysis']['sum_value'])
            
        avg_sum = statistics.mean(sums) if sums else 0
        top_nums = Counter(nums).most_common(5)
        top_str = ", ".join([f"{n}({c})" for n, c in top_nums])
        
        print(f"  [{title}] (대상 {len(group)}회)")
        print(f"    - 평균 총합: {avg_sum:.1f}")
        print(f"    - 최다 출현 Top 5: {top_str}")

    # =================================================================
    # [기존 분석 로직]
    # =================================================================
    def basic_analysis(self):
        print("="*60)
        print(f"[1] 기본 종합 분석 ({self.start_round}~{self.end_round}회)")
        self._print_group_stats(self.data, "전체 구간")

    def specific_modulo_analysis(self, modulo, remainder):
        print("\n" + "="*60)
        print(f"[주기 분석] {modulo}회 주기 (나머지 {remainder})")
        target_rounds = [d for d in self.data if d['round'] % modulo == remainder]
        if not target_rounds:
            print("  해당 조건의 회차가 없습니다.")
            return
        rounds_desc = ", ".join(str(d['round']) for d in target_rounds)
        if len(rounds_desc) > 60: rounds_desc = rounds_desc[:60] + "..."
        self._print_group_stats(target_rounds, f"대상 회차: {rounds_desc}")

    def interval_analysis(self, interval):
        print("\n" + "="*60)
        print(f"[구간 분석] {interval}회 단위 흐름")
        for i in range(0, len(self.data), interval):
            chunk = self.data[i:i+interval]
            if not chunk: continue
            start = chunk[0]['round']
            end = chunk[-1]['round']
            sums = [d['analysis']['sum_value'] for d in chunk]
            avg_sum = statistics.mean(sums)
            nums = [n for d in chunk for n in d['numbers']]
            top_num = Counter(nums).most_common(1)
            top_str = f"{top_num[0][0]}번({top_num[0][1]}회)" if top_num else "-"
            print(f"  [{start}회~{end}회] 평균합: {avg_sum:5.1f} | 최다출현: {top_str}")

    # =================================================================
    # [전문가용 고급 분석 로직]
    # =================================================================
    def advanced_pattern_analysis(self):
        print("\n" + "="*60)
        print("[전문가용 고급 패턴 분석]")
        
        if len(self.data) < 2:
            print("  데이터가 부족하여 고급 분석을 수행할 수 없습니다.")
            return

        # 1. 이월수 (Carryover) 분석
        # 직전 회차의 번호가 이번 회차에 몇 개나 다시 나왔는가?
        carryover_counts = Counter()
        for i in range(1, len(self.data)):
            prev_nums = set(self.data[i-1]['numbers'])
            curr_nums = set(self.data[i]['numbers'])
            intersection = prev_nums & curr_nums
            carryover_counts[len(intersection)] += 1
            
        print("\n  1. 이월수(전회차 번호 재출현) 통계:")
        total_analyzed = sum(carryover_counts.values())
        for count, freq in sorted(carryover_counts.items()):
            ratio = freq / total_analyzed * 100
            print(f"    - {count}개 이월: {freq}회 ({ratio:.1f}%)")

        # 2. 연번 (Consecutive Numbers) 분석
        # 번호가 연속으로 이어지는 경우 (예: 12, 13)
        consecutive_count = 0
        for d in self.data:
            nums = sorted(d['numbers'])
            has_consecutive = False
            for i in range(len(nums) - 1):
                if nums[i+1] == nums[i] + 1:
                    has_consecutive = True
                    break
            if has_consecutive:
                consecutive_count += 1
        
        print(f"\n  2. 연번(연속된 숫자) 출현 빈도:")
        print(f"    - 연번 포함 회차: {consecutive_count}회 ({consecutive_count/len(self.data)*100:.1f}%)")

        # 3. 끝수 (Ending Digit) 분석
        # 각 번호의 1의 자리 숫자 빈도
        ending_digits = Counter()
        for d in self.data:
            for num in d['numbers']:
                ending_digits[num % 10] += 1
        
        print(f"\n  3. 끝수(1의 자리) 출현 순위:")
        print("    (예: 1, 11, 21, 31, 41 -> 1끝수)")
        top_endings = ending_digits.most_common()
        top_str = ", ".join([f"{digit}끝({cnt}회)" for digit, cnt in top_endings[:5]])
        print(f"    - 상위 5개 끝수: {top_str}")

        # 4. 동반 출현 (Co-occurrence) 분석 - 궁합수
        # 가장 자주 같이 나오는 번호 쌍
        pair_counts = Counter()
        for d in self.data:
            nums = sorted(d['numbers'])
            # 6개 번호 중 2개씩 짝지어 카운트
            for pair in combinations(nums, 2):
                pair_counts[pair] += 1
        
        print(f"\n  4. 베스트 궁합수 (동반 출현 Top 5):")
        for pair, count in pair_counts.most_common(5):
            print(f"    - {pair[0]}번 & {pair[1]}번: 함께 {count}회 출현")

if __name__ == "__main__":
    # 분석 범위 설정
    START_ROUND = 1110
    END_ROUND = 1210
    
    analyzer = LottoAnalyzer(START_ROUND, END_ROUND)
    
    # 기본 및 구간 분석
    analyzer.basic_analysis()
    analyzer.specific_modulo_analysis(10, 0) # 10회 주기
    analyzer.interval_analysis(10)           # 10회 구간
    
    # 전문가용 고급 분석 실행
    analyzer.advanced_pattern_analysis()
