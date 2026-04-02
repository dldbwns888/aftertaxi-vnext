# aftertaxi-vnext

세후 DCA 레버리지 ETF 백테스트 엔진 — FX-only 재설계.

## 현재 위상: Architecture Lab + Partial Engine

기존 [aftertaxi](https://github.com/dldbwns888/aftertaxi) (`v3.1.0-freeze`)의 구조를 재설계한 실험장.
**기존 엔진의 완전한 대체품이 아님.** 세금 edge case parity가 아직 부족하다.

### 할 수 있는 것
- FX-only 코어: C/O + FULL rebalance, TAXABLE + ISA, AVGCOST
- Lane A: 실제 ETF + FX 백테스트 (yfinance)
- Lane B: 합성 레버리지 역사 + A/B overlap calibration
- Lane C: Block Bootstrap Monte Carlo 분포 (세후)
- 기존 엔진 대비 7개 시나리오 shadow match 통과

### 아직 못 하는 것
- 건보료, BAND/BUDGET 리밸, 복잡한 이월결손금 만료
- 전략 compile 파이프라인 (GUI/AI용)
- Lane D (execution realism)
- DuckDB 데이터 파이프라인

## 구조

```
src/aftertaxi/
  core/
    contracts.py    — typed 입출력 계약 + 세금 불변식 검증
    facade.py       — run_backtest() 단일 진입점
    runner.py       — 월 루프 + C/O + FULL + 정산 + 집계
    ledger.py       — FX-only 계좌 원장 (단일 클래스)
  lanes/
    lane_a/         — 실제 ETF+FX 로더 + run_lane_a()
    lane_b/         — 합성 레버리지 + overlap calibration
    lane_c/         — circular block bootstrap + 분포 리포트
```

## 세금 불변식

```
gross_pv_krw == gross_pv_usd × reporting_fx_rate
net_pv_krw   == gross_pv_krw − tax_unpaid_krw
assessed     == paid + unpaid
```

## 미구현 계약 필드

contracts.py에 정의되었지만 엔진에서 아직 사용하지 않는 것:
- `AccountConfig.annual_cap` — ISA 연간 한도 (TODO: runner에서 cap 체크)
- `AccountConfig.allowed_assets` — 자산 필터 (TODO: runner에서 필터링)
- `RebalanceMode.BUDGET` — 세금 예산 리밸 (TODO)

## 테스트

```bash
# 전체 (기존 엔진 + yfinance 필요)
PYTHONPATH=/path/to/aftertaxi:src python -m pytest tests/ -q

# 코어만 (외부 의존 없음)
python -m pytest tests/test_contracts.py -v

# Oracle shadow (기존 엔진 비교)
PYTHONPATH=/path/to/aftertaxi:src python -m pytest tests/test_oracle_shadow.py -v

# Lane C 스모크 (실데이터, ~20초)
PYTHONPATH=src python -m pytest tests/test_lane_c_smoke.py -v -s
```

## Lane C 스모크 결과 (100 paths, 20yr, Q60S40 C/O)

| 지표 | C(A) 실ETF | C(B) 합성 |
|---|---|---|
| median mult | 4.97x | 3.94x |
| 5th percentile | 1.39x | 1.35x |
| 파산확률 | 3.0% | 1.0% |
| CVaR 5% | 1.00x | 1.05x |

*C(A)는 2006~2024 성장주 슈퍼사이클 편향. C(B)는 1990~2024 합성 오차 포함.
결론서에는 둘 다 동등하게 제시.*

## 로드맵

| 완료 | 내용 |
|---|---|
| ✅ PR 1 | contracts + facade + oracle 3개 |
| ✅ PR 2 | 새 ledger + runner (C/O) |
| ✅ PR 3 | FULL rebalance + oracle 4 |
| ✅ PR 4 | Lane A loader |
| ✅ PR 5 | Lane B 합성 + A/B calibration |
| ✅ PR 6 | Lane C bootstrap distribution |
| ✅ +α | Oracle 7개 + C(A)/C(B) 스모크 |

| 남은 것 | 내용 |
|---|---|
| 🔲 | 1,000 paths 수렴 확인 → 결론서 숫자 확정 |
| 🔲 | 블록 길이 sensitivity (12/24/36) |
| 🔲 | 건보료 등 세금 parity 보강 |
| 🔲 | Lane D 설계 문서 (구현은 실투자 시점) |
| 🔲 | 전략 compile 파이프라인 (GUI 전 필수) |

## Lane 구조

| Lane | 질문 | 데이터 | 상태 |
|---|---|---|---|
| A | 현실에서 깨지나? | 실제 ETF | ✅ |
| B | 장기 이론이 서나? | 합성 152년 | ✅ |
| C | 운이 나쁘면? | Bootstrap 10,000개 | ✅ |
| D | 내가 못하면? | 실행 노이즈 | 📝 설계만 |

## 기존 레포와의 관계

- 기존 `aftertaxi`: `v3.1.0-freeze` 태그, 동결. 413 tests, 연구 결론 확정.
- vnext는 기존의 **대체품이 아니라 구조 재설계 실험장**.
- 연구 숫자를 낼 때는 양쪽 엔진을 돌려서 비교해야 함.
