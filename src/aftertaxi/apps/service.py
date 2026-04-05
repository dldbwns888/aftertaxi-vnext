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

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, TYPE_CHECKING

import pandas as pd

logger = logging.getLogger(__name__)

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

    # 분석 결과 (GUI/CLI가 직접 계산하지 않도록 service에서 제공)
    interpretation_text: str = ""               # analysis.interpret 결과
    krw_attribution: Optional[object] = None    # KrwAttributionReport
    tax_structure_report: Optional[object] = None  # TaxStructureReport

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
                logger.warning("baseline 실행 실패", exc_info=True)

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

    # 5.5. 분석 결과 (GUI가 직접 계산하지 않도록)
    interpretation_text = ""
    krw_report = None
    tax_report = None
    try:
        from aftertaxi.analysis.interpret import interpret_result
        interpretation_text = interpret_result(result, attribution)
    except Exception:
        logger.warning("interpret_result 실패", exc_info=True)
    try:
        from aftertaxi.analysis.krw_attribution import build_krw_attribution
        krw_report = build_krw_attribution(result)
    except Exception:
        logger.warning("build_krw_attribution 실패", exc_info=True)
    try:
        from aftertaxi.analysis.tax_interpretation import interpret_tax_structure
        tax_report = interpret_tax_structure(result, config)
    except Exception:
        logger.warning("interpret_tax_structure 실패", exc_info=True)

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
            logger.warning("memory.record 실패 — 실행 기록 유실 가능", exc_info=True)

    return RunOutput(
        result=result,
        attribution=attribution,
        config=config,
        trace=trace,
        advisor_report=advisor_report,
        baseline_result=baseline_result,
        provenance=provenance,
        run_id=run_id,
        interpretation_text=interpretation_text,
        krw_attribution=krw_report,
        tax_structure_report=tax_report,
    )


