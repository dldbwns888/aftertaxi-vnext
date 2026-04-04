# aftertaxi-vnext 설계도 1~5
# ================================
# 원칙: 숫자 안 바꾸는 구조 개선 + 연구 생산성 도구.
# 코어는 건드리되 의미론은 건드리지 않는다.


# ════════════════════════════════════════════════════
# 1. EXPERIMENT REGISTRY
# ════════════════════════════════════════════════════
#
# 목적: "이 결과가 어떤 config + 어떤 데이터에서 나왔는지" 추적.
#        6개월 뒤 "지난번 Q60S40 결과 다시 봐야지" 할 때 재현 가능.
#
# 위치: apps/registry.py (코어 밖)
#
# 핵심 개념:
#   Run = config_snapshot + data_fingerprint + result_summary + timestamp
#
# ── 데이터 모델 ──
#
# @dataclass
# class RunRecord:
#     run_id: str              # uuid4 또는 짧은 hash
#     timestamp: str           # ISO 8601
#     config_json: str         # BacktestDraft.to_json() 그대로
#     config_hash: str         # sha256(config_json)[:12]
#     data_fingerprint: str    # sha256(returns.values.tobytes())[:12]
#     result_summary: dict     # {gross_pv_usd, net_pv_krw, tax_assessed, mdd, n_months}
#     tags: List[str]          # 사용자 태그 ["q60s40", "progressive", "v1.2"]
#     git_commit: Optional[str]  # 현재 HEAD hash (있으면)
#
# ── 저장소 ──
#
# SQLite. ~/.aftertaxi/registry.db
# 테이블: runs (run_id PK, 나머지 컬럼)
#
# class ExperimentRegistry:
#     def __init__(self, db_path=~/.aftertaxi/registry.db): ...
#     def record(self, config, data, result, tags=[]) -> RunRecord: ...
#     def list_runs(self, limit=20, tag=None) -> List[RunRecord]: ...
#     def get_run(self, run_id) -> RunRecord: ...
#     def compare(self, run_id_a, run_id_b) -> dict: ...  # config diff + result diff
#     def find_by_config(self, config_hash) -> List[RunRecord]: ...
#
# ── facade 연결 ──
#
# facade.run_backtest()에 optional registry 파라미터:
#
#   result = run_backtest(config, returns, prices, fx_rates,
#                         registry=registry, tags=["q60s40"])
#   # → 자동으로 registry.record() 호출
#
# ── CLI 연결 ──
#
#   aftertaxi config.json                  # 실행 + 자동 기록
#   aftertaxi history                      # 최근 20개 run 목록
#   aftertaxi history --tag q60s40         # 태그 필터
#   aftertaxi show <run_id>                # 상세 보기
#   aftertaxi diff <run_a> <run_b>         # config diff + 결과 diff
#   aftertaxi replay <run_id>              # config 재실행
#
# ── 코어 영향 ──
#
# 없음. registry는 facade 위에 얹는 optional layer.
# facade.py에 if registry: registry.record(...) 한 줄.
#
# ── 파일 ──
#
#   NEW apps/registry.py          ~ 150줄
#   MOD apps/cli.py               + history/show/diff/replay 서브커맨드
#   MOD core/facade.py            + optional registry 파라미터 (1줄)
#   NEW tests/test_registry.py    ~ 80줄
#
# ── 의존성 ──
#
# sqlite3 (stdlib). 추가 패키지 없음.


