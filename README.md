# aftertaxi-vnext

세후 DCA 레버리지 ETF 백테스트 엔진 — FX-only 재설계.

## 현재 위상: Architecture Lab + Partial Engine

기존 [aftertaxi](https://github.com/dldbwns888/aftertaxi) (`v3.1.0-freeze`)의 구조를 재설계한 실험장.
**기존 엔진의 완전한 대체품이 아님.** 세금 edge case parity가 아직 부족하다.

### 할 수 있는 것
- FX-only 코어: C/O + FULL rebalance, TAXABLE + ISA, AVGCOST
- 계좌 제약: annual_cap (연간 납입 한도), allowed_assets (허용 자산 필터)
- 세금 버킷 분리: 양도세 / 배당세 / 건보료(MVP) 항목별 추적
- 거래비용, 배당(원천징수+재투자), EventJournal
- ResultAttribution: 세후 결과 원인 분해
- Lane A: 실제 ETF + FX (Alpha Vantage + FRED 추천, yfinance/EODHD/FMP도 지원)
  - dual-path: ADJUSTED (배당 반영 가격) vs EXPLICIT_DIVIDENDS (배당 분리)
- Lane B: 합성 레버리지 역사 + A/B overlap calibration
- Lane C: Block Bootstrap Monte Carlo (provenance + joblib 병렬화)
- MarketDB: SQLite 멀티소스 통합 데이터베이스
- 워크벤치: 전략 비교 React UI + JSON adapter

### 아직 못 하는 것
- BAND/BUDGET 리밸, 복잡한 이월결손금 만료
- 전략 compile 파이프라인 (GUI/AI용)
- Lane D (execution realism)
- 종합과세 누진구간 완전체 (현재 고정 세율 MVP)
- 건보료 parity (현재 배당소득 기반 MVP, 이자소득 미포함)

### 계약 필드 구현 상태

구현 완료:
- `AccountConfig.annual_cap` — 연간 납입 한도 (cap 초과분 skip)
- `AccountConfig.allowed_assets` — 허용 자산만 매수

미구현 (설정 시 예외):
- `RebalanceMode.BUDGET` → `NotImplementedError`
- `lot_method != "AVGCOST"` → `NotImplementedError`

## 구조

```
src/aftertaxi/
  core/
    contracts.py          — typed 입출력 계약 + 세금 불변식
    facade.py             — run_backtest() 단일 진입점 + 미구현 설정 검증
    runner.py             — 월 루프 + C/O + FULL + 집계
    settlement.py         — 정산 순서 (account + person scope)
    ledger.py             — FX-only 계좌 원장
    tax_engine.py         — 순수 세금 계산 (양도세 + ISA + 배당세 + 건보료)
    dividend.py           — 배당 이벤트 모델
    event_journal.py      — opt-in 이벤트 로그
    attribution.py        — ResultAttribution (세후 결과 원인 분해)
    workbench_adapter.py  — 엔진→워크벤치 JSON 직렬화
  lanes/
    lane_a/
      loader.py           — yfinance + AV/FMP explicit dividend 로더
      data_contract.py    — PriceMode enum, LaneAData, validate()
      compare.py          — adjusted vs explicit 비교 harness
    lane_b/               — 합성 장기역사
    lane_c/
      bootstrap.py        — Circular Block Bootstrap + PathProvenance
      run.py              — 병렬 실행(joblib) + DistributionReport
  loaders/
    alphavantage.py       — Alpha Vantage (close/adj/div 분리, 26년+ 무료)
    fred.py               — FRED FX (DEXKOUS, 30년+ 무료)
    eodhd.py              — EODHD (close/adj 분리, 배당 상세)
    fmp.py                — FMP (close/adj/div, 30년+)
    market_db.py          — SQLite 멀티소스 통합 DB
```

## 세금 불변식

```
gross_pv_krw == gross_pv_usd × reporting_fx_rate
net_pv_krw   == gross_pv_krw − tax_unpaid_krw
assessed     == paid + unpaid
```

## 세금 버킷

```
settle_annual_tax      → _capital_gains_tax_assessed_krw
settle_dividend_tax    → _dividend_tax_assessed_krw
apply_health_insurance → _health_insurance_assessed_krw
(총합: _total_tax_assessed_krw)
```

## 건보료 MVP

- 근사 대상: 직장가입자 보수 외 소득월액보험료 (투자소득 부분)
- 법적 근거: 시행령 제41조 — 양도소득은 소득월액 산정 대상 아님
- 포함: 배당소득. 제외: 양도소득
- 기준: 연 2천만원 초과. 세율: 6.99%. 상한: 연 4천만원
- ⚠ person-scope premium을 첫 TAXABLE 계좌에 귀속 (MVP 한계)

## 데이터 소스

| 소스 | close (배당 미반영) | adjusted | 배당 | 무료 이력 |
|---|---|---|---|---|
| Alpha Vantage | ✅ | ✅ | 월별 금액 | 26년+ |
| FMP | ✅ | ✅ | 상세 (ex/pay/record) | 30년+ |
| EODHD | ✅ | ✅ | 상세 | 1년 |
| yfinance | ⚠ 배당 반영 | — | per-share | 무제한 |
| FRED | — | — | — | FX 30년+ |

⚠ yfinance v1.2의 Close는 배당이 반영된 adjusted close (4소스 교차 비교로 확인).
EXPLICIT_DIVIDENDS 경로에는 AV/FMP close를 사용해야 이중 계산 방지.

## 테스트

```bash
# 전체 (기존 엔진 + yfinance + API 키 필요)
PYTHONPATH=/path/to/aftertaxi:src python -m pytest tests/ -q

# 코어만 (외부 의존 없음)
python -m pytest tests/test_contracts.py tests/test_unsupported_config.py -v
```

242 tests, ~35초.
