# Repository Python File Guide

## 1. 전체 구조 요약

이 저장소는 **한국 거주자의 해외 ETF 적립식(DCA) 세후 백테스트 엔진**이다. 양도세 22%, ISA 비과세/분리과세, 누진세, 이월결손금, 건보료, 배당 원천징수를 반영하여 "세후로 진짜 얼마 남는가?"를 계산한다.

### 주요 레이어와 책임

```
app/gui, app/cli     사용자 입출력
    ↓
apps/service.py      유스케이스 조립 (compile→run→attribution→advisor→memory)
    ↓
strategies/          전략 정의 + payload→BacktestConfig 컴파일
    ↓
core/                엔진 (facade→runner→ledger→settlement→tax_engine)
    ↓
analysis/            결과 해석 (attribution, compare, sweep, ISA최적화, KRW분해, 세금해석)
validation/          검증 (DSR, PSR, CUSUM, bootstrap, walk-forward)
lanes/               데이터 품질 검증 (Lane A~D)
    ↓
experiments/         실행 기록 + 데이터 fingerprint
loaders/             외부 데이터 소스 어댑터
```

### 데이터→실행→분석→검증 흐름

```
JSON payload
  → compile (strategies/compile.py)
  → BacktestConfig
  → run_backtest (core/facade.py → core/runner.py)
  → EngineResult
  → build_attribution (core/attribution.py)
  → ResultAttribution
  → Advisor 2.0 / validation / ISA최적화 / KRW분해
  → RunOutput / ValidatedRunOutput
```

---

## 2. 디렉토리별 개요

### `core/` — 엔진 (계산의 본체)
- **목적:** 세후 DCA 백테스트 실행. 상태를 가진 ledger, 월 루프 runner, 세금 계산.
- **대표 파일:** `facade.py` (진입점), `runner.py` (월 루프), `contracts.py` (타입 계약)
- **다른 디렉토리와의 관계:** 아래로만 의존(numpy/pandas). 위에서 facade.py만 호출.

### `strategies/` — 전략 정의 + 컴파일
- **목적:** JSON payload를 BacktestConfig로 변환. 전략 메타데이터 관리.
- **대표 파일:** `compile.py`, `metadata.py`, `builders.py`
- **관계:** core/contracts.py에 의존. apps/에서 호출.

### `advisor/` — 진단 + 제안 + 종합 판단
- **목적:** EngineResult를 받아 "이 전략 써도 되냐?" 판단.
- **대표 파일:** `advisor_v2.py` (종합), `rules.py` (MVP 규칙), `types.py`
- **관계:** core 결과를 소비만 함. analysis/ 결과도 종합.

### `analysis/` — 결과 해석 (workbench에서 리네임)
- **목적:** 엔진 결과를 다양한 관점에서 해석. 비교, sweep, ISA최적화, KRW분해, 세금해석.
- **대표 파일:** `isa_optimizer.py`, `krw_attribution.py`, `tax_interpretation.py`, `sweep.py`
- **관계:** core 결과를 소비. 엔진을 수정하지 않음.

### `apps/` — 앱 진입점
- **목적:** CLI, GUI, 서비스 레이어. 사용자와 엔진을 연결.
- **대표 파일:** `service.py` (단일 조립점), `cli.py`, `gui/streamlit_app.py`
- **관계:** service.py가 compile/engine/analysis/advisor/memory를 조립.

### `validation/` — 통계 검증
- **목적:** 전략 결과가 통계적으로 유의한지 검증.
- **대표 파일:** `statistical.py` (DSR/PSR), `basic.py`, `reports.py`
- **관계:** EngineResult를 입력으로 받음.

### `lanes/` — 데이터 품질 + 생존성 검증
- **목적:** Lane A(실데이터), B(합성비교), C(부트스트랩), D(장기생존).
- **대표 파일:** `lane_d/synthetic.py`, `lane_a/loader.py`
- **관계:** core 엔진을 재사용. 독립적 실험 프레임.

### `experiments/` — 연구 재현성 인프라
- **목적:** 실행 기록, 데이터 fingerprint.
- **대표 파일:** `memory.py`, `fingerprint.py`
- **관계:** apps/service.py가 기록 저장 시 사용.

### `loaders/` — 외부 데이터 어댑터
- **목적:** yfinance, Alpha Vantage, EODHD, FMP, FRED, Shiller 등.
- **대표 파일:** 소스별 로더.
- **관계:** apps/data_provider.py가 통합 호출.

