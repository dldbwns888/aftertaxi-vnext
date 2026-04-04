# ════════════════════════════════════════════════════════════════
# aftertaxi-vnext 최종 아키텍처
# "자연어 전략 연구 에이전트"
# ════════════════════════════════════════════════════════════════
#
# 제품 정의:
#   "코딩을 모르는 한국 거주 투자자가 자연어로 전략 아이디어를 말하면,
#    시스템이 세후 장기 적립 백테스트 + 과최적화 검증 + 약점 진단 +
#    개선 제안까지 자동으로 해주는 1인용 전략 연구 프로그램."
#
# 입력 예:
#   "매달 월급 들어오면 QQQ랑 SSO를 6:4로 사고,
#    너무 벌어졌을 때만 리밸런싱하고,
#    ISA를 먼저 채운 뒤 남는 돈은 일반계좌로 넣어줘.
#    과최적화인지도 봐줘."
#
# 출력:
#   1. 백테스트 결과 (세후 배수, MDD, 세금 분해)
#   2. "BAND 5%로 리밸. ISA 우선. TAXABLE 잔여."
#   3. 과최적화 검정 결과 (DSR/PSR/PBO 등)
#   4. 약점: "누진세 drag 40%. Bear 5개월 연속 시 MDD -65%."
#   5. 개선안: "ISA 비중 높이면 drag 14%로 완화. SPY 단일도 비교해봐."
#   6. 자동 비교 실험 3개 + 결과


# ════════════════════════════════════════════════════════════════
# Layer 0: MEMORY (실험 기록)
# ════════════════════════════════════════════════════════════════
#
# 모든 레이어의 기반. 실행 기록이 쌓여야 연구가 된다.
#
# ── 데이터 모델 ──
#
# @dataclass
# class RunRecord:
#     run_id: str                    # 짧은 hash (abc123)
#     timestamp: str                 # ISO 8601
#     source: str                    # "nl" | "json" | "gui" | "advisor"
#     intent_json: Optional[str]     # 자연어 의도 (있으면)
#     config_json: str               # BacktestConfig 직렬화
#     config_hash: str               # sha256[:12]
#     data_fingerprint: str          # sha256[:12]
#     plan_json: Optional[str]       # AnalysisPlan (있으면)
#
#     # 결과 요약 (전체 저장은 비용 큼 → 요약만)
#     gross_pv_usd: float
#     net_pv_krw: float
#     tax_assessed_krw: float
#     mdd: float
#     n_months: int
#
#     # 검증 요약
#     validation_grade: Optional[str]  # "A" ~ "F"
#     lane_d_survival: Optional[float]
#
#     # 메타
#     tags: List[str]
#     parent_run_id: Optional[str]   # advisor가 생성한 비교 실험이면 부모 ID
#     git_commit: Optional[str]
#
# ── 저장소 ──
#
# SQLite ~/.aftertaxi/memory.db
#
# class ResearchMemory:
#     def record(self, ...) -> RunRecord
#     def list_runs(self, limit, tag, source) -> List[RunRecord]
#     def get(self, run_id) -> RunRecord
#     def compare(self, id_a, id_b) -> RunDiff
#     def find_similar(self, config_hash) -> List[RunRecord]
#     def get_children(self, parent_id) -> List[RunRecord]  # advisor가 만든 실험들
#
# ── 위치 ──
#
# apps/memory.py  (~150줄)


