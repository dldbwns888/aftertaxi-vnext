# -*- coding: utf-8 -*-
"""
analysis/isa_optimizer.py — ISA 최적화 엔진
============================================
"ISA를 얼마나 써야 가장 유리한가?"에 답한다.

사용법:
  from aftertaxi.analysis.isa_optimizer import optimize_isa, ISAOptResult

  result = optimize_isa(
      strategy_payload={"type": "q60s40"},
      total_monthly=1000,
      returns=ret, prices=pri, fx_rates=fx,
  )
  print(f"최적 ISA 비중: {result.best_isa_pct:.0%}")
  print(f"절세: ₩{result.tax_savings_krw:,.0f}")
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import pandas as pd


@dataclass
class ISAOptPoint:
    """ISA 비중별 결과."""
    isa_pct: float          # 0.0 ~ 1.0
    isa_monthly: float      # USD
    taxable_monthly: float  # USD
    mult_after_tax: float
    tax_total_krw: float
    net_pv_krw: float


@dataclass
class ISAOptResult:
    """ISA 최적화 결과."""
    points: List[ISAOptPoint]
    best_isa_pct: float
    best_net_pv_krw: float
    worst_net_pv_krw: float
    tax_savings_krw: float     # best vs worst 절세액
    taxable_only_tax: float    # ISA 0% 기준

    def summary(self) -> str:
        return (
            f"최적 ISA 비중: {self.best_isa_pct:.0%} "
            f"(절세 ₩{self.tax_savings_krw:,.0f}, "
            f"세후 ₩{self.best_net_pv_krw:,.0f})"
        )


def optimize_isa(
    strategy_payload: dict,
    total_monthly: float,
    returns: pd.DataFrame,
    prices: pd.DataFrame,
    fx_rates: pd.Series,
    isa_pct_range: list = None,
) -> ISAOptResult:
    """ISA 비중을 바꿔가며 최적점을 찾는다.

    brute force: 0%, 10%, ..., 100%까지 ISA 비중별 세후 결과 비교.
    """
    from aftertaxi.apps.service import run_strategy

    if isa_pct_range is None:
        isa_pct_range = [i / 10 for i in range(11)]  # 0.0 ~ 1.0

    points = []

    for pct in isa_pct_range:
        isa_mo = total_monthly * pct
        tax_mo = total_monthly * (1 - pct)

        if pct == 0:
            accounts = [{"type": "TAXABLE", "monthly_contribution": total_monthly}]
        elif pct == 1.0:
            accounts = [{"type": "ISA", "monthly_contribution": total_monthly, "priority": 0}]
        else:
            accounts = [
                {"type": "ISA", "monthly_contribution": isa_mo, "priority": 0},
                {"type": "TAXABLE", "monthly_contribution": tax_mo, "priority": 1},
            ]

        payload = {
            "strategy": strategy_payload,
            "accounts": accounts,
        }

        try:
            out = run_strategy(payload, returns, prices, fx_rates,
                               data_source="synthetic", save_to_memory=False,
                               run_baseline=False)
            points.append(ISAOptPoint(
                isa_pct=pct,
                isa_monthly=isa_mo,
                taxable_monthly=tax_mo,
                mult_after_tax=out.result.mult_after_tax,
                tax_total_krw=out.result.tax.total_assessed_krw,
                net_pv_krw=out.result.net_pv_krw,
            ))
        except Exception:
            pass

    if not points:
        return ISAOptResult([], 0, 0, 0, 0, 0)

    best = max(points, key=lambda p: p.net_pv_krw)
    worst = min(points, key=lambda p: p.net_pv_krw)
    taxable_only = next((p for p in points if p.isa_pct == 0), worst)

    return ISAOptResult(
        points=points,
        best_isa_pct=best.isa_pct,
        best_net_pv_krw=best.net_pv_krw,
        worst_net_pv_krw=worst.net_pv_krw,
        tax_savings_krw=taxable_only.tax_total_krw - best.tax_total_krw,
        taxable_only_tax=taxable_only.tax_total_krw,
    )
