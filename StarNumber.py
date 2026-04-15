import json
import os
import math
import random
from collections import Counter
from analyze_pattern import LottoAnalyzer

class StarNumberGenerator:
    def __init__(self):
        self.data_dir = "lotto_data"
        self.star_dir = os.path.join(self.data_dir, "star")
        if not os.path.exists(self.star_dir):
            os.makedirs(self.star_dir)
        
        latest_path = os.path.join(self.data_dir, "latest.lotto")
        if os.path.exists(latest_path):
            with open(latest_path, 'r') as f:
                self.latest_round = int(f.read().strip())
        else:
            self.latest_round = 0

        self.analyzer = LottoAnalyzer(1, self.latest_round)
        self.all_data = self.analyzer.data

    # --- [1] 양자 얽힘 (Quantum Entanglement) ---
    def _build_entanglement_matrix(self, history):
        """번호 간의 동시 출현 빈도를 기반으로 얽힘 강도 계산"""
        matrix = {n: Counter() for n in range(1, 46)}
        # 최근 50회차 가중치 부여
        recent_weight = 2.0
        
        for i, d in enumerate(history):
            nums = d['numbers']
            weight = recent_weight if i >= len(history) - 50 else 1.0
            
            for n1 in nums:
                for n2 in nums:
                    if n1 != n2:
                        matrix[n1][n2] += weight
        return matrix

    # --- [2] 카오스 이론 (Chaos Theory - Bifurcation) ---
    def _analyze_chaos(self, history):
        """급격한 패턴 변화(분기점) 감지 및 유사 구간 탐색"""
        scores = Counter()
        if len(history) < 20: return scores, []

        # 최근 5회차의 총합 변화량 계산 (변동성 측정)
        recent_sums = [sum(d['numbers']) for d in history[-5:]]
        recent_volatility = sum(abs(recent_sums[i] - recent_sums[i-1]) for i in range(1, 5))
        
        # 과거 데이터에서 유사한 변동성을 보인 구간 탐색
        chaos_points = []
        for i in range(len(history) - 10):
            past_sums = [sum(d['numbers']) for d in history[i:i+5]]
            past_volatility = sum(abs(past_sums[j] - past_sums[j-1]) for j in range(1, 5))
            
            # 변동성 유사도 (차이가 적을수록 유사)
            diff = abs(recent_volatility - past_volatility)
            if diff < 10: # 임계값
                # 유사 분기점 직후 회차 번호에 가중치
                next_nums = history[i+5]['numbers']
                for n in next_nums:
                    scores[n] += 5.0 / (1.0 + diff) # 유사할수록 높은 점수
                chaos_points.append(history[i+5]['round'])
                
        return scores, chaos_points[-3:] # 최근 유사 회차 3개 반환

    # --- [3] 유전 알고리즘 (Genetic Algorithm) ---
    def _fitness(self, combo, weights, entanglement):
        """적합도 함수: 가중치 합 + 얽힘 점수 + 필터 패널티"""
        score = sum(weights[n] for n in combo)
        
        # 얽힘 점수 추가
        entangle_score = 0
        for i in range(6):
            for j in range(i+1, 6):
                n1, n2 = combo[i], combo[j]
                entangle_score += entanglement[n1][n2] * 0.01
        
        score += entangle_score
        
        # 필터 패널티 (조건 불만족 시 점수 대폭 삭감)
        if not (100 <= sum(combo) <= 175): score -= 50
        odd = sum(1 for n in combo if n % 2 != 0)
        if not (2 <= odd <= 4): score -= 30
        
        # 3연번 패널티
        sorted_c = sorted(combo)
        for k in range(4):
            if sorted_c[k+2] == sorted_c[k+1]+1 == sorted_c[k]+2:
                score -= 100
                
        return score

    def _genetic_algorithm(self, weights, entanglement):
        """진화 연산 수행"""
        POPULATION_SIZE = 100
        GENERATIONS = 50
        MUTATION_RATE = 0.1
        
        # 초기 세대 생성 (가중치 기반 랜덤)
        population = []
        nums = list(range(1, 46))
        w_list = [weights[n] for n in nums]
        
        for _ in range(POPULATION_SIZE):
            # 중복 없이 6개 추출
            ind = set()
            while len(ind) < 6:
                ind.update(random.choices(nums, weights=w_list, k=6-len(ind)))
            population.append(sorted(list(ind)))
            
        best_history = []
        
        for gen in range(GENERATIONS):
            # 적합도 평가
            fitness_scores = [self._fitness(ind, weights, entanglement) for ind in population]
            
            # 최고점 기록
            max_score = max(fitness_scores)
            best_ind = population[fitness_scores.index(max_score)]
            best_history.append(max_score)
            
            # 선택 (Roulette Wheel Selection)
            # 음수 점수 보정
            min_fit = min(fitness_scores)
            adj_scores = [s - min_fit + 1 for s in fitness_scores]
            
            new_population = []
            # 엘리트 보존 (상위 2개 무조건 생존)
            elite_indices = sorted(range(len(fitness_scores)), key=lambda i: fitness_scores[i], reverse=True)[:2]
            for idx in elite_indices:
                new_population.append(population[idx])
            
            while len(new_population) < POPULATION_SIZE:
                # 부모 선택
                p1, p2 = random.choices(population, weights=adj_scores, k=2)
                
                # 교차 (Crossover) - 단일 지점
                cut = random.randint(1, 5)
                child = list(set(p1[:cut] + p2[cut:]))
                
                # 부족한 번호 채우기
                while len(child) < 6:
                    new_n = random.choices(nums, weights=w_list)[0]
                    if new_n not in child: child.append(new_n)
                
                # 돌연변이 (Mutation)
                if random.random() < MUTATION_RATE:
                    idx = random.randint(0, 5)
                    new_n = random.randint(1, 45)
                    while new_n in child: new_n = random.randint(1, 45)
                    child[idx] = new_n
                
                new_population.append(sorted(child[:6]))
            
            population = new_population

        return best_ind, best_history

    def analyze_and_predict(self, target_round):
        history = [d for d in self.all_data if d['round'] < target_round]
        actual_data = next((d for d in self.all_data if d['round'] == target_round), None)
        
        if len(history) < 50:
            return [1, 2, 3, 4, 5, 6], "데이터 부족"

        # --- 1. 종합 가중치 산출 ---
        weights = {n: 1.0 for n in range(1, 46)}
        details = {n: [] for n in range(1, 46)}

        # A. 기본 통계 (최근 10주)
        recent_10 = [n for d in history[-10:] for n in d['numbers']]
        freq_10 = Counter(recent_10)
        for n in range(1, 46):
            w = freq_10.get(n, 0) * 1.0
            weights[n] += w
            if w > 0: details[n].append(f"최근빈도({w:.1f})")

        # B. 카오스 이론 (분기점 분석)
        chaos_scores, chaos_rounds = self._analyze_chaos(history)
        for n, s in chaos_scores.items():
            weights[n] += s
            if s > 2.0: details[n].append(f"카오스패턴({s:.1f})")

        # C. 양자 얽힘 매트릭스 생성
        entanglement = self._build_entanglement_matrix(history)

        # --- 2. 유전 알고리즘 실행 ---
        best_combo, fit_history = self._genetic_algorithm(weights, entanglement)
        recommended = sorted(best_combo)

        # --- 리포트 작성 ---
        report = []
        report.append(f"■ {target_round}회차 [Chaos & Quantum] 분석 리포트 (v6.0) ■")
        report.append("="*60)
        
        if actual_data:
            actual_nums = actual_data['numbers']
            bonus = actual_data.get('bonus')
            matched = set(recommended) & set(actual_nums)
            rank = "낙첨"
            if len(matched) == 6: rank = "1등"
            elif len(matched) == 5 and bonus in recommended: rank = "2등"
            elif len(matched) == 5: rank = "3등"
            elif len(matched) == 4: rank = "4등"
            elif len(matched) == 3: rank = "5등"
            report.append(f"▶ [검증 결과] {len(matched)}개 적중 {sorted(list(matched))} -> {rank}")
            report.append(f"   (실제: {actual_nums} +{bonus})")
        
        report.append("-" * 60)
        report.append("1. 적용된 알고리즘 (v6.0)")
        report.append("  - 카오스 이론: 급격한 패턴 변화(분기점)를 감지하여 유사 과거 회차의 번호 추적")
        if chaos_rounds:
            report.append(f"    (유사 분기점 회차: {chaos_rounds})")
        report.append("  - 양자 얽힘: 번호 간의 보이지 않는 연결고리(동시 출현)를 매트릭스로 분석")
        report.append("  - 유전 알고리즘: 50세대에 걸친 교배와 돌연변이를 통해 최적의 조합 진화")
        report.append(f"    (적합도 진화: {fit_history[0]:.1f} -> {fit_history[-1]:.1f})")
        report.append("-" * 60)
        
        report.append("2. 번호별 DNA 분석 (선택 근거)")
        for n in recommended:
            w = weights[n]
            d_str = ", ".join(details[n]) if details[n] else "기본 가중치"
            
            # 얽힘 파트너 찾기 (조합 내에서)
            partners = []
            for other in recommended:
                if n == other: continue
                if entanglement[n][other] > 5: # 강한 얽힘 기준
                    partners.append(f"{other}번")
            
            report.append(f"  ★ [{n:02d}번] 가중치 합: {w:.1f}")
            report.append(f"     └ 근거: {d_str}")
            if partners:
                report.append(f"     └ 양자 얽힘(동반): {', '.join(partners)}")
            
        report.append("-" * 60)
        report.append(f"★ 최종 진화 결과: {recommended}")

        return recommended, "\n".join(report)

    def run_verification(self):
        print(f"2회차부터 {self.latest_round}회차까지 v6.0 알고리즘 검증 중...")
        for r in range(2, self.latest_round + 1):
            prediction, comment = self.analyze_and_predict(r)
            
            actual = next((d['numbers'] for d in self.all_data if d['round'] == r), None)
            result = {"round": r, "predicted_numbers": prediction, "actual_numbers": actual}
            
            with open(os.path.join(self.star_dir, f"{r}_star.lotto"), 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=4, ensure_ascii=False)
            
            with open(os.path.join(self.star_dir, f"{r}_comment.txt"), 'w', encoding='utf-8') as f:
                f.write(comment)
            
            if r % 50 == 0:
                print(f"진화 연산 진행률: {r}/{self.latest_round}...")
        print("검증 완료.")

    def predict_next(self):
        next_round = self.latest_round + 1
        prediction, comment = self.analyze_and_predict(next_round)
        
        print("\n" + "="*60)
        print(f"다음 {next_round}회차 [Chaos & Quantum] 예측 결과")
        print("="*60)
        print(comment)
        
        with open(os.path.join(self.star_dir, f"{next_round}_star.lotto"), 'w', encoding='utf-8') as f:
            json.dump({"round": next_round, "predicted_numbers": prediction}, f, indent=4, ensure_ascii=False)
            
        with open(os.path.join(self.star_dir, f"{next_round}_comment.txt"), 'w', encoding='utf-8') as f:
            f.write(comment)
        
        return prediction

if __name__ == "__main__":
    generator = StarNumberGenerator()
    generator.run_verification()
    generator.predict_next()