# ════════════════════════════════════════════════════════════════
# Layer 1: INTENT (자연어 → 구조화된 의도)
# ════════════════════════════════════════════════════════════════
#
# 자연어를 BacktestConfig로 바로 바꾸지 않는다.
# 먼저 "의도"로 바꾼다. 의도는 아직 실행 불가능하다.
#
# ── 왜 Intent가 Config과 다른가 ──
#
# 사용자: "QQQ랑 SPY 중 더 강한 쪽에만 투자"
# → 이건 momentum 전략인데, lookback이 없다.
# → Config으로 바로 변환 불가. Intent로 먼저 잡고, Compile이 기본값을 채운다.
#
# 사용자: "ISA 먼저 채우고"
# → 이건 계좌 우선순위지, 금액이 아니다.
# → Intent: "ISA priority > TAXABLE"
# → Compile: ISA priority=0, TAXABLE priority=1, ISA cap=20M KRW
#
# ── 데이터 모델 ──
#
# @dataclass
# class StrategyIntent:
#     """전략 의도. 아직 실행 불가능할 수 있음."""
#     description: str                          # 원문 또는 요약
#     assets: Optional[List[str]] = None        # ["QQQ", "SSO"]
#     weights: Optional[Dict[str, float]] = None  # {"QQQ": 0.6, "SSO": 0.4}
#     strategy_type: Optional[str] = None       # "bnh" | "momentum" | "custom"
#     rebalance_hint: Optional[str] = None      # "drift_only" | "monthly" | "never"
#     leverage_ok: bool = True
#     params: Dict[str, Any] = field(default_factory=dict)
#
# @dataclass
# class AccountIntent:
#     """계좌 의도."""
#     monthly_total_usd: Optional[float] = None
#     isa_first: bool = True                    # ISA 우선 여부
#     account_types: List[str] = field(default_factory=lambda: ["ISA", "TAXABLE"])
#     progressive_tax: bool = False             # 누진세 고려
#     health_insurance: bool = False
#
# @dataclass
# class ResearchIntent:
#     """연구 요청."""
#     run_validation: bool = False
#     run_lane_d: bool = False
#     compare_baselines: bool = False           # SPY B&H 등 자동 비교
#     suggest_improvements: bool = False
#     check_overfitting: bool = False
#
# @dataclass
# class FullIntent:
#     strategy: StrategyIntent
#     account: AccountIntent
#     research: ResearchIntent
#     raw_input: str = ""                       # 원문 보존
#
# ── Parser ──
#
# Phase 2에선 규칙 기반:
#   "QQQ" → assets에 추가
#   "6:4" → weights 파싱
#   "ISA 먼저" → isa_first=True
#   "과최적화" → check_overfitting=True
#   "리밸런싱 자주 말고" → rebalance_hint="drift_only"
#
# Phase 3에선 LLM 파서:
#   Claude API로 자연어 → FullIntent JSON 변환
#   시스템 프롬프트에 FullIntent 스키마 + 예시 포함
#   파싱 실패 시 규칙 기반 fallback
#
# ── 위치 ──
#
# intent/
#   types.py        — FullIntent, StrategyIntent, AccountIntent, ResearchIntent
#   parser.py       — 규칙 기반 파서
#   nl_parser.py    — LLM 기반 파서 (Phase 3)
#   normalizer.py   — 의도 보정/기본값 채우기


# ════════════════════════════════════════════════════════════════
# Layer 2: COMPILE (의도 → 실행 가능한 설정)
# ════════════════════════════════════════════════════════════════
#
# Intent를 BacktestConfig + AnalysisPlan으로 변환.
# 이미 있는 compile.py를 확장.
#
# ── AnalysisPlan ──
#
# @dataclass
# class AnalysisPlan:
#     """실행할 분석 목록."""
#     run_backtest: bool = True
#     run_attribution: bool = True
#     run_validation: bool = False
#     validation_tests: List[str] = field(default_factory=list)  # ["dsr", "psr", "pbo"]
#     run_lane_d: bool = False
#     lane_d_paths: int = 50
#     lane_d_mode: str = "sign_flip"
#     compare_strategies: List[str] = field(default_factory=list)  # ["spy_bnh"]
#     run_sensitivity: bool = False
#     run_advisor: bool = False
#
# ── compile 흐름 ──
#
# def compile_intent(intent: FullIntent) -> Tuple[BacktestConfig, AnalysisPlan]:
#     """FullIntent → (BacktestConfig, AnalysisPlan).
#
#     1. StrategyIntent → StrategyConfig
#        - strategy_type 매칭 (metadata registry)
#        - 빈 params에 기본값 채우기
#        - assets/weights 정규화
#
#     2. AccountIntent → List[AccountConfig]
#        - isa_first → priority 배정
#        - monthly_total → ISA cap 고려 배분
#        - progressive_tax → TaxConfig merge
#
#     3. ResearchIntent → AnalysisPlan
#        - 직접 매핑
#        - compare_baselines=True → ["spy_bnh"] 자동 추가
#     """
#
# ── 보정 규칙 (normalizer) ──
#
# 1. 자산이 없으면 → ["SPY"] 기본
# 2. 비중 합 != 1 → 정규화
# 3. rebalance_hint="drift_only" → BAND 5%
# 4. rebalance_hint="never" → CONTRIBUTION_ONLY
# 5. leverage ETF + vol 경고
# 6. ISA 월 납입 > cap → 자동 분배
#
# ── 위치 ──
#
# 기존 strategies/compile.py 확장 + intent/compile_intent.py 신규


