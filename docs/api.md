# API Reference

## 서비스 API (앱 진입점)

```python
from aftertaxi.apps.service import (
    run_strategy,            # 기본 실행
    run_validated_strategy,  # 검증 + Advisor 2.0 포함
    compare_strategies,      # 멀티 전략 비교
)
```

### run_strategy()

```python
out = run_strategy(
    payload={"strategy": {"type": "q60s40"},
             "accounts": [{"type": "ISA", "monthly_contribution": 500}]},
    returns=returns_df,     # pd.DataFrame, index=date, columns=assets
    prices=prices_df,       # pd.DataFrame, same shape
    fx_rates=fx_series,     # pd.Series, same index
    data_source="yfinance", # "synthetic" | "yfinance" | "yfinance_fx"
    save_to_memory=True,    # 실행 기록 저장
    run_baseline=True,      # SPY B&H 자동 비교
)

# RunOutput 필드
out.result              # EngineResult
out.attribution         # ResultAttribution
out.config              # BacktestConfig
out.trace               # CompileTrace
out.advisor_report      # AdvisorReport
out.baseline_result     # EngineResult | None
out.provenance          # DataProvenance
out.run_id              # str

# 편의 프로퍼티
out.mult_after_tax      # float
out.mdd                 # float
out.tax_drag_pct        # float
out.baseline_gap        # float | None
out.data_source         # str
out.data_fingerprint    # str
```

### run_validated_strategy()

```python
vout = run_validated_strategy(
    payload=...,
    returns=..., prices=..., fx_rates=...,
    mode="decision_support",  # "research" | "decision_support"
)

vout.run                    # RunOutput
vout.validation_report      # ValidationReport
vout.advisor_v2             # AdvisorV2Report
vout.advisor_v2.overall_grade  # "strong" | "mixed" | "fragile"
vout.advisor_v2.full_text()    # 전체 판정 보고서
```

### compare_strategies()

```python
cout = compare_strategies(
    payloads=[payload1, payload2],
    labels=["Q60S40", "SPY"],
    returns=..., prices=..., fx_rates=...,
)

cout.rank_table   # [{"label", "mult_after_tax", "mdd", "tax_drag_pct"}, ...]
cout.winner       # str
```

## 분석 API

```python
from aftertaxi.analysis.isa_optimizer import optimize_isa
from aftertaxi.analysis.krw_attribution import build_krw_attribution
from aftertaxi.analysis.tax_interpretation import interpret_tax_structure
from aftertaxi.analysis.sweep import run_sweep
```

### optimize_isa()

ISA 비중별 세후 결과 비교 → 최적점.

```python
result = optimize_isa(
    strategy_payload={"type": "q60s40"},
    total_monthly=1000,
    returns=..., prices=..., fx_rates=...,
)
result.best_isa_pct      # 0.0 ~ 1.0
result.tax_savings_krw   # 절세액
result.summary()         # "최적 ISA 비중: 100% (절세 ₩860만)"
```

### build_krw_attribution()

자산 성과 / 환율 효과 / 세금 손실 분해.

```python
krw = build_krw_attribution(result, base_fx=1300.0)
krw.asset_gain_krw       # 자산 기여
krw.fx_effect_krw        # 환율 기여
krw.tax_drag_krw         # 세금 손실
krw.summary_text()       # 전체 분해 출력
```

### interpret_tax_structure()

세금 구조 자동 해석.

```python
tax = interpret_tax_structure(result, config)
tax.dominant_tax_type    # "capital_gains" | "dividend" | ...
tax.findings             # ["양도세 100% 집중", ...]
tax.opportunities        # ["ISA 활용 여지", ...]
tax.summary_text         # 전체 해석
```

## Compile API

```python
from aftertaxi.strategies.compile import compile_backtest

config = compile_backtest(payload, strict=True)
# strict=True: 누락 필드 → ValueError
# strict=False: 기본값 자동 채움 + warning
```
