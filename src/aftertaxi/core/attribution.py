# -*- coding: utf-8 -*-
"""
attribution.py — 세후 결과 원인 분해
=====================================
EngineResult에서 사후 계산. EngineResult를 수정하지 않는다.

설계 원칙:
  - EngineResult = "무슨 결과가 나왔는가"
  - ResultAttribution = "왜 그 결과가 나왔는가"
  - attribution은 해석 레이어. 코어 계약을 비대하게 만들지 않는다.

MVP 범위:
  - 포트폴리오 수준 drag 분해 (transaction cost, tax, dividend withholding)
  - 계좌별 breakdown
  - 시장수익/선택효과/타이밍효과 같은 포트폴리오 attribution은 하지 않음
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from aftertaxi.core.contracts import AccountSummary, EngineResult


# ══════════════════════════════════════════════
# 계좌별 Attribution
# ══════════════════════════════════════════════

@dataclass(frozen=True)
class AccountAttribution:
    """계좌 1개의 drag 분해."""
    account_id: str
    account_type: str
    invested_usd: float
    gross_pv_usd: float
    transaction_cost_usd: float
    tax_assessed_krw: float
    dividend_gross_usd: float
    dividend_withholding_usd: float
    dividend_net_usd: float

    @property
    def gross_return_usd(self) -> float:
        """투자 대비 세전 수익 (USD)."""
        return self.gross_pv_usd - self.invested_usd

    @property
    def cost_drag_pct(self) -> float:
        """거래비용이 투자금 대비 몇 %인지."""
        if self.invested_usd <= 0:
            return 0.0
        return self.transaction_cost_usd / self.invested_usd * 100

    @property
    def withholding_drag_pct(self) -> float:
        """배당 원천징수가 투자금 대비 몇 %인지."""
        if self.invested_usd <= 0:
            return 0.0
        return self.dividend_withholding_usd / self.invested_usd * 100


# ══════════════════════════════════════════════
# 포트폴리오 Attribution
# ══════════════════════════════════════════════

@dataclass(frozen=True)
class ResultAttribution:
    """포트폴리오 수준 세후 결과 원인 분해.

    EngineResult에서 사후 계산. 코어 계약을 수정하지 않는다.
    """
    # 포트폴리오 합산
    invested_usd: float
    gross_pv_usd: float
    net_pv_krw: float
    reporting_fx_rate: float

    # drag 재료 (합산)
    total_transaction_cost_usd: float
    total_tax_assessed_krw: float
    total_tax_unpaid_krw: float
    total_dividend_gross_usd: float
    total_dividend_withholding_usd: float
    total_dividend_net_usd: float

    # 계좌별 breakdown
    account_attributions: List[AccountAttribution]

    @property
    def mult_pre_tax(self) -> float:
        if self.invested_usd <= 0:
            return 0.0
        return self.gross_pv_usd / self.invested_usd

    @property
    def mult_after_tax(self) -> float:
        if self.invested_usd <= 0 or self.reporting_fx_rate <= 0:
            return 0.0
        return (self.net_pv_krw / self.reporting_fx_rate) / self.invested_usd

    @property
    def cost_drag_pct(self) -> float:
        """거래비용이 투자금 대비 몇 %."""
        if self.invested_usd <= 0:
            return 0.0
        return self.total_transaction_cost_usd / self.invested_usd * 100

    @property
    def tax_drag_pct(self) -> float:
        """세금이 세전 PV 대비 몇 %."""
        gross_krw = self.gross_pv_usd * self.reporting_fx_rate
        if gross_krw <= 0:
            return 0.0
        return self.total_tax_assessed_krw / gross_krw * 100

    @property
    def withholding_drag_pct(self) -> float:
        """배당 원천징수가 투자금 대비 몇 %."""
        if self.invested_usd <= 0:
            return 0.0
        return self.total_dividend_withholding_usd / self.invested_usd * 100

    def summary_text(self) -> str:
        """한 눈에 보는 drag 분해."""
        lines = [
            f"=== ResultAttribution ===",
            f"투자금: ${self.invested_usd:,.0f}",
            f"세전 배수: {self.mult_pre_tax:.2f}x",
            f"세후 배수: {self.mult_after_tax:.2f}x",
            f"",
            f"[Drag 분해]",
            f"  거래비용: ${self.total_transaction_cost_usd:,.1f} ({self.cost_drag_pct:.2f}%)",
            f"  세금: {self.total_tax_assessed_krw:,.0f} KRW ({self.tax_drag_pct:.2f}%)",
            f"  배당 원천징수: ${self.total_dividend_withholding_usd:,.1f} ({self.withholding_drag_pct:.2f}%)",
            f"",
            f"[배당]",
            f"  총 배당: ${self.total_dividend_gross_usd:,.1f}",
            f"  원천징수: ${self.total_dividend_withholding_usd:,.1f}",
            f"  순 배당: ${self.total_dividend_net_usd:,.1f}",
        ]
        if self.account_attributions:
            lines.append("")
            lines.append(f"[계좌별]")
            for a in self.account_attributions:
                lines.append(
                    f"  {a.account_id} ({a.account_type}): "
                    f"PV ${a.gross_pv_usd:,.0f}, "
                    f"cost ${a.transaction_cost_usd:,.1f}, "
                    f"div net ${a.dividend_net_usd:,.1f}"
                )
        return "\n".join(lines)


# ══════════════════════════════════════════════
# 계산 함수
# ══════════════════════════════════════════════

def build_attribution(result: EngineResult) -> ResultAttribution:
    """EngineResult에서 ResultAttribution을 사후 계산.

    Parameters
    ----------
    result : EngineResult (facade에서 받은 결과)

    Returns
    -------
    ResultAttribution
    """
    account_attrs = []
    total_cost = 0.0
    total_div_gross = 0.0
    total_div_wh = 0.0

    for a in result.accounts:
        total_cost += a.transaction_cost_usd
        total_div_gross += a.dividend_gross_usd
        total_div_wh += a.dividend_withholding_usd

        account_attrs.append(AccountAttribution(
            account_id=a.account_id,
            account_type=a.account_type,
            invested_usd=a.invested_usd,
            gross_pv_usd=a.gross_pv_usd,
            transaction_cost_usd=a.transaction_cost_usd,
            tax_assessed_krw=a.tax_assessed_krw,
            dividend_gross_usd=a.dividend_gross_usd,
            dividend_withholding_usd=a.dividend_withholding_usd,
            dividend_net_usd=a.dividend_net_usd,
        ))

    return ResultAttribution(
        invested_usd=result.invested_usd,
        gross_pv_usd=result.gross_pv_usd,
        net_pv_krw=result.net_pv_krw,
        reporting_fx_rate=result.reporting_fx_rate,
        total_transaction_cost_usd=total_cost,
        total_tax_assessed_krw=result.tax.total_assessed_krw,
        total_tax_unpaid_krw=result.tax.total_unpaid_krw,
        total_dividend_gross_usd=total_div_gross,
        total_dividend_withholding_usd=total_div_wh,
        total_dividend_net_usd=total_div_gross - total_div_wh,
        account_attributions=account_attrs,
    )