### `intent/` — 사용자 의도 타입
- **목적:** 자연어 → 구조화 의도 (미래 확장용).
- **대표 파일:** `types.py`, `plan.py`
- **관계:** compile에서 CompileTrace 생성.

### `workbench/` — **DEPRECATED** (analysis/로 이동)
- **목적:** 하위호환 re-export 껍데기.

---

## 3. 파일별 설명

### core/

#### `core/contracts.py`
- **역할:** 엔진 입출력 타입 계약. 프로젝트 전체의 타입 기둥.
- **왜 존재하는가:** 모든 모듈이 공유하는 타입을 한 곳에 고정. dict 금지 철학.
- **핵심 클래스:**
  - `AccountType`: TAXABLE | ISA enum
  - `RebalanceMode`: CONTRIBUTION_ONLY | FULL | BAND
  - `TaxConfig`: 세율, 공제, 누진 구간
  - `AccountConfig`: 계좌별 설정 (monthly, cap, rebalance)
  - `StrategyConfig`: 전략명 + 자산 비중
  - `BacktestConfig`: 계좌 + 전략 + 기간 통합 설정
  - `EngineResult`: 최종 결과 (불변식 검증 포함)
  - `TaxSummary`: assessed/paid/unpaid 일관성 검증
  - `AccountSummary`: 계좌별 결과
  - `PersonSummary`: person-scope 세금 (건보료)
  - `KOREA_PROGRESSIVE_BRACKETS`: 누진세 8구간
- **의존성:** dataclasses, enum, numpy, typing만
- **수정 시 주의:** 필드 추가/제거는 전체 프로젝트에 영향. golden baseline 테스트로 검증 필수.
- **관련 파일:** 거의 전부.

#### `core/facade.py`
- **역할:** 엔진 공개 API 단일 진입점.
- **핵심 함수:** `run_backtest(config, returns, prices, fx_rates) → EngineResult`
- **왜 존재하는가:** 외부에서 runner/ledger/settlement를 직접 만지지 않게.
- **주의:** BUDGET/FIFO/PENSION은 NotImplementedError. 의도적 거부.
- **관련:** runner.py, contracts.py

#### `core/runner.py`
- **역할:** 월 루프 실행기. 엔진의 심장.
- **핵심 함수:**
  - `run_engine()`: 전체 루프
  - `_step_mark_to_market()`: 1. 시가 평가
  - `_step_year_boundary()`: 2. 연도 전환 + 세금 정산 + annual_tax_history 수집
  - `_step_dividends()`: 3. 배당
  - `_step_deposit_and_rebalance()`: 4. 적립 + 리밸런싱
  - `_step_record()`: 5. 월별 기록
  - `_aggregate()`: 전 계좌 통합 → EngineResult
  - `_execute_contribution_only()`, `_execute_full_rebalance()`: 리밸 정책
  - `_drift_exceeds_threshold()`: BAND 판정
- **수정 시 주의:** golden baseline이 깨질 수 있음. 정책 추가는 step 함수로만.
- **관련:** ledger.py, settlement.py, allocation.py

#### `core/ledger.py`
- **역할:** 계좌 원장. 현금, 포지션, 세금 상태를 관리하는 상태 객체.
- **핵심 클래스:** `AccountLedger`
- **핵심 메서드:** `deposit()`, `buy()`, `sell()`, `liquidate()`, `mark_to_market()`, `apply_dividend()`, `settle_annual_tax()`, `get_cgt_inputs()`, `apply_cgt_result()`
- **수정 시 주의:** 상태 변경은 원자적이어야. deposit()은 cash+annual_usd+annual_krw를 한 번에.
- **관련:** runner.py, settlement.py, tax_engine.py

#### `core/settlement.py`
- **역할:** 정산 순서 캡슐화. 세금 계산 중재자.
- **핵심 함수:** `settle_year_end()`, `settle_final()`
- **패턴:** get → compute → apply. ledger에서 입력 꺼내고, tax_engine으로 계산하고, ledger에 결과 적용.
- **관련:** ledger.py, tax_engine.py

#### `core/tax_engine.py`
- **역할:** 세금 계산 순수 함수. 상태 없음.
- **핵심 함수:**
  - `compute_capital_gains_tax()`: 양도세 22% + 공제 + 이월결손금 + 누진
  - `compute_isa_settlement()`: ISA 비과세 ₩200만 + 초과분 9.9%
  - `compute_dividend_tax()`: 배당 종합과세
  - `compute_health_insurance()`: 건보료
  - `_compute_progressive_tax()`: 누진세 8구간