# ════════════════════════════════════════════════════════════════
# Layer 3: ENGINE (실행)
# ════════════════════════════════════════════════════════════════
#
# 이미 있다. 건드리지 않는다.
#
# facade.run_backtest() → runner → settlement → ledger → tax_engine
#
# PR C/D로 runner 분해 + settlement 정리만 하면 된다.
# 기능 추가 없음.


# ════════════════════════════════════════════════════════════════
# Layer 4: VALIDATION (검증/평가)
# ════════════════════════════════════════════════════════════════
#
# 이미 있다. 확장만.
#
# 현재: validation/ + Lane B/C/D + attribution + compare
#
# 추가할 것:
#
# ── ValidationOrchestrator ──
#
# AnalysisPlan을 받아서 필요한 검증을 순서대로 실행.
#
# class ValidationOrchestrator:
#     def execute(self, result, plan, returns, prices, fx) -> ValidationReport:
#         report = ValidationReport()
#
#         if plan.run_attribution:
#             report.attribution = build_attribution(result)
#
#         if plan.run_validation:
#             for test in plan.validation_tests:
#                 report.validation[test] = run_validation_test(test, result, returns)
#
#         if plan.run_lane_d:
#             report.lane_d = run_lane_d(returns, config, ...)
#
#         if plan.compare_strategies:
#             for baseline in plan.compare_strategies:
#                 report.comparisons[baseline] = run_comparison(result, baseline, ...)
#
#         if plan.run_sensitivity:
#             report.sensitivity = run_sensitivity(...)
#
#         return report
#
# @dataclass
# class ValidationReport:
#     attribution: Optional[ResultAttribution] = None
#     validation: Dict[str, Any] = field(default_factory=dict)
#     lane_d: Optional[LaneDReport] = None
#     comparisons: Dict[str, CompareResult] = field(default_factory=dict)
#     sensitivity: Optional[SensitivityGrid] = None
#     grade: str = ""  # 종합 등급 A~F
#
# ── 위치 ──
#
# validation/orchestrator.py  (~100줄)


