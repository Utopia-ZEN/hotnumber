import os
import json
import glob

def find_low_sum_rounds(base_path, threshold=120):
    """
    lotto_data 폴더 내의 모든 당첨 데이터를 분석하여 
    총합이 특정 수치(threshold) 이하인 회차를 찾습니다.
    """
    pattern = os.path.join(base_path, '**', '*.lotto')
    files = glob.glob(pattern, recursive=True)
    
    results = []
    
    for file in files:
        filename = os.path.basename(file)
        # 통계 데이터 및 메타 파일 제외
        if filename in ['frequency.lotto', 'latest.lotto']:
            continue
            
        try:
            with open(file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            round_num = data.get('round')
            sum_value = data.get('analysis', {}).get('sum_value')
            
            if round_num is not None and sum_value is not None:
                if sum_value <= threshold:
                    results.append((round_num, sum_value))
        except Exception:
            pass

    results.sort(key=lambda x: x[0])
    
    print(f"📊 총합 {threshold} 이하인 회차 목록 (총 {len(results)}건)")
    print("-" * 45)
    for r, s in results:
        print(f"제 {r}회차 : 총합 {s}")

if __name__ == "__main__":
    target_dir = r"D:\PycharmProjects\hotnumber\lotto_data"
    find_low_sum_rounds(target_dir, 120)