- **수정 시 주의:** tax_golden 15개 테스트로 검증. 법 조항 기반 수기 계산과 대조.
- **관련:** settlement.py, contracts.py

#### `core/allocation.py`
- **역할:** 자금 배분. priority 기반 계좌 배분.
- **핵심 클래스:** `AllocationPlanner`
- **원칙:** ledger를 직접 수정하지 않고 의도(AccountOrder)만 반환.
- **관련:** runner.py

#### `core/attribution.py`
- **역할:** 세후 결과 원인 분해 (사후 계산).
- **핵심 함수:** `build_attribution(result) → ResultAttribution`
- **관련:** service.py, advisor/

#### `core/dividend.py`
- **역할:** 배당 이벤트 모델. DividendSchedule로 분기/반기 배당 생성.
- **관련:** runner.py

#### `core/event_journal.py`
- **역할:** 이벤트 로그. buy/sell/deposit/tax_assessed 등 기록.
- **관련:** ledger.py (내부에서 호출)

#### `core/workbench_adapter.py`
- **역할:** EngineResult → JSON 직렬화 (GUI/CLI용).
- **관련:** analysis/__init__.py

### strategies/

#### `strategies/compile.py`
- **역할:** JSON payload → BacktestConfig 변환. 프로젝트의 입력 게이트.
- **핵심 함수:**
  - `compile_backtest(payload, strict=False)`: 전체 컴파일
  - `compile_account()`: 계좌 dict → AccountConfig (strict mode 지원)
  - `compile_strategy()`: 전략 dict → StrategyConfig
  - `compile_backtest_with_trace()`: compile + CompileTrace 생성
  - `apply_suggestion_patch()`: Advisor 제안을 payload에 안전 적용
  - `_merge_tax_config()`: preset + user override merge
- **수정 시 주의:** 자동 보정(monthly 기본값 등)은 warning 발행. strict=True면 에러.
- **관련:** metadata.py, builders.py, contracts.py

#### `strategies/metadata.py`
- **역할:** 전략 메타데이터 등록소. GUI 폼 자동 생성.
- **핵심:** `_REGISTRY` dict. `get_metadata()`, `list_metadata()`.
- **관련:** builders.py, GUI

#### `strategies/builders.py`
- **역할:** 내장 전략 빌더 함수 7개.
- **핵심:** `build_q60s40()`, `build_spy_bnh()`, `build_custom()` 등.
- **관련:** spec.py, metadata.py

#### `strategies/spec.py`
- **역할:** StrategySpec dataclass.
- **관련:** builders.py

#### `strategies/registry.py`
- **역할:** StrategyRegistry 클래스 (미래 확장용).
- **관련:** metadata.py

### advisor/

#### `advisor/advisor_v2.py`
- **역할:** 종합 판단기. KRW attribution + 세금 해석 + ISA최적화 + validation을 하나로.
- **핵심 함수:** `build_advisor_v2()` → `AdvisorV2Report` (grade: strong/mixed/fragile)
- **관련:** service.py (run_validated_strategy에서 자동 호출)

#### `advisor/rules.py`
- **역할:** MVP 규칙 엔진. 5개 진단 + max 3 제안.
- **핵심:** `run_advisor(inp) → AdvisorReport`
- **규칙:** HIGH_TAX_DRAG, NO_ISA, EXTREME_MDD, PROGRESSIVE_NOT_MODELED, LOW_SURVIVAL
- **관련:** types.py, builder.py

#### `advisor/builder.py`
- **역할:** EngineResult → AdvisorInput 정제. raw data 접근 차단.
- **핵심:** `build_advisor_input()`. multi-account aware (has_band_account, all_contribution_only).
- **관련:** types.py, rules.py

#### `advisor/types.py`
- **역할:** Advisor 타입 정의.
- **핵심:** `AdvisorInput`, `Diagnosis`, `SuggestionPatch` (priority + dedup), `AdvisorReport`

### analysis/ (구 workbench/)

#### `analysis/__init__.py`
- **역할:** workbench 실행 파이프라인. `run_workbench()`, `run_workbench_json()`.
- **관련:** CLI --json 출력

