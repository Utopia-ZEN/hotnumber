import requests
from bs4 import BeautifulSoup
import re
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
})

url = "https://www.dhlottery.co.kr/pt720/result"
response = session.get(url, verify=False)
soup = BeautifulSoup(response.text, 'html.parser')

highest_candidate = 0
opt_val = soup.find('input', id='opt_val')
if opt_val:
    print(f"opt_val: {opt_val.get('value')}")
    highest_candidate = int(opt_val.get('value'))

print(f"highest_candidate: {highest_candidate}")

url2 = f"https://www.dhlottery.co.kr/gameResult.do?method=pension720&drwNo={highest_candidate}"
res2 = session.get(url2, verify=False)
res2.encoding = 'euc-kr'
soup2 = BeautifulSoup(res2.text, 'html.parser')
title_span = soup2.find('span', class_='psltEpsd')
if title_span:
    print(f"title_span: {title_span.text}")
else:
    print("no title_span")