# ════════════════════════════════════════════════════════════════
# Layer 5: ADVISOR (진단 + 개선 제안)
# ════════════════════════════════════════════════════════════════
#
# 이게 차별화 핵심. 두 단계로 구현.
#
# ── Phase A: 규칙 기반 Critic ──
#
# LLM 없이, 숫자 기반 규칙으로 진단 + 제안.
# 이걸 먼저 만들어야 LLM 연결해도 품질이 보장된다.
#
# @dataclass
# class Diagnosis:
#     code: str        # "HIGH_TAX_DRAG" | "LOW_SURVIVAL" | "OVERFITTING" | ...
#     severity: str    # "critical" | "warning" | "info"
#     message: str     # 한국어 설명
#     metric: float    # 관련 수치
#     threshold: float # 기준선
#
# @dataclass
# class Suggestion:
#     code: str        # "INCREASE_ISA" | "USE_BAND" | "SIMPLIFY" | ...
#     message: str     # 한국어 제안
#     auto_experiment: Optional[dict] = None  # 자동 실험 config (있으면)
#
# @dataclass
# class AdvisorReport:
#     diagnoses: List[Diagnosis]
#     suggestions: List[Suggestion]
#     auto_experiments: List[dict]  # 자동 생성된 비교 실험 configs
#     summary: str                  # 1~2문장 요약
#
# ── 진단 규칙 (20개 정도면 충분) ──
#
# def _diagnose(result, validation_report, config) -> List[Diagnosis]:
#     dx = []
#
#     # 세금
#     drag = validation_report.attribution.tax_drag_pct
#     if drag > 30:
#         dx.append(Diagnosis("HIGH_TAX_DRAG", "critical",
#                   f"세금 drag {drag:.0f}%로 수익의 1/3 이상이 세금.",
#                   drag, 30))
#     elif drag > 15:
#         dx.append(Diagnosis("MODERATE_TAX_DRAG", "warning",
#                   f"세금 drag {drag:.0f}%.", drag, 15))
#
#     # ISA 활용
#     isa_accounts = [a for a in config.accounts if a.account_type.value == "ISA"]
#     if not isa_accounts and drag > 10:
#         dx.append(Diagnosis("NO_ISA", "critical",
#                   "ISA 계좌 미사용. ISA 추가 시 세금 크게 절감 가능.", 0, 0))
#
#     # MDD
#     if result.mdd < -0.50:
#         dx.append(Diagnosis("EXTREME_MDD", "critical",
#                   f"MDD {result.mdd:.0%}. 50% 이상 하락은 심리적으로 견디기 어려움.",
#                   result.mdd, -0.50))
#
#     # Lane D 생존
#     if validation_report.lane_d and validation_report.lane_d.survival_rate < 0.5:
#         dx.append(Diagnosis("LOW_SURVIVAL", "critical",
#                   f"50년 생존률 {validation_report.lane_d.survival_rate:.0%}.",
#                   validation_report.lane_d.survival_rate, 0.5))
#
#     # 누진세
#     has_prog = any(a.tax_config.progressive_brackets for a in config.accounts)
#     if not has_prog and drag > 15:
#         dx.append(Diagnosis("PROGRESSIVE_NOT_MODELED", "warning",
#                   "누진세 미반영. 실제 drag는 더 높을 수 있음.", 0, 0))
#
#     # 과최적화
#     # (validation report에 DSR/PSR 결과가 있으면)
#     ...
#
#     return dx
#
# ── 제안 규칙 ──
#
# def _suggest(diagnoses, result, config) -> List[Suggestion]:
#     suggestions = []
#
#     codes = {d.code for d in diagnoses}
#
#     if "NO_ISA" in codes:
#         suggestions.append(Suggestion("ADD_ISA",
#             "ISA 계좌 추가 권장. 월 $1,282 이하면 세금 0 달성 가능.",
#             auto_experiment={"accounts": [
#                 {"type": "ISA", "priority": 0},
#                 {"type": "TAXABLE", "priority": 1},
#             ]}))
#
#     if "HIGH_TAX_DRAG" in codes:
#         suggestions.append(Suggestion("USE_BAND",
#             "BAND 리밸런싱으로 공제 분산 효과. 세금 ~12% 완화 가능.",
#             auto_experiment={"accounts": [
#                 {"rebalance_mode": "BAND", "band_threshold_pct": 0.05}
#             ]}))
#
#     if "EXTREME_MDD" in codes:
#         suggestions.append(Suggestion("REDUCE_LEVERAGE",
#             "레버리지 비중 축소 고려. SSO 40% → 20%로 MDD 완화.",
#             auto_experiment={"strategy": {"weights": {"QQQ": 0.8, "SSO": 0.2}}}))
#
#     # 항상: 단순 benchmark 비교
#     suggestions.append(Suggestion("COMPARE_BASELINE",
#         "SPY 100% B&H와 비교하면 이 전략의 알파를 확인할 수 있습니다.",
#         auto_experiment={"strategy": {"type": "spy_bnh"}}))
#
#     return suggestions
#
# ── Phase B: LLM Advisor ──
#
# 규칙 기반 진단 + 결과 숫자를 LLM에게 주고,
# 더 자연스러운 한국어 해석 + 창의적 개선 제안을 받는다.
#
# def advise_with_llm(result, diagnoses, suggestions, config) -> str:
#     prompt = f"""
#     당신은 한국 거주자를 위한 세후 투자 전략 연구 어드바이저입니다.
#
#     [백테스트 결과]
#     세후 배수: {result.mult_after_tax:.2f}x
#     MDD: {result.mdd:.0%}
#     세금 drag: {drag:.0f}%
#     기간: {result.n_months}개월
#
#     [진단]
#     {diagnoses_text}
#
#     [기존 제안]
#     {suggestions_text}
#
#     사용자에게 친절하고 구체적으로 설명해주세요.
#     추가로 놓친 개선점이 있으면 제안해주세요.
#     """
#     # Claude API 호출
#     ...
#
# ── 위치 ──
#
# advisor/
#   types.py          — Diagnosis, Suggestion, AdvisorReport
#   rules.py          — _diagnose(), _suggest()
#   advisor.py        — run_advisor(result, validation, config) → AdvisorReport
#   llm_advisor.py    — LLM 확장 (Phase 3)


