import os
import json
import time
import re
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

# Configuration
DATA_DIR = 'lotto_data'
TARGET_URL = 'https://www.dhlottery.co.kr/lt645/result'
LATEST_FILE = 'latest.lotto'
FREQUENCY_FILE = 'frequency.lotto'

def ensure_data_dir():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

def get_latest_round_and_setup_driver():
    options = Options()
    options.add_argument('--headless')  # Run in background
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    try:
        driver.get(TARGET_URL)
        # Wait for the select element to be present
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "srchStrLtEpsd"))
        )
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        select_tag = soup.find('select', id='srchStrLtEpsd')
        
        latest_round = 0
        if select_tag:
            for option in select_tag.find_all('option'):
                val = option.get('value')
                if val and val.isdigit():
                    latest_round = int(val)
                    break # Assuming first one is latest
                    
        return latest_round, driver
    except Exception as e:
        print(f"Error initializing driver or fetching latest round: {e}")
        if driver:
            driver.quit()
        return 0, None

def get_saved_rounds():
    saved = []
    if not os.path.exists(DATA_DIR):
        return saved
    for filename in os.listdir(DATA_DIR):
        if filename.endswith('.lotto') and filename != LATEST_FILE:
            try:
                round_num = int(filename.split('.')[0])
                saved.append(round_num)
            except ValueError:
                pass
    return sorted(saved)

def parse_money(money_str):
    clean = re.sub(r'[^\d]', '', money_str)
    return int(clean) if clean else 0

def parse_winners(winner_str):
    clean = re.sub(r'[^\d]', '', winner_str)
    return int(clean) if clean else 0

def calculate_analysis_data(numbers, bonus):
    """
    Calculate advanced analysis metrics:
    - odd_even_ratio: Ratio of odd to even numbers (e.g., "4:2")
    - sum_value: Sum of the 6 main numbers
    - ac_value: Arithmetic Complexity value
    - high_low_ratio: Ratio of high (23-45) to low (1-22) numbers
    """
    # Odd/Even
    odds = sum(1 for n in numbers if n % 2 != 0)
    evens = 6 - odds
    odd_even_ratio = f"{odds}:{evens}"
    
    # Sum
    sum_value = sum(numbers)
    
    # AC Value (Arithmetic Complexity)
    diffs = set()
    sorted_nums = sorted(numbers)
    for i in range(len(sorted_nums)):
        for j in range(i + 1, len(sorted_nums)):
            diffs.add(sorted_nums[j] - sorted_nums[i])
    ac_value = len(diffs) - 5
    
    # High/Low (Low: 1-22, High: 23-45)
    highs = sum(1 for n in numbers if n >= 23)
    lows = 6 - highs
    high_low_ratio = f"{highs}:{lows}"
    
    return {
        'odd_even_ratio': odd_even_ratio,
        'sum_value': sum_value,
        'ac_value': ac_value,
        'high_low_ratio': high_low_ratio
    }

def fetch_range_with_selenium(driver, start_round, end_round):
    print(f"Fetching rounds {start_round} to {end_round}...")
    try:
        driver.execute_script(f"""
            document.getElementById('srchStrLtEpsd').value = '{start_round}';
            document.getElementById('srchEndLtEpsd').value = '{end_round}';
            document.getElementById('btnWnNoPop').click();
        """)
        
        time.sleep(2)
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        results = []
        container = soup.find('div', id='tableMoDiv')
        if not container:
            print("Could not find result container (tableMoDiv)")
            return []
            
        items = container.find_all('div', class_='mo-table-list')
        
        for item in items:
            try:
                round_wrap = item.find('div', class_='round-wrap')
                if not round_wrap: continue
                
                spans = round_wrap.find_all('span')
                round_text = spans[0].text
                round_num = int(re.search(r'\d+', round_text).group())
                
                ball_boxes = item.find_all('div', class_='result-ballBox')
                if len(ball_boxes) < 2:
                    continue
                    
                win_balls = ball_boxes[0].find_all('div', class_='result-ball')
                numbers = [int(b.text) for b in win_balls]
                
                bonus_ball = ball_boxes[1].find('div', class_='result-ball')
                bonus = int(bonus_ball.text) if bonus_ball else 0
                
                winners_text = spans[2].text
                winners = parse_winners(winners_text)
                
                price_span = item.find('span', class_='txt-price')
                amount = parse_money(price_span.text)
                
                # Calculate analysis data
                analysis = calculate_analysis_data(numbers, bonus)
                
                results.append({
                    'round': round_num,
                    'numbers': numbers,
                    'bonus': bonus,
                    'winners': winners,
                    'amount_per_winner': amount,
                    'analysis': analysis
                })
                
            except Exception as e:
                print(f"Error parsing item: {e}")
                continue
                
        return results
    except Exception as e:
        print(f"Error in selenium fetch: {e}")
        return []