# ════════════════════════════════════════════════════
# 2. RUNNER 분해 + SETTLEMENT 정리 (PR C + D 합본)
# ════════════════════════════════════════════════════
#
# 목적: run_engine() 379줄 God Function → 의미 단위 함수 추출.
#        ledger lazy import 제거 → settlement가 세금 계산 중재.
#
# ── 현재 run_engine() 구조 ──
#
#   계좌 생성 (57~69)
#   planner 생성 (77~79)
#   월 루프 (81~155):
#     1. mark_to_market
#     2. 연도 전환 → settle_year_end
#     2.5. 배당
#     3-4. deposit + allocation + rebalance
#     5. 월말 기록
#   최종 청산 (156~165)
#   결과 집계 (166~)
#
# ── 목표 구조 ──
#
# @dataclass
# class StepContext:
#     """매 월 공유되는 실행 문맥."""
#     step: int
#     dt: pd.Timestamp
#     fx_rate: float
#     price_map: Dict[str, float]
#     current_year: int
#
# def run_engine(config, prices, fx_rates, journal=None):
#     runtime = _init_runtime(config, prices, fx_rates, journal)
#
#     for step in range(runtime.n_steps):
#         ctx = runtime.build_context(step)
#
#         _step_mark_to_market(ctx, runtime.ledgers)
#         _step_year_boundary(ctx, runtime)       # settle + 리셋
#         _step_dividends(ctx, runtime)
#         _step_deposit_and_rebalance(ctx, runtime)
#         _step_record(ctx, runtime)
#
#     _finalize(runtime)
#     return _aggregate(runtime)
#
# ── Runtime 객체 ──
#
# @dataclass
# class EngineRuntime:
#     config: BacktestConfig
#     ledgers: Dict[str, AccountLedger]
#     planner: AllocationPlanner
#     fx_lookup: tuple
#     prices: pd.DataFrame
#     index: pd.DatetimeIndex
#     n_steps: int
#     start: int
#     current_year: Optional[int]
#     monthly_values: list
#
#     def build_context(self, step: int) -> StepContext: ...
#
# ── 각 step 함수 ──
#
# def _step_mark_to_market(ctx, ledgers):
#     for ledger in ledgers.values():
#         ledger.mark_to_market(ctx.price_map)
#
# def _step_year_boundary(ctx, runtime):
#     if runtime.current_year is not None and ctx.dt.year != runtime.current_year:
#         settle_year_end(runtime.ledgers, runtime.current_year, ctx.fx_rate, ...)
#         for ledger in runtime.ledgers.values():
#             ledger.annual_contribution_usd = 0.0
#             ledger.annual_contribution_krw = 0.0
#         runtime.current_year = ctx.dt.year
#
# def _step_dividends(ctx, runtime):
#     schedule = runtime.config.dividend_schedule
#     if schedule is None or not schedule.is_dividend_month(ctx.step):
#         return
#     for ledger in runtime.ledgers.values():
#         for asset in list(ledger.positions.keys()):
#             event = schedule.create_event(asset, ctx.price_map.get(asset, 0))
#             if event is not None:
#                 ledger.apply_dividend(...)
#
# def _step_deposit_and_rebalance(ctx, runtime):
#     ytd = {id: l.annual_contribution_krw for id, l in runtime.ledgers.items()}
#     orders = runtime.planner.plan(..., ytd_contributions=ytd, fx_rate=ctx.fx_rate)
#     for order in orders:
#         ledger = runtime.ledgers[order.account_id]
#         if order.deposit > 0:
#             ledger.deposit(order.deposit, ctx.fx_rate)
#         _execute_order(ledger, order, ctx)
#
# def _step_record(ctx, runtime):
#     total_usd = sum(l.total_value_usd() for l in runtime.ledgers.values())
#     runtime.monthly_values.append(total_usd)
#     for ledger in runtime.ledgers.values():
#         ledger.record_month()
#
# ── settlement 정리 (PR D) ──
#
# 현재 ledger 내부:
#   def settle_annual_tax(self, year):
#       from tax_engine import compute_capital_gains_tax  # lazy import!
#       result = compute_capital_gains_tax(...)
#       self._apply(result)
#
# 변경 후:
#   # ledger: 상태 제공 + 결과 반영만
#   def get_tax_inputs(self) -> dict:
#       return {"gain": self.annual_realized_gain_krw,
#               "loss": self.annual_realized_loss_krw,
#               "carryforward": self.loss_carryforward_krw, ...}
#
#   def apply_tax_result(self, result: CapitalGainsTaxResult):
#       self._total_tax_assessed_krw += result.tax_krw
#       self.loss_carryforward_krw = result.carryforward_remaining + result.new_loss_carry
#       self.annual_realized_gain_krw = 0.0
#       self.annual_realized_loss_krw = 0.0
#
#   # settlement: 중재자
#   def settle_year_end(ledgers, year, fx_rate, ...):
#       for ledger in ledgers.values():
#           inputs = ledger.get_tax_inputs()
#           result = compute_capital_gains_tax(**inputs, year=year,
#                       rate=ledger.tax_rate,
#                       progressive_brackets=ledger.progressive_brackets, ...)
#           ledger.apply_tax_result(result)
#
# ── 파일 ──
#
#   MOD core/runner.py       — run_engine() 분해, StepContext/Runtime 추가
#   MOD core/settlement.py   — tax 계산 중재 로직 이동
#   MOD core/ledger.py       — lazy import 제거, get_tax_inputs/apply_tax_result 추가
#   NEW tests/test_runner_steps.py  — step 함수 개별 테스트
#
# ── 검증 ──
#
# golden 3개 시나리오 숫자 완전 동일 필수.
# 기존 509+ 회귀 전부 통과.
# runner.py에서 lazy import 0개.


