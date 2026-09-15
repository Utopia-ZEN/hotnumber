# Future Inference Engine

이 엔진은 로또 번호를 보장 예측하지 않습니다. 로또 추첨은 독립 난수 사건이므로 과거 데이터가 다음 회차를 결정한다는 가정은 하지 않습니다. 대신 과거 데이터를 약한 신호로 보고, 가능한 조합을 더 정교하게 설계하기 위한 통계적 앙상블 엔진입니다.

## 포함된 추론 신호

- 베이지안 기본률: 각 번호의 출현률을 단순 빈도가 아니라 스무딩된 사후 확률로 계산합니다.
- 최근성 감쇠: 최근 30회, 80회, 180회, 전체 구간을 따로 보고 과열 신호와 장기 신호를 분리합니다.
- 미출현 간격 재출현률: 간격 구간별 과거 재출현률을 사용하며, 조건 표본이 100건 미만이면 균등 기준으로 되돌립니다.
- 페어/트리플 리프트: 관측 횟수에 따라 리프트를 축소해 소표본 연결의 과대평가를 줄입니다.
- 패턴 가능도: 합계, 홀짝, 고저, 끝수, 연번, 범위 패턴이 과거 분포에서 너무 비정상적이면 감점합니다.
- 안정성 패널티: 여러 기간에서 신호가 흔들리면 불확실성으로 보고 감점합니다.
- 기존 StarNumber 후보: 카오스 유사 구간, 번호 얽힘, 유전 알고리즘 후보를 유지해 미래 엔진 후보와 경쟁시킵니다.
- 기존 PickNumber 후보: 빈도, 최근 흐름, 페어, 트리플, 희귀성 기반 후보도 함께 경쟁시킵니다.

## 실행

```powershell
python StarNumber.py 6
python StarNumber.py 6 --engine future
python PickNumber\generate_future_numbers.py 6
```

`StarNumber.py`의 기본 엔진은 `future`입니다. `future`는 PickNumber, 기존 StarNumber, FutureInference 후보를 모두 섞어 최종 점수로 재랭킹합니다.

## 워크포워드 검증

```powershell
python StarNumber.py 5 --engine future --verify --verify-start-round 1100
```

검증은 각 목표 회차보다 이전 데이터만 사용하고, 같은 회차·같은 게임 수의 고정 균등 무작위 포트폴리오와 비교합니다. `paired_average_match_delta_95_interval`은 회차별 평균 차이의 정규근사 구간이며, 하한이 0보다 큰 경우에만 `average_match_superiority_supported=true`가 됩니다. 게임당 균등 이론 기대 적중 수 `0.8`과 최고 적중 수 비교도 함께 기록합니다.

## 출력 필드

- `future_score`: 미래 추론 앙상블에서 추가된 점수입니다.
- `posterior_score`: 번호별 사후 확률 기반 점수입니다.
- `momentum_score`: 최근 구간에서 강해진 번호 흐름입니다.
- `gap_pressure_score`: 미출현 간격 보정입니다.
- `gap_hazard_min_samples`: 조합에 적용된 간격 조건 중 가장 작은 표본 수입니다.
- `gap_hazard_mean_rate`: 조합 번호들의 조건별 평균 재출현률입니다.
- `lift_score`: 페어/트리플 연결 리프트입니다.
- `pattern_probability_score`: 과거 패턴 분포에 맞는 정도입니다.
- `stability_score`: 여러 기간에서 신호가 안정적인 정도입니다.
- `uncertainty_penalty`: 기간별 신호 변동성에 대한 감점입니다.
- `legacy_score`: 정규화 전 기존 PickNumber 점수입니다.
- `score_calibration`: 기존 점수와 추론 점수를 후보 집합 안에서 동등한 표준편차로 혼합한 방식입니다.

## 해석 원칙

점수가 높은 조합은 “당첨 가능성이 보장된다”가 아니라 “데이터 기반 설계 기준을 더 많이 만족한다”는 뜻입니다. 조합 간 겹침도 제한해 한 장 안에서 위험을 분산합니다.
