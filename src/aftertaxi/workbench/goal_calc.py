# -*- coding: utf-8 -*-
"""
workbench/goal_calc.py — 목표 금액 역산 계산기
===============================================
"30년 후 세후 10억 원이 목표면 월 납입 얼마?"

binary search로 역산. facade.run_backtest() 반복 호출.
코어 무관.

사용법:
  from aftertaxi.workbench.goal_calc import find_monthly_for_goal

  result = find_monthly_for_goal(
      target_krw=1_000_000_000,
      strategy_payload={"type": "q60s40"},
      returns=returns, prices=prices, fx_rates=fx,
  )
  print(f"월 ${result.monthly_usd:,.0f} 필요")
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from aftertaxi.core.contracts import EngineResult


@dataclass(frozen=True)
class GoalCalcResult:
    """역산 결과."""
    target_krw: float
    monthly_usd: float
    achieved_krw: float
    n_months: int
    iterations: int
    fx_rate: float = 1300.0

    def summary_text(self) -> str:
        years = self.n_months / 12
        return (
            f"목표: ₩{self.target_krw:,.0f} ({years:.0f}년)\n"
            f"필요 월 납입: ${self.monthly_usd:,.0f} (≈ ₩{self.monthly_usd * self.fx_rate:,.0f})\n"
            f"예상 달성: ₩{self.achieved_krw:,.0f}\n"
            f"({self.iterations}회 탐색)"
        )


def find_monthly_for_goal(
    target_krw: float,
    strategy_payload: dict,
    returns: pd.DataFrame,
    prices: pd.DataFrame,
    fx_rates: pd.Series,
    account_type: str = "TAXABLE",
    lo: float = 100.0,
    hi: float = 50_000.0,
    tolerance: float = 0.02,
    max_iter: int = 20,
    n_months: Optional[int] = None,
) -> GoalCalcResult:
    """binary search로 목표 세후 금액 달성에 필요한 월 납입 역산.

    Parameters
    ----------
    target_krw : 목표 세후 PV (KRW)
    strategy_payload : {"type": "q60s40"} 등
    lo, hi : 탐색 범위 (USD/월)
    tolerance : 목표 대비 허용 오차 (2%)
    """
    from aftertaxi.strategies.compile import compile_backtest
    from aftertaxi.core.facade import run_backtest

    def _run(monthly: float) -> float:
        payload = {
            "strategy": strategy_payload,
            "accounts": [{"type": account_type, "monthly_contribution": monthly}],
        }
        if n_months:
            payload["n_months"] = n_months
        config = compile_backtest(payload)
        result = run_backtest(config, returns=returns, prices=prices, fx_rates=fx_rates)
        return result.net_pv_krw

    # fx_rate for display
    _fx = float(fx_rates.iloc[-1]) if hasattr(fx_rates, 'iloc') else float(fx_rates)

    iterations = 0
    for _ in range(max_iter):
        iterations += 1
        mid = (lo + hi) / 2
        achieved = _run(mid)

        if abs(achieved - target_krw) / target_krw < tolerance:
            return GoalCalcResult(
                target_krw=target_krw, monthly_usd=mid,
                achieved_krw=achieved, n_months=n_months or len(returns),
                iterations=iterations, fx_rate=_fx,
            )

        if achieved < target_krw:
            lo = mid
        else:
            hi = mid

    # max_iter 도달
    mid = (lo + hi) / 2
    achieved = _run(mid)
    return GoalCalcResult(
        target_krw=target_krw, monthly_usd=mid,
        achieved_krw=achieved, n_months=n_months or len(returns),
        iterations=iterations, fx_rate=_fx,
    )