# ════════════════════════════════════════════════════
# 3. ANALYTICS 확장
# ════════════════════════════════════════════════════
#
# 목적: "어디서 벌고 어디서 깨졌냐" 세밀하게.
#        현재 attribution은 전체 요약. 자산별/연도별 분해 없음.
#
# ── 추가할 analytics ──
#
# a. Contribution Attribution (자산별 수익 기여)
#
# @dataclass
# class AssetContribution:
#     asset: str
#     weight_avg: float          # 평균 비중
#     return_contribution: float  # 전체 수익 중 이 자산 기여분 (USD)
#     pct_of_total: float        # % 기여
#
# def build_asset_contribution(
#     monthly_weights: pd.DataFrame,  # (T, N) 자산별 비중
#     monthly_returns: pd.DataFrame,  # (T, N) 자산별 수익률
# ) -> List[AssetContribution]:
#     # Brinson-style: contribution_i = weight_i × return_i
#     ...
#
# 데이터 소스: ledger에서 매월 position value를 이미 기록.
# monthly_values는 전체만 있지만, 자산별은 없음.
# → ledger.record_month()에 자산별 스냅샷 추가 필요.
# → 또는: 가격 × 수량으로 사후 계산 (prices + ledger positions history)
#
# 가장 싼 방법: runner에서 매월 자산별 value dict를 기록.
#   runtime.asset_values_history.append({asset: ledger.positions[asset].market_value_usd})
# 이건 runner 분해(PR C) 후에 _step_record()에 자연스럽게 붙음.
#
#
# b. Tax Decomposition Timeline (연도별 세금 분해)
#
# @dataclass
# class AnnualTaxBreakdown:
#     year: int
#     capital_gains_tax_krw: float
#     dividend_tax_krw: float
#     health_insurance_krw: float
#     total_krw: float
#     taxable_base_krw: float
#     exemption_used_krw: float
#     progressive_bracket_hit: Optional[str]  # "88M~150M (38.5%)" 등
#
# 데이터 소스: EventJournal이 이미 tax_assessed 이벤트를 연도별로 기록.
#   → journal에서 연도별 그룹화해서 추출.
#
# def build_tax_timeline(journal: EventJournal) -> List[AnnualTaxBreakdown]:
#     events = journal.get_events(event_type="tax_assessed")
#     by_year = groupby(events, key=lambda e: e.year)
#     ...
#
#
# c. Underwater Chart 데이터
#
# def build_underwater(monthly_values: np.ndarray) -> pd.DataFrame:
#     """drawdown 시리즈 + recovery 기간."""
#     peak = np.maximum.accumulate(monthly_values)
#     drawdown = monthly_values / peak - 1
#     # recovery_months: 각 drawdown에서 peak 회복까지 기간
#     ...
#     return pd.DataFrame({"drawdown": drawdown, "peak": peak})
#
# 이건 monthly_values만 있으면 되니까 코어 변경 없음.
#
#
# ── 파일 ──
#
#   NEW workbench/analytics.py     ~ 200줄 (contribution + tax timeline + underwater)
#   MOD core/attribution.py        — AssetContribution 연결 (optional)
#   NEW tests/test_analytics.py    ~ 100줄
#
# ── 코어 영향 ──
#
# 최소. journal 읽기 + monthly_values 사후 계산이 대부분.
# 자산별 contribution만 runner에 history 기록 1줄 추가 (PR C 이후).


# ════════════════════════════════════════════════════
# 4. EXAMPLES + ERROR MESSAGES
# ════════════════════════════════════════════════════
#
# 목적: 6개월 뒤 자기 자신을 위한 온보딩.
#
# ── examples/ 디렉토리 ──
#
# examples/
#   01_basic_spy.json          # SPY B&H, TAXABLE, 5년
#   02_q60s40_isa.json         # QQQ+SSO, ISA+TAXABLE, 20년
#   03_progressive_tax.json    # 누진세 비교 (progressive: true)
#   04_band_rebalance.json     # BAND 5%, 6040
#   05_lane_d_survival.json    # Lane D 생존률
#   README.md                  # 각 예제 설명 + 실행 명령어
#
# 실행:
#   aftertaxi examples/01_basic_spy.json
#   aftertaxi examples/02_q60s40_isa.json --sensitivity
#
# ── 에러 메시지 개선 ──
#
# 현재: NotImplementedError("계좌 타입 'PENSION' 미지원. 지원: ['TAXABLE', 'ISA']")
# 이미 괜찮음. 개선점:
#
# 1. compile에서 unknown strategy type:
#    현재: KeyError
#    개선: f"전략 '{key}' 없음. 사용 가능: {list_metadata()로 이름 나열}"
#
# 2. 데이터 로드 실패:
#    현재: yfinance 에러 그대로 전파
#    개선: f"'{ticker}' 데이터 로드 실패. 티커명 확인하세요. (원본: {e})"
#
# 3. 환율 미스매치:
#    현재: 조용히 잘못된 결과
#    개선: returns와 fx_rates 인덱스 길이 불일치 시 경고
#
# 4. config 파일 파싱:
#    현재: json.JSONDecodeError 그대로
#    개선: f"JSON 파싱 실패 (줄 {e.lineno}, 열 {e.colno}): {e.msg}"
#
# ── 구현 ──
#
# facade.py에 _validate_data() 추가:
#   returns/prices/fx 길이 일치 확인
#   NaN 비율 체크
#   경고 발행
#
# compile.py에 try-except 래핑:
#   strategy KeyError → 친절한 메시지
#
# cli.py에 JSON 에러 래핑:
#   JSONDecodeError → 위치 표시
#
# ── 파일 ──
#
#   NEW examples/*.json + README.md       ~ 7개 파일
#   MOD core/facade.py                    + _validate_data()
#   MOD strategies/compile.py             + 에러 메시지 개선
#   MOD apps/cli.py                       + JSON 파싱 에러 개선
#   NEW tests/test_error_messages.py      ~ 30줄


