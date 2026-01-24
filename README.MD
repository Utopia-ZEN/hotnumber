# 로또 6/45 당첨번호 크롤러 및 분석기 (Hotnumber)

이 프로젝트는 동행복권(dhlottery.co.kr) 사이트에서 로또 6/45 당첨 결과를 수집하고, 당첨 번호에 대한 고급 분석 데이터를 생성하여 JSON 형태로 저장하는 도구입니다.

GitHub Actions를 통해 매주 자동으로 최신 회차 정보를 업데이트하도록 구성되어 있습니다.

## 📋 주요 기능

1.  **데이터 크롤링**:
    *   Selenium을 사용하여 동적 웹페이지(JavaScript)에서 데이터를 정확하게 수집합니다.
    *   1회부터 최신 회차까지의 모든 당첨 정보를 수집합니다.
    *   이미 저장된 데이터가 있다면, **새로 추가된 회차만** 자동으로 감지하여 업데이트합니다.

2.  **고급 분석 데이터 생성**:
    단순 당첨 번호 외에 분석에 필요한 지표를 자동으로 계산하여 저장합니다.
    *   **홀짝 비율 (Odd/Even Ratio)**: 홀수와 짝수의 비율 (예: 4:2)
    *   **총합 (Sum)**: 당첨 번호 6개의 합계
    *   **AC값 (Arithmetic Complexity)**: 번호 간 차이의 다양성을 나타내는 산술적 복잡도 지표
    *   **고저 비율 (High/Low Ratio)**: 저번호(1~22)와 고번호(23~45)의 비율

3.  **통계 데이터 (Frequency)**:
    *   전체 회차를 분석하여 각 번호별 출현 빈도(기본 당첨, 보너스 당첨, 총합)와 순위 정보를 `frequency.lotto`에 저장합니다.

4.  **자동 업데이트**:
    *   GitHub Actions를 통해 매주 일요일(추첨 직후) 자동으로 스크립트가 실행되어 저장소를 최신 상태로 유지합니다.

## 📂 데이터 구조

모든 데이터는 `lotto_data/` 디렉토리에 저장됩니다.

### 1. 회차별 데이터 (`{회차}.lotto`)
각 회차의 정보는 JSON 형식으로 저장됩니다.

```json
{
    "round": 1207,
    "numbers": [10, 22, 24, 27, 38, 45],
    "bonus": 11,
    "winners": 17,
    "amount_per_winner": 1733202949,
    "analysis": {
        "odd_even_ratio": "2:4",
        "sum_value": 166,
        "ac_value": 8,
        "high_low_ratio": "4:2"
    }
}
```

### 2. 빈도 데이터 (`frequency.lotto`)
전체 회차에 대한 번호별 통계입니다.

```json
{
    "stats": {
        "1": { "main": 150, "bonus": 20, "total": 170 },
        ...
    },
    "ranking": [
        { "number": 34, "counts": { "main": 160, "bonus": 25, "total": 185 } },
        ...
    ],
    "total_rounds": 1207
}
```

### 3. 최신 회차 정보 (`latest.lotto`)
현재 저장된 가장 최신 회차 번호가 텍스트로 저장됩니다.

## 🚀 설치 및 사용 방법

### 필수 요구 사항
*   Python 3.9 이상
*   Chrome 브라우저 (Selenium 구동용)

### 설치

1.  저장소 클론
    ```bash
    git clone https://github.com/your-username/hotnumber.git
    cd hotnumber
    ```

2.  라이브러리 설치
    ```bash
    pip install -r requirements.txt
    ```

### 실행

```bash
python crawler.py
```
*   **초기 실행 시**: 1회부터 최신 회차까지 모든 데이터를 수집합니다.
*   **이후 실행 시**: 마지막으로 저장된 회차 이후의 새로운 데이터만 수집하여 추가합니다.
*   실행이 완료되면 `lotto_data/` 폴더 내의 파일들과 `frequency.lotto`이 갱신됩니다.

## 🤖 GitHub Actions 자동화

이 저장소는 `.github/workflows/update_lotto.yml` 설정에 의해 자동화되어 있습니다.

*   **일정**: 매주 일요일 00:00 UTC (한국 시간 오전 9시)
*   **동작**:
    1.  환경 설정 및 의존성 설치
    2.  `crawler.py` 실행 (신규 회차 크롤링)
    3.  변경된 데이터(`lotto_data/`)를 감지하여 자동으로 Commit & Push

따라서 별도의 수동 조작 없이도 저장소의 데이터는 항상 최신 상태로 유지됩니다.
