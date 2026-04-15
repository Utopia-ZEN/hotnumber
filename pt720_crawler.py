import requests
from bs4 import BeautifulSoup
import json
import os
import time
from collections import Counter
import urllib3
import re

# SSL 경고 무시
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class PT720Crawler:
    def __init__(self):
        self.data_dir = "pt720_data"
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
            
        self.latest_round_file = os.path.join(self.data_dir, "latest.pt7")
        self.frequency_file = os.path.join(self.data_dir, "frequency.pt7")
        self.session = self._initialize_session()

    @staticmethod
    def _initialize_session():
        """세션을 생성하고 초기화 (웜업)"""
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
        })
        # 세션 유지를 위해 메인 페이지를 먼저 방문 (웜업)
        try:
            session.get("https://www.dhlottery.co.kr/", timeout=15, verify=False)
        except requests.exceptions.RequestException as e:
            print(f"세션 초기화 실패: {e}")
        return session

    def get_latest_round(self):
        """실제로 데이터가 존재하는 가장 최신 회차 번호 가져오기"""
        print("동행복권 서버에 연결하여 최신 회차 정보를 확인 중입니다...", flush=True)
        url = "https://www.dhlottery.co.kr/pt720/result"
        
        try:
            response = self.session.get(url, timeout=15, verify=False)
            if response.status_code != 200:
                print(f"서버 응답 오류 (Status: {response.status_code})")
                return 0
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 페이지에 명시된 가장 높은 회차 번호를 찾음
            highest_candidate = 0
            # 1. <input id="opt_val">
            latest_input = soup.find('input', id='opt_val')
            if latest_input and latest_input.get('value'):
                highest_candidate = int(latest_input['value'])
            
            # 2. 드롭다운 목록에서 더 높은 회차가 있는지 확인
            options = soup.find_all('button', class_='option-il')
            if options:
                for opt in options:
                    val = opt.get('data-value')
                    if val and int(val) > highest_candidate:
                        highest_candidate = int(val)

            if highest_candidate == 0:
                print("페이지에서 회차 정보를 찾지 못했습니다.")
                return 0
                
            print(f"웹페이지 상의 최신 회차(후보): {highest_candidate}회")
            
            # 찾은 최고 회차부터 역순으로 실제 데이터 존재 유무 검사
            for r in range(highest_candidate, highest_candidate - 10, -1): # 최근 10개만 검사
                if r <= 0: break
                print(f"최신 회차 검증 중... ({r}회)", end='\r', flush=True)
                if self.fetch_round_data(r, is_test=True):
                    print(f"\n실제 데이터가 존재하는 최신 회차: {r}회 확인 완료.", flush=True)
                    return r
                time.sleep(0.5)
            
            print("\n최근 10회차 내에서 유효한 당첨 데이터를 찾을 수 없습니다.")
            return 0

        except requests.exceptions.RequestException as e:
            print(f"최신 회차 확인 중 심각한 오류 발생: {e}")
            return 0

    def fetch_round_data(self, round_num, is_test=False):
        """특정 회차 데이터 크롤링 (v14 - 단일 세션)"""
        url = f"https://www.dhlottery.co.kr/gameResult.do?method=pension720&drwNo={round_num}"
        
        try:
            self.session.headers.update({'Referer': "https://www.dhlottery.co.kr/pt720/result"})
            response = self.session.get(url, timeout=15, verify=False)
            response.encoding = 'euc-kr'
            soup = BeautifulSoup(response.text, 'html.parser')
            
            title_span = soup.find('span', class_='psltEpsd')
            if not title_span or re.sub(r'[^0-9]', '', title_span.text) != str(round_num):
                return None

            if is_test:
                return {"round": round_num}

            date_div = soup.find('div', class_='result-date')
            draw_date = date_div.text.replace(' 추첨', '').strip() if date_div else "Unknown"

            balls_containers = soup.find_all('div', class_='result-wfBall')
            if len(balls_containers) < 2: return None

            first_prize_wrap = balls_containers[0].find('div', class_='wf720-num-list')
            if not first_prize_wrap: return None
            
            jo_el = first_prize_wrap.find('span', class_='pension-jo')
            jo = int(jo_el.text) if jo_el else 0
            
            winning_nums = [int(n.text) for n in first_prize_wrap.find_all('span', class_=re.compile(r'wf-[1-6]n'))]
            
            bonus_wrap = balls_containers[1].find('div', class_='wf720-num-list')
            if not bonus_wrap: return None
            
            bonus_nums = [int(n.text) for n in bonus_wrap.find_all('span', class_=re.compile(r'wf-[1-6]n'))]

            if len(winning_nums) != 6 or len(bonus_nums) != 6: return None
            
            def analyze_nums(nums):
                odd = sum(1 for n in nums if n % 2 != 0)
                high = sum(1 for n in nums if n >= 5)
                return {
                    "odd_even_ratio": f"{odd}:{6-odd}", "sum_value": sum(nums),
                    "high_low_ratio": f"{high}:{6-high}", "range": max(nums) - min(nums) if nums else 0
                }

            result = {
                "round": round_num, "date": draw_date, "winning_group": jo,
                "winning_numbers": winning_nums, "bonus_numbers": bonus_nums,
                "analysis": {"winning": analyze_nums(winning_nums), "bonus": analyze_nums(bonus_nums)},
                "details": [] # type: list[dict]
            }
            
            # --- 상세 당첨 정보 파싱 (v14 복구) ---
            table = soup.find('div', class_='wf720Info-tbl')
            if table:
                tbody = table.find('div', class_='tbl-tr tbody')
                if tbody:
                    ranks = tbody.find_all('div', class_='tbl-td td-rank')
                    for rank_div in ranks:
                        rank_text = rank_div.get_text(strip=True)
                        
                        condition_texts = []
                        prize_text = ""
                        winners_store = ""
                        winners_internet = ""
                        winners_total = ""

                        curr = rank_div.find_next_sibling('div', class_='tbl-td')
                        while curr:
                            # BeautifulSoup의 get 속성은 리스트를 반환할 수 있으므로, 리스트인 경우 문자열로 결합하거나 확인합니다.
                            classes = curr.get('class')
                            if isinstance(classes, list):
                                class_str = " ".join(classes)
                            else:
                                class_str = classes if classes else ""
                            
                            if 'td-rank' in class_str:
                                break

                            if 'td-info' in class_str or 'td-numWrap' in class_str:
                                condition_texts.append(curr.get_text(" ", strip=True))
                            elif 'td-money' in class_str:
                                prize_text = curr.get_text(strip=True)
                            elif 'td-store' in class_str:
                                winners_store = curr.get_text(strip=True)
                            elif 'td-internet' in class_str:
                                winners_internet = curr.get_text(strip=True)
                            elif 'td-total' in class_str:
                                winners_total = curr.get_text(strip=True)

                            curr = curr.find_next_sibling('div', class_='tbl-td')
                            
                        condition = " | ".join(filter(None, condition_texts))
                        
                        result['details'].append({ # type: ignore
                            "rank": rank_text,
                            "condition": condition,
                            "prize": prize_text,
                            "winners": {
                                "store": winners_store,
                                "internet": winners_internet,
                                "total": winners_total
                            }
                        })
            return result
        except requests.exceptions.RequestException:
            return None

    def update_data(self):
        print("연금복권 데이터 수집기(크롤러)를 시작합니다...", flush=True)
        latest_round = self.get_latest_round()
        if latest_round == 0:
            print("최신 회차 정보를 감지하지 못했습니다.")
            return

        start_round = 1
        existing_files = [int(f.split('.')[0]) for f in os.listdir(self.data_dir) if f.endswith('.pt7') and f[:-4].isdigit()]
        if existing_files:
            start_round = max(existing_files) + 1

        if start_round > latest_round:
            print("이미 모든 데이터가 최신 상태입니다.")
        else:
            print(f"\n>> {start_round}회부터 {latest_round}회까지 수집을 시작합니다.")
            for r in range(start_round, latest_round + 1):
                print(f"[{r}/{latest_round}] 데이터 수집 중...", end='\r', flush=True)
                
                data = self.fetch_round_data(r)
                if not data:
                    print(f"\n{r}회차 수집 실패. 프로세스를 중단합니다.")
                    break
                
                with open(os.path.join(self.data_dir, f"{r}.pt7"), 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
                with open(self.latest_round_file, 'w', encoding='utf-8') as f:
                    f.write(str(r))
                
                time.sleep(1.5)
            
            print(f"\n수집 완료.")

        final_latest = 0
        if os.path.exists(self.latest_round_file):
            try:
                with open(self.latest_round_file, 'r', encoding='utf-8') as f:
                    final_latest = int(f.read().strip())
            except (ValueError, IOError):
                pass
        
        if final_latest > 0:
            self.update_frequency()

    def update_frequency(self):
        print("번호 빈도 분석을 시작합니다...", flush=True)
        freq_jo, freq_win, freq_bonus, freq_all_nums = Counter(), {i: Counter() for i in range(1, 7)}, {i: Counter() for i in range(1, 7)}, Counter()
        valid_count = 0
        
        existing_files = [int(f.split('.')[0]) for f in os.listdir(self.data_dir) if f.endswith('.pt7') and f[:-4].isdigit()]
        
        for r in sorted(existing_files):
            file_path = os.path.join(self.data_dir, f"{r}.pt7")
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    jo, winning_nums, bonus_nums = data.get('winning_group'), data.get('winning_numbers', []), data.get('bonus_numbers', [])
                    if jo: freq_jo[jo] += 1
                    for i, n in enumerate(winning_nums):
                        freq_win[i+1][n] += 1
                        freq_all_nums[n] += 1
                    for i, n in enumerate(bonus_nums):
                        freq_bonus[i+1][n] += 1
                        freq_all_nums[n] += 1
                    valid_count += 1
            except (json.JSONDecodeError, KeyError):
                continue
        
        freq_data = {
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"), "analyzed_rounds": valid_count,
            "jo_frequency": dict(sorted(freq_jo.items())),
            "win_position_frequency": {str(k): dict(sorted(v.items())) for k, v in freq_win.items()},
            "bonus_position_frequency": {str(k): dict(sorted(v.items())) for k, v in freq_bonus.items()},
            "overall_number_frequency": dict(sorted(freq_all_nums.items()))
        }
        
        with open(self.frequency_file, 'w', encoding='utf-8') as f:
            json.dump(freq_data, f, ensure_ascii=False, indent=4)
        print(f"분석 보고서(frequency.pt7) 갱신 완료 (총 {valid_count}회차)")

if __name__ == "__main__":
    crawler = PT720Crawler()
    crawler.update_data()
