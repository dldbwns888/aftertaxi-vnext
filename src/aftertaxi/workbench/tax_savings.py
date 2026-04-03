# -*- coding: utf-8 -*-
"""
workbench/tax_savings.py — 세금 절감 시뮬레이터
===============================================
"같은 전략, TAXABLE만 vs ISA 포함" 비교.
ISA 활용 시 절세액(원화)을 직접 계산.

코어 무관. compile + facade 호출만.

사용법:
  from aftertaxi.workbench.tax_savings import simulate_tax_savings

  report = simulate_tax_savings(
      strategy_payload={"type": "q60s40"},
      total_monthly=1000,
      isa_ratio=0.3,
      returns=returns, prices=prices, fx_rates=fx,
  )
  print(report.summary_text())
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from aftertaxi.core.contracts import EngineResult


@dataclass(frozen=True)
class TaxSavingsReport:
    """ISA 절세 효과 리포트."""
    # TAXABLE 100%
    taxable_only_mult: float
    taxable_only_tax: float

    # ISA + TAXABLE
    mixed_mult: float
    mixed_tax: float
    isa_ratio: float

    # 절세 효과
    tax_savings_krw: float
    mult_improvement: float

    def summary_text(self) -> str:
        return (
            f"═══ ISA 절세 시뮬레이션 (ISA {self.isa_ratio:.0%}) ═══\n"
            f"  TAXABLE 100%: 세후 {self.taxable_only_mult:.3f}x, 세금 ₩{self.taxable_only_tax:,.0f}\n"
            f"  ISA {self.isa_ratio:.0%} 혼합: 세후 {self.mixed_mult:.3f}x, 세금 ₩{self.mixed_tax:,.0f}\n"
            f"  절세액: ₩{self.tax_savings_krw:,.0f}\n"
            f"  배수 개선: {self.mult_improvement:+.3f}x"
        )


def simulate_tax_savings(
    strategy_payload: dict,
    total_monthly: float,
    isa_ratio: float,
    returns: pd.DataFrame,
    prices: pd.DataFrame,
    fx_rates: pd.Series,
    n_months: Optional[int] = None,
) -> TaxSavingsReport:
    """ISA 절세 효과 시뮬레이션.

    Parameters
    ----------
    strategy_payload : {"type": "q60s40"} 등
    total_monthly : 총 월 납입 (USD)
    isa_ratio : ISA에 넣을 비율 (0~1)
    """
    from aftertaxi.strategies.compile import compile_backtest
    from aftertaxi.core.facade import run_backtest

    base_payload = {"strategy": strategy_payload}
    if n_months:
        base_payload["n_months"] = n_months

    # 1. TAXABLE 100%
    payload_t = {**base_payload, "accounts": [
        {"type": "TAXABLE", "monthly_contribution": total_monthly},
    ]}
    cfg_t = compile_backtest(payload_t)
    r_t = run_backtest(cfg_t, returns=returns, prices=prices, fx_rates=fx_rates)

    # 2. ISA + TAXABLE
    isa_monthly = total_monthly * isa_ratio
    tax_monthly = total_monthly * (1 - isa_ratio)
    payload_m = {**base_payload, "accounts": [
        {"type": "ISA", "monthly_contribution": isa_monthly, "priority": 0},
        {"type": "TAXABLE", "monthly_contribution": tax_monthly, "priority": 1},
    ]}
    cfg_m = compile_backtest(payload_m)
    r_m = run_backtest(cfg_m, returns=returns, prices=prices, fx_rates=fx_rates)

    # 배수 계산 — net_pv_krw(세후) + reporting_fx_rate
    fx_scalar = r_t.reporting_fx_rate if r_t.reporting_fx_rate > 0 else float(fx_rates.iloc[-1])
    invested_krw = r_t.invested_usd * fx_scalar
    t_mult = r_t.net_pv_krw / invested_krw if invested_krw > 0 else 0

    m_invested_krw = r_m.invested_usd * fx_scalar
    m_mult = r_m.net_pv_krw / m_invested_krw if m_invested_krw > 0 else 0

    return TaxSavingsReport(
        taxable_only_mult=t_mult,
        taxable_only_tax=r_t.tax.total_assessed_krw,
        mixed_mult=m_mult,
        mixed_tax=r_m.tax.total_assessed_krw,
        isa_ratio=isa_ratio,
        tax_savings_krw=r_t.tax.total_assessed_krw - r_m.tax.total_assessed_krw,
        mult_improvement=m_mult - t_mult,
    )