def save_result(result):
    filename = os.path.join(DATA_DIR, f"{result['round']}.lotto")
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=4)
    print(f"Saved {filename}")

def save_latest_round_number(round_num):
    filename = os.path.join(DATA_DIR, LATEST_FILE)
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(str(round_num))
    print(f"Updated {filename} with round {round_num}")

def update_existing_files_with_analysis():
    print("Checking and updating existing files with analysis data...")
    if not os.path.exists(DATA_DIR):
        return

    updated_count = 0
    for filename in os.listdir(DATA_DIR):
        if filename.endswith('.lotto') and filename != LATEST_FILE:
            filepath = os.path.join(DATA_DIR, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Check if analysis data is missing
                if 'analysis' not in data:
                    numbers = data.get('numbers', [])
                    bonus = data.get('bonus', 0)
                    
                    if numbers:
                        data['analysis'] = calculate_analysis_data(numbers, bonus)
                        
                        with open(filepath, 'w', encoding='utf-8') as f:
                            json.dump(data, f, ensure_ascii=False, indent=4)
                        updated_count += 1
            except Exception as e:
                print(f"Error updating {filename}: {e}")
    
    if updated_count > 0:
        print(f"Updated {updated_count} files with analysis data.")
    else:
        print("All existing files already have analysis data.")

def update_frequency_data():
    print("Updating frequency data...")
    # Initialize frequency map for numbers 1 to 45
    frequency = {str(i): {'main': 0, 'bonus': 0, 'total': 0} for i in range(1, 46)}
    
    if not os.path.exists(DATA_DIR):
        return

    count = 0
    for filename in os.listdir(DATA_DIR):
        if filename.endswith('.lotto') and filename != LATEST_FILE:
            try:
                with open(os.path.join(DATA_DIR, filename), 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    numbers = data.get('numbers', [])
                    bonus = data.get('bonus', 0)
                    
                    for num in numbers:
                        if 1 <= num <= 45:
                            frequency[str(num)]['main'] += 1
                            frequency[str(num)]['total'] += 1
                    
                    if 1 <= bonus <= 45:
                        frequency[str(bonus)]['bonus'] += 1
                        frequency[str(bonus)]['total'] += 1
                    count += 1
            except Exception as e:
                print(f"Error reading {filename}: {e}")

    # Sort by total frequency descending for convenience
    sorted_by_total = sorted(frequency.items(), key=lambda x: x[1]['total'], reverse=True)
    
    output_data = {
        'stats': frequency,
        'ranking': [{'number': int(k), 'counts': v} for k, v in sorted_by_total],
        'total_rounds': count
    }

    freq_file = os.path.join(DATA_DIR, FREQUENCY_FILE)
    with open(freq_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=4)
    
    print(f"Frequency data updated based on {count} rounds. Saved to {freq_file}")

def main():
    ensure_data_dir()
    
    # First, update any existing files that might be missing analysis data
    update_existing_files_with_analysis()
    
    print("Initializing Selenium...")
    latest_round, driver = get_latest_round_and_setup_driver()
    
    if not driver:
        print("Failed to initialize driver.")
        return

    try:
        print(f"Latest round on site: {latest_round}")
        
        if latest_round > 0:
            save_latest_round_number(latest_round)
        
        saved_rounds = get_saved_rounds()
        last_saved = saved_rounds[-1] if saved_rounds else 0
        print(f"Last saved round: {last_saved}")
        
        if latest_round > last_saved:
            start = last_saved + 1
            end = latest_round
            
            chunk_size = 10
            for i in range(start, end + 1, chunk_size):
                chunk_end = min(i + chunk_size - 1, end)
                results = fetch_range_with_selenium(driver, i, chunk_end)
                
                for result in results:
                    save_result(result)
        else:
            print("Already up to date.")
            
        # Always update frequency data at the end
        update_frequency_data()
            
    finally:
        driver.quit()

if __name__ == '__main__':
    main()
