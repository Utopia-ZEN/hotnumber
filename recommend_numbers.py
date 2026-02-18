import random
from collections import Counter
from itertools import combinations
from analyze_pattern import LottoAnalyzer

class LottoRecommender:
    def __init__(self):
        self.latest_round = self._get_latest_round()
        # 전체 데이터 로드 (1회부터 최신회차까지)
        self.analyzer = LottoAnalyzer(1, self.latest_round)
        self.all_data = self.analyzer.data
        # 최근 30회차 데이터 (최신 트렌드 분석용)
        self.recent_data = self.analyzer.data[-30:] if len(self.analyzer.data) >= 30 else self.analyzer.data

    def _get_latest_round(self):
        try:
            with open('lotto_data/latest.lotto', 'r') as f:
                return int(f.read().strip())
        except:
            return 1000 # 기본값

    def _get_hot_numbers(self, data_source):
        """주어진 데이터 소스에서 번호별 출현 빈도를 반환"""
        nums = [n for d in data_source for n in d['numbers']]
        return Counter(nums)

    def _get_cold_numbers(self, num_rounds=15):
        """최근 N회차 동안 나오지 않은 번호 반환"""
        recent_subset = self.analyzer.data[-num_rounds:]
        recent_nums = set(n for d in recent_subset for n in d['numbers'])
        all_nums = set(range(1, 46))
        return list(all_nums - recent_nums)

    def _get_pair_weights(self, data_source):
        """가장 자주 함께 나온 번호 쌍(궁합수) 빈도 반환"""
        pair_counts = Counter()
        for d in data_source:
            nums = sorted(d['numbers'])
            for pair in combinations(nums, 2):
                pair_counts[pair] += 1
        return pair_counts

    def _generate_weighted_set(self, weights):
        """가중치를 기반으로 6개 번호 생성"""
        numbers = list(weights.keys())
        probs = list(weights.values())
        
        selected = set()
        while len(selected) < 6:
            pick = random.choices(numbers, weights=probs, k=1)[0]
            selected.add(pick)
        return sorted(list(selected))

    def _generate_pair_based_set(self, pair_weights):
        """상위 궁합수를 포함한 번호 조합 생성"""
        # 상위 100개 페어 중 하나를 랜덤 선택하여 시작
        top_pairs = pair_weights.most_common(100)
        if not top_pairs:
            return self._generate_weighted_set({i:1 for i in range(1,46)})
            
        start_pair = random.choice(top_pairs)[0]
        selected = set(start_pair)
        
        # 나머지는 전체 빈도 가중치로 채움
        total_counts = self._get_hot_numbers(self.all_data)
        weights = {n: total_counts.get(n, 0) for n in range(1, 46)}
        
        while len(selected) < 6:
            pick = random.choices(list(weights.keys()), weights=list(weights.values()), k=1)[0]
            selected.add(pick)
            
        return sorted(list(selected))

    def _check_filters(self, numbers):
        """생성된 번호 조합이 로또 통계적 필터를 통과하는지 검사"""
        sorted_nums = sorted(numbers)
        
        # 1. 총합 필터 (일반적으로 100~200 사이가 가장 많음)
        s = sum(numbers)
        if not (100 <= s <= 200): return False
        
        # 2. 홀짝 비율 (0:6 또는 6:0 제외)
        odds = sum(1 for n in numbers if n % 2 != 0)
        if odds == 0 or odds == 6: return False
        
        # 3. 고저 비율 (1~22: 저, 23~45: 고) - 0:6 또는 6:0 제외
        highs = sum(1 for n in numbers if n >= 23)
        if highs == 0 or highs == 6: return False

        # 4. 3연번 제외 (예: 1, 2, 3)
        for i in range(len(sorted_nums)-2):
            if sorted_nums[i+1] == sorted_nums[i]+1 and sorted_nums[i+2] == sorted_nums[i]+2:
                return False
        
        # 5. AC값 (산술적 복잡도) >= 7 (대부분의 당첨번호는 7 이상)
        diffs = set()
        for i in range(6):
            for j in range(i+1, 6):
                diffs.add(sorted_nums[j] - sorted_nums[i])
        ac = len(diffs) - 5
        if ac < 7: return False

        return True

    def recommend(self):
        recommendations = []
        
        # [전략 1] 최근 트렌드(Hot) 중심 - 5조합
        hot_counts = self._get_hot_numbers(self.recent_data)
        weights_hot = {n: 1 + hot_counts.get(n, 0) for n in range(1, 46)}
        
        count = 0
        while count < 5:
            nums = self._generate_weighted_set(weights_hot)
            if self._check_filters(nums):
                recommendations.append(("최근 트렌드(Hot)", nums))
                count += 1

        # [전략 2] 미출현(Cold) 번호 공략 - 5조합
        cold_nums = self._get_cold_numbers(15)
        weights_cold = {n: 10 if n in cold_nums else 1 for n in range(1, 46)}
        
        count = 0
        while count < 5:
            nums = self._generate_weighted_set(weights_cold)
            if self._check_filters(nums):
                recommendations.append(("미출현 번호(Cold)", nums))
                count += 1

        # [전략 3] 전체 통계 기반 균형 - 5조합
        total_counts = self._get_hot_numbers(self.all_data)
        weights_total = {n: total_counts.get(n, 0) for n in range(1, 46)}
        
        count = 0
        while count < 5:
            nums = self._generate_weighted_set(weights_total)
            if self._check_filters(nums):
                recommendations.append(("전체 통계 균형", nums))
                count += 1

        # [전략 4] 동반 출현(Pair) 궁합수 - 5조합
        pair_weights = self._get_pair_weights(self.all_data)
        
        count = 0
        while count < 5:
            nums = self._generate_pair_based_set(pair_weights)
            if self._check_filters(nums):
                recommendations.append(("동반 출현(Pair)", nums))
                count += 1
                    
        return recommendations

if __name__ == "__main__":
    print("로또 번호 분석 및 추천 시스템을 시작합니다...")
    rec = LottoRecommender()
    results = rec.recommend()
    
    print(f"\n[{rec.latest_round + 1}회차 대비 추천 번호 20선]")
    print("="*75)
    print(f"{'No.':<4} {'전략':<15} {'추천 번호':<30} {'총합':<5} {'홀:짝'}")
    print("-" * 75)
    
    for i, (desc, nums) in enumerate(results, 1):
        s = sum(nums)
        odds = sum(1 for n in nums if n % 2 != 0)
        evens = 6 - odds
        ratio = f"{odds}:{evens}"
        nums_str = ", ".join(map(str, nums))
        print(f"{i:02d}.  {desc:<15} [{nums_str:<25}] {s:<5} {ratio}")
    print("="*75)