#### `analysis/isa_optimizer.py`
- **역할:** ISA 비중별 세후 결과 비교 → 최적점.
- **핵심:** `optimize_isa()` → `ISAOptResult`
- **관련:** service.py (validated run에서 자동 호출)

#### `analysis/krw_attribution.py`
- **역할:** 자산 성과 / 환율 효과 / 세금 손실 KRW 분해.
- **핵심:** `build_krw_attribution()` → `KrwAttributionReport`. 검산: invested+asset+fx-tax=net.
- **관련:** advisor_v2.py

#### `analysis/tax_interpretation.py`
- **역할:** "세금이 왜 이렇게 나왔는가?" 자동 해석.
- **핵심:** `interpret_tax_structure()` → `TaxStructureReport` (findings + opportunities).
- **관련:** advisor_v2.py

#### `analysis/compare.py`
- **역할:** 멀티 전략 비교 리포트 + 통계 검정.
- **핵심:** `compare_strategies()` → `ComparisonReport`. rank_table, pairwise t-test/Wilcoxon.

#### `analysis/sweep.py`
- **역할:** 파라미터 그리드 서치.
- **핵심:** `run_sweep(SweepConfig, ...)` → `SweepResult`. 자동 비중 정규화.

#### `analysis/analytics.py`
- **역할:** 자산별 기여 분해 + underwater (drawdown) 분석.
- **핵심:** `build_asset_contribution()`, `build_underwater()`.

#### `analysis/sensitivity.py`
- **역할:** 성장률×변동성 민감도 히트맵.
- **핵심:** `run_sensitivity()` → `SensitivityGrid`.

#### `analysis/tax_savings.py`
- **역할:** ISA 혼합 시 절세 시뮬레이션.
- **핵심:** `simulate_tax_savings()` → `TaxSavingsReport`.

#### `analysis/interpret.py`
- **역할:** 결과 해석 텍스트 자동 생성.
- **핵심:** `interpret_result()`, `interpret_comparison()`.

#### `analysis/goal_calc.py`
- **역할:** 목표 금액 역산 계산기.
- **핵심:** `find_monthly_for_goal()` → `GoalCalcResult`.

#### `analysis/export.py`
- **역할:** CSV/XLSX 내보내기.
- **핵심:** `to_csv()`, `to_excel()`, `to_csv_multi()`, `to_excel_multi()`.

### apps/

#### `apps/service.py`
- **역할:** 앱 서비스 레이어. 앱↔코어 중간 계층.
- **핵심 함수:**
  - `run_strategy()` → `RunOutput` (compile+run+attribution+baseline+advisor+memory)
  - `run_validated_strategy()` → `ValidatedRunOutput` (+ validation + Advisor 2.0)
  - `compare_strategies()` → `CompareOutput`
- **핵심 DTO:** `RunOutput` (typed, provenance 포함), `ValidatedRunOutput` (advisor_v2 포함)
- **수정 시 주의:** GUI/CLI 모두 이 파일 경유. 시그니처 변경은 양쪽 영향.

#### `apps/cli.py`
- **역할:** CLI 백테스트 실행기.
- **핵심:** `main()` → argparse + service.run_strategy(). `--compare`, `--lane-d`, `--sensitivity`, `--watch`, `--history`, `replay:` 지원.
- **수정 시 주의:** 과비대화 경고. subcommand 분리 후보.

#### `apps/gui/streamlit_app.py`
- **역할:** Streamlit 연구 대시보드. 초보자/고급 모드.
- **핵심:** `main()`. 전략 빌더 wizard, baseline비교, Advisor카드, analytics차트.
- **의존성:** streamlit, service.py
- **수정 시 주의:** 605줄. 렌더 함수들이 많음. 분리 후보.

#### `apps/gui/draft_models.py`
- **역할:** GUI 입력 초안 모델. JSON↔StrategyDraft/AccountDraft/BacktestDraft.
- **관련:** streamlit_app.py

#### `apps/data_provider.py`
- **역할:** 앱용 데이터 공급자. synthetic/yfinance/yfinance_fx 통합.
- **핵심:** `load_market_data()` → `MarketData`.
- **관련:** cli.py, streamlit_app.py

#### `apps/data_cache.py`
- **역할:** 데이터 캐시 (SQLite + pickle).

#### `apps/memory.py` — **RE-EXPORT** → experiments/memory.py
#### `apps/data_fingerprint.py` — **RE-EXPORT** → experiments/fingerprint.py

