# aftertaxi-vnext

세후 DCA 레버리지 ETF 백테스트 엔진 — FX-only 재설계.

## 현재 위상: Primary-candidate Engine

기존 [aftertaxi](https://github.com/dldbwns888/aftertaxi) (`v3.1.0-freeze`)를 구조적으로 대체하는 차세대 엔진.
코어 잠금(oracle shadow 8/8 통과) + 기능 승계(strategies, validation) 완료.

**아직 완전한 대체품은 아님**: BAND/BUDGET 리밸, PENSION, 종합과세 누진, Lane D 미구현.

### 5개 축

| 축 | 역할 | 모듈 |
|---|---|---|
| **코어 엔진** | 돈 상태 변경 + 세금 계산 + 정산 | core/ |
| **데이터 레이어** | 질문별 검증 프레임 | lanes/, loaders/ |
| **해석 레이어** | "왜 이런 결과?" | attribution, workbench_adapter |
| **검증 레이어** | "이 전략이 진짜?" | validation/ (15+ 도구) |
| **전략 레이어** | 입력 → 실행 파이프라인 | strategies/ |

### 할 수 있는 것
- FX-only 코어: C/O + FULL, TAXABLE + ISA, AVGCOST
- 계좌 제약: annual_cap, allowed_assets, priority-based allocation
- 세금 버킷: 양도세 / 배당세 / 건보료(MVP) 항목별 추적
- PersonSummary: person-scope liability 분리 (계좌 귀속 왜곡 방지)
- 거래비용, 배당(원천징수+재투자), EventJournal
- Lane A: 실제 ETF + FX (Alpha Vantage/FMP + FRED, dual-path)
- Lane B: 합성 장기역사 (2-mode: Overlap + Structural)
- Lane C: Block Bootstrap Monte Carlo (provenance + joblib 병렬화)
- validation/: DSR, PSR, Bootstrap, Permutation, CUSUM, Rolling Sharpe, Walk-Forward, IS-OOS, CPCV, PBO, 랜덤 시장 생존
- strategies/: registry (7종 빌더) + compile (JSON → BacktestConfig)
- MarketDB: SQLite 멀티소스 통합 (AV, FMP, EODHD, yfinance, FRED)

### 아직 못 하는 것
- BAND/BUDGET 리밸 → `NotImplementedError`
- PENSION 계좌 → `NotImplementedError`
- FIFO/HIFO lot method → `NotImplementedError`
- 종합과세 누진구간 (현재 고정 세율)
- Lane D (execution realism)
- workbench 실연결 (현재 mock)

## 실행 파이프라인

```
JSON / dict / GUI
    ↓
strategies/compile.py
    ↓
BacktestConfig (typed)
    ↓
facade.run_backtest()
    ↓
runner → settlement → ledger → tax_engine
    ↓
EngineResult + PersonSummary
    ↓
attribution / validation / workbench
```

## 구조

```
src/aftertaxi/
  core/
    contracts.py          — typed 계약 + 불변식 + 프리셋 + 팩토리
    facade.py             — run_backtest() + 미구현 설정 검증
    runner.py             — 월 루프 + allocation
    settlement.py         — 정산 순서 (account + person scope)
    ledger.py             — FX-only 계좌 원장
    allocation.py         — AllocationPlanner (priority + cap + allowed)
    tax_engine.py         — 순수 세금 계산
    dividend.py           — 배당 이벤트
    attribution.py        — 세후 결과 원인 분해
    event_journal.py      — opt-in 이벤트 로그
    workbench_adapter.py  — JSON 직렬화
  strategies/
    registry.py           — @register + build + build_from_dict
    spec.py               — StrategySpec (메타데이터 포함)
    builders.py           — 7종 내장 전략
    compile.py            — JSON/dict → BacktestConfig
  lanes/
    lane_a/               — 실제 ETF + FX, dual-path (adjusted/explicit)
    lane_b/               — 합성 장기역사, 2-mode (overlap/structural)
    lane_c/               — Bootstrap MC + provenance
  loaders/
    alphavantage.py, fred.py, eodhd.py, fmp.py, market_db.py
  validation/
    basic.py              — 5개 검산 (tax drag, MDD, PV 등)
    statistical.py        — 5개 통계 (DSR, PSR, Bootstrap, Permutation, CUSUM)
    stability.py          — 3개 안정성 (Rolling Sharpe, Walk-Forward, IS-OOS)
    robustness.py         — 2개 강건성 (CPCV, PBO)
    stress.py             — 랜덤 시장 생존 (vector sign-flip null)
    reports.py, run.py    — typed 리포트 + 통합 실행
```

## 세금 불변식

```
gross_pv_krw == gross_pv_usd × reporting_fx_rate
net_pv_krw   == gross_pv_krw − tax_unpaid_krw
assessed     == paid + unpaid
```

## 코어 안정성 근거

- Oracle shadow 8개 시나리오 21 tests 전부 통과 (기존 엔진 대비)
- Characterization golden 20개 (손계산 대조 포함)
- Settlement 직접 테스트 12개
- Validation 15+ 도구
- 코어 경계 가이드 (`docs/core_boundary_guide.md`)

## 테스트

```bash
PYTHONPATH=/path/to/aftertaxi:src python -m pytest tests/ -q
```

313+ tests, ~36초 (API 의존 테스트 제외).

## 문서

- `docs/oracle_shadow_classification.md` — 기존 엔진 테스트 481개 3분류
- `docs/core_boundary_guide.md` — 기능별 수정 가이드
