# -*- coding: utf-8 -*-
"""
analysis/krw_attribution.py — KRW 기여 분해
=============================================
"세후 KRW 결과가 무엇 때문에 나왔는가?"

자산 성과 / 환율 효과 / 세금 손실을 분리.

사용법:
  from aftertaxi.analysis.krw_attribution import build_krw_attribution

  report = build_krw_attribution(result, base_fx=1300.0)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KrwAttributionReport:
    """KRW 기준 기여 분해."""
    invested_krw: float           # 투입 원화 환산
    asset_gain_krw: float         # 자산 성과 기여 (USD 수익 × base_fx)
    fx_effect_krw: float          # 환율 변동 효과
    tax_drag_krw: float           # 세금 손실
    net_pv_krw: float             # 최종 세후 KRW

    @property
    def total_gain_krw(self) -> float:
        return self.net_pv_krw - self.invested_krw

    def summary_text(self) -> str:
        lines = [
            f"투입: ₩{self.invested_krw:,.0f}",
            f"자산 성과: {'+' if self.asset_gain_krw >= 0 else ''}₩{self.asset_gain_krw:,.0f}",
            f"환율 효과: {'+' if self.fx_effect_krw >= 0 else ''}₩{self.fx_effect_krw:,.0f}",
            f"세금 손실: -₩{self.tax_drag_krw:,.0f}",
            f"세후 결과: ₩{self.net_pv_krw:,.0f}",
        ]
        return "\n".join(lines)


def build_krw_attribution(result, base_fx: float = None) -> KrwAttributionReport:
    """EngineResult → KRW 기여 분해.

    1차 근사 분해:
      invested_krw = invested_usd × base_fx
      asset_gain_krw = (gross_pv_usd - invested_usd) × base_fx
      fx_effect_krw = gross_pv_usd × (reporting_fx - base_fx)
      tax_drag_krw = gross_pv_krw - net_pv_krw

    검산: invested_krw + asset_gain + fx_effect - tax_drag ≈ net_pv_krw
    """
    if base_fx is None:
        base_fx = result.reporting_fx_rate

    invested_usd = result.invested_usd
    gross_usd = result.gross_pv_usd
    reporting_fx = result.reporting_fx_rate

    # 분해
    # gross_pv_usd는 세금 납부 후 값이므로, 세전 USD는 역산 필요
    tax_total_krw = result.tax.total_assessed_krw
    tax_paid_krw = result.tax.total_paid_krw

    invested_krw = invested_usd * base_fx
    # 세전 진짜 자산 성과 = (gross_usd + 납부세금/fx) - invested
    gross_pretax_usd = gross_usd + tax_paid_krw / reporting_fx
    asset_gain_krw = (gross_pretax_usd - invested_usd) * base_fx
    fx_effect_krw = gross_pretax_usd * (reporting_fx - base_fx)
    tax_drag_krw = tax_total_krw

    return KrwAttributionReport(
        invested_krw=invested_krw,
        asset_gain_krw=asset_gain_krw,
        fx_effect_krw=fx_effect_krw,
        tax_drag_krw=tax_drag_krw,
        net_pv_krw=result.net_pv_krw,
    )