### experiments/

#### `experiments/memory.py`
- **역할:** SQLite 기반 실험 기록.
- **핵심:** `ResearchMemory.record()`, `.list_runs()`, `.get()`. data_fingerprint/source 저장.

#### `experiments/fingerprint.py`
- **역할:** 데이터 출처 추적.
- **핵심:** `compute_fingerprint()` → sha256[:12]. `DataProvenance` (source, assets, date_range, notes).

### intent/

#### `intent/types.py`
- **역할:** 사용자 의도 타입 (미래 자연어 입력 대비).
- **핵심:** `StrategyIntent`, `AccountIntent`, `FullIntent`.

#### `intent/plan.py`
- **역할:** 분석 계획 + 컴파일 추적.
- **핵심:** `CompileTrace`, `CompileDecision`, `AnalysisPlan`.

### validation/

#### `validation/__init__.py`
- **역할:** 검증 단일 진입점.
- **핵심:** `validate()` → `ValidationReport`.

#### `validation/basic.py`
- 5개 기본 검산: tax_drag, mdd_range, pretax≥posttax, invested_positive, pv_nonnegative.

#### `validation/statistical.py`
- DSR, PSR, bootstrap_sharpe, permutation, CUSUM.

#### `validation/stability.py`
- rolling_sharpe, walk_forward, IS/OOS decay.

#### `validation/robustness.py`
- CPCV, PBO (Probability of Backtest Overfitting).

#### `validation/stress.py`
- 랜덤 시장 생존 테스트 (sign-flip, bootstrap).

#### `validation/reports.py`
- `Grade` enum (PASS/WARN/FAIL), `CheckResult`, `ValidationReport`.

#### `validation/run.py`
- `run_validation_suite()` 오케스트레이터.

### lanes/

#### `lanes/lane_a/` — 실제 ETF 데이터 검증
- `loader.py`: yfinance + FX + 배당 로드
- `data_contract.py`: PriceMode enum, LaneAData
- `compare.py`: adjusted vs explicit dividend 비교
- `run.py`: Lane A 편의 실행

#### `lanes/lane_b/` — 합성 레버리지 비교
- `synthetic.py`: 합성 레버리지 수익률 생성
- `run.py`: Lane B + overlap calibration

#### `lanes/lane_c/` — 부트스트랩 분포
- `bootstrap.py`: Circular Block Bootstrap
- `run.py`: 분포 리포트 + 병렬화

#### `lanes/lane_d/` — 장기 생존 시뮬레이션
- `synthetic.py`: sign-flip + HMM regime 합성 경로
- `run.py`: 생존률 계산
- `compare.py`: DCA vs Lump Sum 비교
- `haircut.py`: 실행 마찰 모델

### loaders/
- `alphavantage.py`, `eodhd.py`, `fmp.py`, `fred.py`: 외부 API 데이터 로더
- `market_db.py`: 멀티소스 통합 DB
- `shiller.py`: 152년 장기 데이터

### workbench/ — **DEPRECATED**
모든 파일이 `analysis/` 동명 파일의 re-export. DeprecationWarning 발행.

---

## 4. 테스트 파일 맵

### 🔴 Golden (엔진 변경 감지)
| 테스트 | 대상 | 성격 |
|---|---|---|
| `test_golden_baseline.py` (4) | 전체 엔진 | seed=42 결과 스냅샷 |
| `test_tax_golden.py` (15) | tax_engine | 법 조항 기반 3자 대조 |
| `test_oracle_shadow.py` (8) | 전체 엔진 | 기존 aftertaxi 대비 동일성 |
| `test_characterization.py` (5) | ledger+settlement | 수기 계산 대조 |

### 🟡 Contract (계약 검증)
| 테스트 | 대상 |
|---|---|
| `test_compile_strict.py` (4) | compile strict mode |
| `test_compile_merge.py` (11) | 세금 preset merge |
| `test_apply_patch.py` (9) | Advisor patch 안전성 |
| `test_cross_feature.py` (9) | BAND+누진, 이월+만료 교차 |
| `test_deposit_ownership.py` (5) | deposit 원자성 |
| `test_contracts.py` | TaxSummary/EngineResult 불변식 |
| `test_bug_report.py` (6) | 버그 리포트 회귀 |