# ════════════════════════════════════════════════════
# 5. DATA CACHE HASH (결과 재현성)
# ════════════════════════════════════════════════════
#
# 목적: "이 결과가 어떤 데이터 버전에서 나왔는지" 추적.
#        experiment registry(#1)의 data_fingerprint 기반.
#
# ── 현재 data_cache.py ──
#
# SQLite 캐시. (source, ticker, interval) → DataFrame.
# max_age_hours로 stale 체크.
# 문제: 같은 ticker라도 데이터가 바뀔 수 있음 (수정주가, 배당 반영).
#
# ── 추가할 것 ──
#
# 1. data_fingerprint() 함수
#
# def data_fingerprint(returns: pd.DataFrame, fx: pd.Series) -> str:
#     """데이터 해시. sha256(returns.values + fx.values)[:12]."""
#     import hashlib
#     h = hashlib.sha256()
#     h.update(returns.values.tobytes())
#     h.update(fx.values.tobytes())
#     h.update(str(returns.index[0]).encode())
#     h.update(str(returns.index[-1]).encode())
#     return h.hexdigest()[:12]
#
# 2. MarketData에 fingerprint 필드
#
# @dataclass
# class MarketData:
#     returns: pd.DataFrame
#     prices: pd.DataFrame
#     fx: pd.Series
#     source: str
#     ...
#     fingerprint: str = ""  # 추가
#
#     def __post_init__(self):
#         if not self.fingerprint:
#             self.fingerprint = data_fingerprint(self.returns, self.fx)
#
# 3. cache에 fingerprint 저장
#
# DataCache.put()에 fingerprint 컬럼 추가.
# DataCache.get()이 반환할 때 fingerprint도 포함.
# → "같은 ticker인데 데이터 바뀌었나?" 감지 가능.
#
# 4. facade에서 fingerprint 전파
#
# run_backtest()이 MarketData를 받으면 → fingerprint를 EngineResult에 기록.
# (또는 registry가 받아서 저장)
#
# ── 파일 ──
#
#   MOD apps/data_cache.py        + fingerprint 컬럼
#   MOD apps/data_provider.py     + MarketData.fingerprint
#   NEW apps/data_fingerprint.py  ~ 20줄 (fingerprint 함수)
#   NEW tests/test_fingerprint.py ~ 30줄
#
# ── 코어 영향 ──
#
# 없음. data_provider/cache/registry 레벨만.


# ════════════════════════════════════════════════════
# 구현 순서 + 의존성
# ════════════════════════════════════════════════════
#
#   #5 data fingerprint ──→ #1 experiment registry
#        (fingerprint가 registry의 입력)
#
#   PR C runner 분해 ──→ #3 analytics
#        (자산별 history 기록이 runner 분해 후 자연스러움)
#
#   PR D settlement ──→ #3 tax timeline
#        (settlement이 세금 분해를 소유해야 timeline이 깨끗)
#
#   #4 examples는 독립. 언제든 가능.
#
# 최적 순서:
#
#   1단계: #5 fingerprint (20줄, 독립, 30분)
#   2단계: #1 registry (150줄, #5 의존, 2시간)
#   3단계: PR C runner 분해 (구조, 숫자 불변, 3시간)
#   4단계: PR D settlement (구조, lazy import 제거, 2시간)
#   5단계: #3 analytics (workbench 확장, 2시간)
#   6단계: #4 examples + errors (포장, 1시간)
#
# 총 예상: ~10시간 작업. 3~4 세션.