@dataclass
class CompareOutput:
    """비교 결과."""
    outputs: List[RunOutput]
    rank_table: List[Dict]
    winner: str
    comparison_report: Optional[object] = None  # analysis.compare.ComparisonReport


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
    analysis.compare를 내부적으로 사용하여 통계 검정까지 수행.
    """
    outputs = []
    for payload in payloads:
        out = run_strategy(payload, returns, prices, fx_rates,
                           data_source=data_source, save_to_memory=False,
                           run_baseline=False)
        outputs.append(out)

    # analysis.compare로 풍부한 비교 리포트 생성
    from aftertaxi.analysis.compare import compare_strategies as _compare_analysis
    engine_results = [out.result for out in outputs]
    comparison_report = _compare_analysis(engine_results, names=labels)

    rank_table = comparison_report.rank_table()
    winner = comparison_report.winner

    return CompareOutput(
        outputs=outputs,
        rank_table=rank_table,
        winner=winner,
        comparison_report=comparison_report,
    )


@dataclass
class ValidatedRunOutput:
    """검증 + 종합 판단 포함 실행 결과."""
    run: RunOutput
    validation_report: Optional[object] = None
    validation_grade: str = ""
    validation_passed: bool = True
    advisor_v2: Optional[object] = None  # AdvisorV2Report


def run_validated_strategy(
    payload: dict,
    returns: pd.DataFrame,
    prices: pd.DataFrame,
    fx_rates: pd.Series,
    data_source: str = "synthetic",
    full_validation: bool = False,
    isa_optimize: bool = True,
    mode: str = "research",  # "research" | "decision_support"
) -> ValidatedRunOutput:
    """검증 + 종합 판단 포함 전략 실행.

    mode="research": 기본. 합성 허용, 경고만.
    mode="decision_support": 보수적. 합성 경고 강화, validation 필수, strict compile.
    """
    import warnings

    if mode == "decision_support":
        if data_source == "synthetic":
            warnings.warn(
                "decision_support 모드에서 합성 데이터 사용. "
                "실제 데이터(yfinance)로 재검증을 강력히 권장합니다.",
                UserWarning, stacklevel=2,
            )
        full_validation = True  # decision mode에서는 전체 검증 강제
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
        logger.warning("validation 실행 실패", exc_info=True)

    # 3. Advisor 2.0 — 종합 판단
    advisor_v2_report = None
    try:
        from aftertaxi.analysis.krw_attribution import build_krw_attribution
        from aftertaxi.analysis.tax_interpretation import interpret_tax_structure
        from aftertaxi.advisor.advisor_v2 import build_advisor_v2

        krw = build_krw_attribution(out.result)
        tax = interpret_tax_structure(out.result, out.config)

        # ISA 최적화 (선택적)
        isa_report = None
        if isa_optimize:
            try:
                from aftertaxi.analysis.isa_optimizer import optimize_isa
                strategy_payload = payload.get("strategy", {})
                total_monthly = sum(a.monthly_contribution for a in out.config.accounts)
                isa_report = optimize_isa(
                    strategy_payload, total_monthly,
                    returns, prices, fx_rates,
                    isa_pct_range=[0, 0.5, 1.0],  # 빠른 3점 스캔
                )
            except Exception:
                logger.warning("ISA 최적화 실패", exc_info=True)

        advisor_v2_report = build_advisor_v2(
            result=out.result,
            config=out.config,
            attribution=out.attribution,
            krw_report=krw,
            tax_report=tax,
            isa_report=isa_report,
            validation_report=validation_report,
            baseline_result=out.baseline_result,
        )
    except Exception:
        logger.warning("advisor_v2 빌드 실패", exc_info=True)

    return ValidatedRunOutput(
        run=out,
        validation_report=validation_report,
        validation_grade=grade,
        validation_passed=passed,
        advisor_v2=advisor_v2_report,
    )


# ══════════════════════════════════════════════
# 분석 서비스 (GUI/CLI가 직접 호출하던 것을 흡수)
# ══════════════════════════════════════════════

def run_tax_savings(
    strategy_payload: dict,
    total_monthly: float,
    isa_ratio: float,
    returns: pd.DataFrame,
    prices: pd.DataFrame,
    fx_rates: pd.Series,
    n_months: Optional[int] = None,
):
    """ISA 절세 시뮬레이션 — 서비스 레이어.

    Returns
    -------
    TaxSavingsReport
    """
    from aftertaxi.analysis.tax_savings import simulate_tax_savings
    return simulate_tax_savings(
        strategy_payload=strategy_payload,
        total_monthly=total_monthly,
        isa_ratio=isa_ratio,
        returns=returns,
        prices=prices,
        fx_rates=fx_rates,
        n_months=n_months,
    )


def run_sensitivity(
    strategy_payload: dict,
    n_months: int = 240,
    fx_rate: float = 1300.0,
    seed: int = 42,
    growth_range: Optional[List[float]] = None,
    vol_range: Optional[List[float]] = None,
):
    """민감도 히트맵 — 서비스 레이어.

    Returns
    -------
    SensitivityGrid
    """
    from aftertaxi.analysis.sensitivity import run_sensitivity as _sens
    return _sens(
        strategy_payload=strategy_payload,
        growth_range=growth_range,
        vol_range=vol_range,
        n_months=n_months,
        fx_rate=fx_rate,
        seed=seed,
    )


def run_lane_d(
    source_returns: pd.DataFrame,
    backtest_payload: dict,
    n_paths: int = 100,
    actual_result=None,
    n_jobs: int = 1,
):
    """Lane D 합성 장기 생존 시뮬레이션 — 서비스 레이어.

    payload를 받아서 compile까지 처리한 뒤 lane_d에 넘긴다.
    앱은 compile을 직접 만질 필요 없음.

    Returns
    -------
    SyntheticSurvivalReport
    """
    from aftertaxi.strategies.compile import compile_backtest
    from aftertaxi.lanes.lane_d.run import run_lane_d as _lane_d
    from aftertaxi.lanes.lane_d.synthetic import SyntheticMarketConfig

    config = compile_backtest(backtest_payload)
    synthetic_config = SyntheticMarketConfig(n_paths=n_paths)

    return _lane_d(
        source_returns=source_returns,
        backtest_config=config,
        synthetic_config=synthetic_config,
        actual_result=actual_result,
        n_jobs=n_jobs,
    )