### 🟢 Unit/Integration (기능)
| 테스트 | 대상 |
|---|---|
| `test_allocation.py` | AllocationPlanner |
| `test_attribution.py` | build_attribution |
| `test_band_rebalance.py` | BAND 리밸런싱 |
| `test_settlement.py` | settle_year_end/settle_final |
| `test_tax_engine.py` | 세금 순수 함수 |
| `test_progressive_tax.py` | 누진세 8구간 |
| `test_dividend.py` | 배당 이벤트 |
| `test_health_insurance.py` | 건보료 |
| `test_transaction_cost.py` | 거래비용 + EventJournal |
| `test_compile.py` | compile 전체 |
| `test_strategies.py` | registry + builders |
| `test_validation.py` | DSR/PSR/basic |
| `test_compare.py` | 멀티 전략 비교 |
| `test_sweep.py` | 파라미터 sweep |
| `test_analytics.py` | 자산 기여 + underwater |
| `test_isa_optimizer.py` | ISA 최적화 |
| `test_intent_advisor.py` | Intent + Advisor 타입 |
| `test_memory.py` | Research Memory |
| `test_export.py` | CSV/XLSX 내보내기 |
| `test_cli.py` | CLI 실행 |
| `test_gui_infra.py` | GUI draft models |
| `test_data_provider.py` | 데이터 공급자 |
| `test_data_cache.py` | 데이터 캐시 |
| `test_lane_*.py` | Lane A~D 전부 |
| `test_hmm_regime.py` | HMM 합성 경로 |
| `test_stress.py` | 랜덤 생존 |
| `test_sensitivity_and_watch.py` | 민감도 히트맵 |
| `test_interpret_and_savings.py` | 해석 + ISA 절세 |
| `test_workbench_*.py` | workbench 파이프라인 |
| `test_phase0_bugfixes.py` | 초기 버그 회귀 |
| `test_bugfix_review.py` | 코드 리뷰 버그 |
| `test_unsupported_config.py` | 미지원 설정 거부 |
| `test_warnings_and_goal.py` | 경고 + 목표 역산 |

### helpers.py
- `make_engine_result()`: 테스트용 EngineResult 팩토리.

---

## 5. 핵심 진입점

| 진입점 | 용도 | 파일 |
|---|---|---|
| `run_strategy()` | 기본 실행 (앱용) | `apps/service.py` |
| `run_validated_strategy()` | 검증+Advisor 2.0 | `apps/service.py` |
| `run_backtest()` | 엔진 직접 호출 | `core/facade.py` |
| `compile_backtest()` | payload→config | `strategies/compile.py` |
| `aftertaxi config.json` | CLI | `apps/cli.py` |
| `streamlit run ...` | GUI | `apps/gui/streamlit_app.py` |

---

## 6. 리팩터링 관점 메모

### 파일 책임이 큰 곳
- **`apps/gui/streamlit_app.py` (605줄):** 렌더 함수 10개가 한 파일. `gui/renderers.py` 분리 후보.
- **`apps/cli.py` (335줄):** 실행+compare+lane-d+sensitivity+watch+history. subcommand 분리 후보.
- **`core/runner.py`:** step 함수 5개 + 정책 함수 3개. 현재는 관리 가능 수준.

### 경계가 애매한 곳
- **`analysis/__init__.py`:** workbench 파이프라인이 그대로 들어가 있음. service.py와 역할 중복 가능.
- **`apps/data_provider.py`:** data/ 폴더로 이동 후보.

### Future cleanup 후보
- `workbench/` 전체: deprecated re-export. 다음 breaking release에서 제거.
- 테스트 `sys.path.insert`: 대부분 제거됨. oracle_shadow만 정당한 legacy 잔여.
- `apps/data_cache.py` + `apps/data_provider.py`: `data/` 폴더로 통합 후보.
- `intent/types.py`: 현재 compile에서 직접 사용하지 않음. 미래 자연어 입력 대비.

---

## 7. 누락 검사

- **전체 .py 파일 수 (src/ + tests/):** 155
- **root .py 파일 (start_aftertaxi.py):** 1
- **총 .py 파일:** 156
- **문서화한 파일:** 96 운영 + 59 테스트 + 1 root = 156
- **`__init__.py` (빈 파일):** 16개 (core, advisor, analysis, apps, gui, experiments, intent, lanes×5, loaders, strategies, validation, workbench, tests, src) — 패키지 마커. 빈 파일이거나 re-export.
- **누락 파일:** 없음