# ════════════════════════════════════════════════════════════════
# 전체 파이프라인
# ════════════════════════════════════════════════════════════════
#
# def research(input_text: str, memory: ResearchMemory) -> ResearchResult:
#     """전체 연구 파이프라인. 자연어 → 결과 + 진단 + 제안."""
#
#     # 1. Intent
#     intent = parse_intent(input_text)        # Layer 1
#
#     # 2. Compile
#     config, plan = compile_intent(intent)    # Layer 2
#
#     # 3. Data
#     data = load_market_data(config.assets, ...)
#
#     # 4. Engine
#     result = run_backtest(config, data)      # Layer 3
#
#     # 5. Validation
#     val_report = validate(result, plan, data)  # Layer 4
#
#     # 6. Advisor
#     advisor_report = advise(result, val_report, config)  # Layer 5
#
#     # 7. Auto-experiments (advisor가 제안한 비교 실험)
#     for exp_config in advisor_report.auto_experiments:
#         merged = merge_config(config, exp_config)
#         exp_result = run_backtest(merged, data)
#         memory.record(exp_result, parent=run_id)
#
#     # 8. Memory
#     run_id = memory.record(config, data, result, val_report, advisor_report)
#
#     return ResearchResult(
#         result=result,
#         validation=val_report,
#         advisor=advisor_report,
#         run_id=run_id,
#     )


# ════════════════════════════════════════════════════════════════
# 디렉토리 구조 (최종)
# ════════════════════════════════════════════════════════════════
#
# src/aftertaxi/
#   core/               # Layer 3: 엔진 (기존, 건드리지 않음)
#     contracts.py
#     facade.py
#     runner.py
#     settlement.py
#     ledger.py
#     tax_engine.py
#     allocation.py
#     attribution.py
#     event_journal.py
#     dividend.py
#
#   strategies/          # 전략 빌더 + 메타데이터 (기존)
#     metadata.py
#     builders.py
#     compile.py
#
#   intent/              # Layer 1: 의도 파싱 (NEW)
#     types.py           # FullIntent, StrategyIntent, AccountIntent, ResearchIntent
#     parser.py          # 규칙 기반 파서
#     normalizer.py      # 의도 보정/기본값
#     nl_parser.py       # LLM 파서 (Phase 3)
#
#   validation/          # Layer 4: 검증 (기존 + orchestrator)
#     orchestrator.py    # AnalysisPlan → ValidationReport
#     ...
#
#   advisor/             # Layer 5: 진단 + 제안 (NEW)
#     types.py           # Diagnosis, Suggestion, AdvisorReport
#     rules.py           # 규칙 기반 진단/제안
#     advisor.py         # 메인 진입점
#     llm_advisor.py     # LLM 확장 (Phase 3)
#
#   lanes/               # 기존
#   loaders/             # 기존
#   workbench/           # 기존 (analytics 확장)
#
#   apps/                # 사용자 인터페이스
#     cli.py
#     memory.py          # Layer 0: 실험 기록 (NEW)
#     data_provider.py
#     data_cache.py
#     gui/
#       streamlit_app.py
#
#   pipeline.py          # research() 메인 파이프라인 (NEW)


# ════════════════════════════════════════════════════════════════
# 구현 로드맵
# ════════════════════════════════════════════════════════════════
#
# Phase 1: 코어 정비 (현재~)
#   PR C: runner 분해
#   PR D: settlement 정리
#   PR E: KRW/USD 타입
#   data fingerprint
#   → 코어가 안정되어야 위 계층이 의미 있음
#
# Phase 2: 규칙 기반 연구 프로그램 (Phase 1 직후)
#   Memory (apps/memory.py)
#   Intent types (intent/types.py)
#   AnalysisPlan + ValidationOrchestrator
#   Advisor rules (advisor/rules.py)
#   pipeline.py 초안
#   examples/ + 에러 메시지
#   → 이 시점에서 CLI: aftertaxi research "QQQ SSO 6:4 ISA 먼저"
#
# Phase 3: 자연어 연결 (Phase 2 안정 후)
#   intent/nl_parser.py (Claude API)
#   advisor/llm_advisor.py (Claude API)
#   Streamlit 대화형 UI
#   → 이 시점에서 자연어 입력 가능
#
# Phase 4: 자동 연구 루프 (Phase 3 안정 후)
#   advisor 자동 실험 생성 + 실행
#   memory 기반 "비슷한 과거 실험" 추천
#   연구 히스토리 시각화
#   → 이 시점에서 "전략 연구 에이전트" 완성
#
# 예상 기간:
#   Phase 1: 3~4세션 (설계도 1~5 소화)
#   Phase 2: 4~5세션
#   Phase 3: 2~3세션
#   Phase 4: 3~4세션
#   총: ~15세션
