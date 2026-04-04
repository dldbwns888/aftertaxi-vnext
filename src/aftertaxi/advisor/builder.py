# -*- coding: utf-8 -*-
"""
advisor/builder.py — AdvisorInput 생성기
=========================================
EngineResult + ValidationReport → AdvisorInput.

이 함수가 "Advisor는 raw data 접근 금지"를 강제하는 병목점.
Advisor는 이 함수의 출력만 받는다.
"""
from __future__ import annotations

from typing import Optional

from aftertaxi.core.contracts import EngineResult, BacktestConfig, AccountType
from aftertaxi.core.attribution import ResultAttribution
from aftertaxi.advisor.types import AdvisorInput


def build_advisor_input(
    result: EngineResult,
    attribution: ResultAttribution,
    config: BacktestConfig,
    baseline_result: Optional[EngineResult] = None,
    validation_grade: Optional[str] = None,
    lane_d_survival: Optional[float] = None,
) -> AdvisorInput:
    """EngineResult → AdvisorInput 정제.

    이 함수를 거치면 raw monthly_values, positions, journal 등은
    모두 버려지고, 계산된 지표만 AdvisorInput에 담긴다.
    """
    has_isa = any(
        a.account_type == AccountType.ISA
        for a in config.accounts
    )
    has_progressive = any(
        a.tax_config.progressive_brackets is not None
        for a in config.accounts
    )

    baseline_mult = None
    baseline_gap = None
    if baseline_result is not None:
        baseline_mult = baseline_result.mult_after_tax
        if baseline_mult > 0:
            baseline_gap = (result.mult_after_tax - baseline_mult) / baseline_mult * 100

    return AdvisorInput(
        mult_after_tax=result.mult_after_tax,
        mdd=result.mdd,
        tax_drag_pct=attribution.tax_drag_pct,
        n_months=result.n_months,
        has_isa=has_isa,
        has_progressive=has_progressive,
        n_accounts=result.n_accounts,
        rebalance_mode=config.accounts[0].rebalance_mode.value if config.accounts else "CONTRIBUTION_ONLY",
        validation_grade=validation_grade,
        lane_d_survival=lane_d_survival,
        baseline_mult=baseline_mult,
        baseline_gap_pct=baseline_gap,
    )
