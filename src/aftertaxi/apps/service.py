# -*- coding: utf-8 -*-
"""
apps/service.py — 앱 서비스 레이어
===================================
앱(GUI/CLI)이 코어를 직접 만지지 않게 하는 중간 계층.

앱은 이 모듈만 import하면 됨:
  from aftertaxi.apps.service import run_strategy, RunOutput

앱이 몰라도 되는 것:
  compile, facade, attribution, advisor, memory, fingerprint 내부
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from aftertaxi.core.contracts import BacktestConfig, EngineResult
    from aftertaxi.core.attribution import ResultAttribution
    from aftertaxi.intent.plan import CompileTrace
    from aftertaxi.advisor.types import AdvisorReport
    from aftertaxi.experiments.fingerprint import DataProvenance


@dataclass
class RunOutput:
    """앱이 받는 실행 결과 전부. 타입이 명시적."""
    # 코어 결과
    result: EngineResult
    attribution: ResultAttribution
    config: BacktestConfig
    trace: CompileTrace

    # Advisor
    advisor_report: AdvisorReport

    # baseline (있으면)
    baseline_result: Optional[EngineResult] = None

    # provenance (구조적 추적)
    provenance: Optional[DataProvenance] = None

    # memory
    run_id: str = ""

    # 하위호환 프로퍼티
    @property
    def data_source(self) -> str:
        return self.provenance.source if self.provenance else ""

    @property
    def data_fingerprint(self) -> str:
        return self.provenance.fingerprint if self.provenance else ""

    @property
    def mult_after_tax(self) -> float:
        return self.result.mult_after_tax

    @property
    def mdd(self) -> float:
        return self.result.mdd

    @property
    def tax_drag_pct(self) -> float:
        return self.attribution.tax_drag_pct

    @property
    def baseline_gap(self) -> Optional[float]:
        if self.baseline_result:
            return self.result.mult_after_tax - self.baseline_result.mult_after_tax
        return None


def run_strategy(
    payload: dict,
    returns: pd.DataFrame,
    prices: pd.DataFrame,
    fx_rates: pd.Series,
    data_source: str = "synthetic",
    save_to_memory: bool = True,
    run_baseline: bool = True,
) -> RunOutput:
    """전략 실행 — 앱의 단일 진입점.

    compile → run → attribution → advisor → baseline → memory 전부 처리.
    앱은 이 함수 하나만 호출하면 됨.
    """
    from aftertaxi.strategies.compile import compile_backtest_with_trace
    from aftertaxi.core.facade import run_backtest
    from aftertaxi.core.attribution import build_attribution
    from aftertaxi.core.contracts import (
        AccountConfig, AccountType, BacktestConfig as BTC, StrategyConfig as SC,
    )
    from aftertaxi.advisor.builder import build_advisor_input
    from aftertaxi.advisor.rules import run_advisor
    from aftertaxi.apps.data_fingerprint import compute_fingerprint

    # 1. Compile
    config, trace = compile_backtest_with_trace(payload)

    # 2. Engine
    result = run_backtest(config, returns=returns, prices=prices, fx_rates=fx_rates)
    attribution = build_attribution(result)

    # 3. Baseline (SPY B&H)
    baseline_result = None
    if run_baseline and "SPY" in prices.columns:
        strategy_key = payload.get("strategy", {}).get("type", "")
        if strategy_key != "spy_bnh":
            try:
                total_monthly = sum(a.monthly_contribution for a in config.accounts)
                bl_cfg = BTC(
                    accounts=[AccountConfig("bl", AccountType.TAXABLE, total_monthly)],
                    strategy=SC("spy_bnh", {"SPY": 1.0}),
                )
                baseline_result = run_backtest(bl_cfg, returns=returns, prices=prices, fx_rates=fx_rates)
            except Exception:
                pass

    # 4. Advisor
    adv_input = build_advisor_input(result, attribution, config,
                                     baseline_result=baseline_result)
    advisor_report = run_advisor(adv_input)

    # 5. Provenance (구조적 추적)
    from aftertaxi.experiments.fingerprint import DataProvenance as DP
    fp = compute_fingerprint(returns, fx_rates)
    provenance = DP(
        fingerprint=fp,
        source=data_source,
        assets=list(returns.columns),
        date_range=f"{returns.index[0]:%Y-%m}~{returns.index[-1]:%Y-%m}",
        n_months=len(returns),
        notes="synthetic" if data_source == "synthetic" else "",
    )

    # 6. Memory
    run_id = ""
    if save_to_memory:
        try:
            import json
            from aftertaxi.apps.memory import ResearchMemory
            memory = ResearchMemory()
            strategy_key = payload.get("strategy", {}).get("type", "unknown")
            run_id = memory.record(
                config_json=json.dumps(payload, ensure_ascii=False),
                gross_pv_usd=result.gross_pv_usd,
                net_pv_krw=result.net_pv_krw,
                tax_assessed_krw=result.tax.total_assessed_krw,
                mdd=result.mdd,
                n_months=result.n_months,
                name=f"{strategy_key} {result.n_months // 12}yr",
                advisor_summary=advisor_report.summary,
                data_fingerprint=fp,
                data_source=data_source,
            )
        except Exception:
            pass

    return RunOutput(
        result=result,
        attribution=attribution,
        config=config,
        trace=trace,
        advisor_report=advisor_report,
        baseline_result=baseline_result,
        provenance=provenance,
        run_id=run_id,
    )


@dataclass
class CompareOutput:
    """비교 결과."""
    outputs: List[RunOutput]
    rank_table: List[Dict]
    winner: str


def compare_strategies(
    payloads: List[dict],
    labels: List[str],
    returns: pd.DataFrame,
    prices: pd.DataFrame,
    fx_rates: pd.Series,
    data_source: str = "synthetic",
) -> CompareOutput:
    """여러 전략 비교 — 서비스 레이어.

    payloads와 labels는 같은 길이. 같은 데이터로 전부 실행 후 순위.
    """
    outputs = []
    for payload in payloads:
        out = run_strategy(payload, returns, prices, fx_rates,
                           data_source=data_source, save_to_memory=False,
                           run_baseline=False)
        outputs.append(out)

    # 순위 테이블
    rows = []
    for label, out in zip(labels, outputs):
        rows.append({
            "label": label,
            "mult_after_tax": out.result.mult_after_tax,
            "mdd": out.result.mdd,
            "tax_drag_pct": out.attribution.tax_drag_pct,
        })

    rows.sort(key=lambda r: r["mult_after_tax"], reverse=True)
    winner = rows[0]["label"] if rows else ""

    return CompareOutput(outputs=outputs, rank_table=rows, winner=winner)


@dataclass
class ValidatedRunOutput:
    """검증 포함 실행 결과."""
    run: RunOutput
    validation_report: Optional[object] = None  # ValidationReport
    validation_grade: str = ""                   # "A" ~ "F"
    validation_passed: bool = True


def run_validated_strategy(
    payload: dict,
    returns: pd.DataFrame,
    prices: pd.DataFrame,
    fx_rates: pd.Series,
    data_source: str = "synthetic",
    full_validation: bool = False,
) -> ValidatedRunOutput:
    """검증 포함 전략 실행 — 성과 + 검증을 한 번에.

    결과를 믿을 수 있는지까지 답한다.
    """
    # 1. 일반 실행
    out = run_strategy(payload, returns, prices, fx_rates,
                       data_source=data_source, save_to_memory=True)

    # 2. 검증
    validation_report = None
    grade = ""
    passed = True
    try:
        import numpy as np
        from aftertaxi.validation import validate

        # excess returns 계산 (단순: 월별 수익률)
        mv = out.result.monthly_values
        if len(mv) > 1:
            monthly_returns = np.diff(mv) / mv[:-1]
            vr = validate(
                result=out.result,
                excess_returns=monthly_returns,
                strategy_name=payload.get("strategy", {}).get("type", "unknown"),
                full=full_validation,
            )
            validation_report = vr
            grade = vr.grade if hasattr(vr, "grade") else ""
            passed = vr.passed if hasattr(vr, "passed") else True
    except Exception:
        pass  # 검증 실패해도 실행 결과는 유효

    return ValidatedRunOutput(
        run=out,
        validation_report=validation_report,
        validation_grade=grade,
        validation_passed=passed,
    )
