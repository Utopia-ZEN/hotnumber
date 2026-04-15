import os
import json
import glob
from collections import Counter

def load_lotto_data(base_path):
    """lotto_data 폴더에서 당첨 번호 데이터를 읽어옵니다."""
    pattern = os.path.join(base_path, '**', '*.lotto')
    files = glob.glob(pattern, recursive=True)
    
    rounds_data = {}
    for file in files:
        filename = os.path.basename(file)
        # 통계 데이터 및 예측 파일 제외
        if filename in ['frequency.lotto', 'latest.lotto'] or '_star' in filename:
            continue
            
        try:
            with open(file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            r_num = data.get('round')
            nums = data.get('numbers')
            if r_num and nums:
                rounds_data[r_num] = sorted(nums)
        except Exception:
            pass
            
    return rounds_data

def analyze_correlations(base_path):
    rounds_data = load_lotto_data(base_path)
    if not rounds_data:
        print("데이터를 찾을 수 없습니다.")
        return

    sorted_rounds = sorted(rounds_data.keys())
    total_rounds = len(sorted_rounds)
    
    # 개별 출현 횟수 기록용
    stats = {
        'sum': Counter(),
        'endings': Counter(),
        'consec': Counter(),
        'carryover': Counter(),
        'combo': Counter()
    }
    
    # 연관관계 분석 기록용
    relation_when_consec = Counter()      # 연번 발생 시 동반되는 끝수 패턴
    relation_when_carryover = Counter()   # 이월수 발생 시 동반되는 총합 구간

    for i, r in enumerate(sorted_rounds):
        nums = rounds_data[r]
        
        # 1. 총합 그룹
        total_sum = sum(nums)
        if total_sum <= 100: sum_g = "총합 100 이하"
        elif total_sum <= 120: sum_g = "총합 101~120"
        elif total_sum <= 140: sum_g = "총합 121~140"
        elif total_sum <= 160: sum_g = "총합 141~160"
        elif total_sum <= 180: sum_g = "총합 161~180"
        else: sum_g = "총합 181 이상"
        
        # 2. 끝수 그룹 (동일 끝수 중복 개수 기준)
        endings = [n % 10 for n in nums]
        max_dup = max(Counter(endings).values()) if endings else 0
        if max_dup == 1: end_g = "동일끝수 없음"
        elif max_dup == 2: end_g = "동일끝수 2개(1쌍)"
        elif max_dup == 3: end_g = "동일끝수 3개"
        else: end_g = f"동일끝수 {max_dup}개"
        
        # 3. 연번 그룹
        consec_cnt = sum(1 for j in range(len(nums)-1) if nums[j+1] == nums[j] + 1)
        if consec_cnt == 0: consec_g = "연번 없음"
        elif consec_cnt == 1: consec_g = "연번 1쌍"
        else: consec_g = f"연번 {consec_cnt}쌍"
        
        # 4. 이월수 그룹
        carry_cnt = 0
        if i > 0:
            prev_nums = rounds_data[sorted_rounds[i-1]]
            carry_cnt = len(set(nums) & set(prev_nums))
        
        if carry_cnt == 0: carry_g = "이월수 없음"
        elif carry_cnt == 1: carry_g = "이월수 1개"
        else: carry_g = f"이월수 {carry_cnt}개 이상"

        # 데이터 누적
        stats['sum'][sum_g] += 1
        stats['endings'][end_g] += 1
        stats['consec'][consec_g] += 1
        stats['carryover'][carry_g] += 1
        
        # 복합 조합 키 생성
        combo_key = f"[{sum_g}] + [{end_g}] + [{consec_g}] + [{carry_g}]"
        stats['combo'][combo_key] += 1
        
        # 연관관계 누적 (조건부 데이터)
        if consec_cnt > 0:
            relation_when_consec[end_g] += 1
        if carry_cnt > 0:
            relation_when_carryover[sum_g] += 1
            
    # ------------------ 리포트 출력부 ------------------
    print("=" * 65)
    print(f"📊 로또 패턴 심층 분석 및 연관관계 리포트 (총 {total_rounds}회차 누적)")
    print("=" * 65)
    
    def print_counter(title, counter, total):
        print(f"\n[ {title} 전체 출현 빈도 ]")
        for k, v in counter.most_common():
            ratio = (v / total) * 100
            print(f" - {k} : {v}회 ({ratio:.1f}%)")

    print_counter("총합 구간", stats['sum'], total_rounds)
    print_counter("끝수 패턴", stats['endings'], total_rounds)
    print_counter("연번 유무", stats['consec'], total_rounds)
    print_counter("이월수 유무", stats['carryover'], total_rounds)

    print("\n" + "=" * 65)
    print("🔗 1. 핵심 패턴 간의 연관관계 (조건부 출현 확률)")
    print("=" * 65)
    
    consec_total = sum(relation_when_consec.values())
    print(f"\n▶ 연번이 발생한 회차(총 {consec_total}회)에서 자주 동반되는 끝수 패턴은?")
    for k, v in relation_when_consec.most_common(3):
        print(f"  - {k} : {v}회 ({(v/consec_total)*100:.1f}%)")
        
    carry_total = sum(relation_when_carryover.values())
    print(f"\n▶ 이월수가 발생한 회차(총 {carry_total}회)에서 자주 형성되는 총합 구간은?")
    for k, v in relation_when_carryover.most_common(3):
        print(f"  - {k} : {v}회 ({(v/carry_total)*100:.1f}%)")

    print("\n" + "=" * 65)
    print("🏆 2. 최다 출현 '4대 요소 복합 패턴' (Top 10)")
    print("   (총합 + 끝수 + 연번 + 이월수)")
    print("=" * 65)
    for i, (combo_str, count) in enumerate(stats['combo'].most_common(10), 1):
        ratio = (count / total_rounds) * 100
        print(f"{i}위: {combo_str}")
        print(f"      => 총 {count}회 출현 ({ratio:.1f}%)\n")
        
    print("💡 분석 완료! 가장 높은 확률을 가진 조합 패턴을 번호 선택에 참고해 보세요.")

if __name__ == "__main__":
    # 본인의 프로젝트 환경에 맞게 폴더 경로 지정
    target_dir = r"D:\PycharmProjects\hotnumber\lotto_data"
    analyze_correlations(target_dir)