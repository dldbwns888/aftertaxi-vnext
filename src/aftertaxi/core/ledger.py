# -*- coding: utf-8 -*-
"""
ledger.py — 최소 FX-only 계좌 원장
====================================
PR 2: C/O + AVGCOST + 단일계좌 지원.
상태 단일 소유 원칙: 모든 잔고/세금 상태가 이 클래스 안에 있다.

설계 원칙:
  1. FX-only. legacy 단일통화 모드 없음.
  2. 성과(USD)와 세금(KRW)을 같은 변수에 섞지 않는다.
  3. buy/sell 1회 = cash + position + tax state 원자적 갱신.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np


# ══════════════════════════════════════════════
# Position
# ══════════════════════════════════════════════

@dataclass
class Position:
    """AVGCOST 포지션."""
    qty: float = 0.0
    cost_basis_usd: float = 0.0  # 총 매입원가 (USD)
    cost_basis_krw: float = 0.0  # 총 매입원가 (KRW, 세금용)
    market_value_usd: float = 0.0  # 현재 시가 (USD)

    @property
    def avg_cost_usd(self) -> float:
        return self.cost_basis_usd / self.qty if self.qty > 1e-12 else 0.0

    @property
    def avg_cost_krw(self) -> float:
        return self.cost_basis_krw / self.qty if self.qty > 1e-12 else 0.0


# ══════════════════════════════════════════════
# Ledger
# ══════════════════════════════════════════════

class AccountLedger:
    """FX-only 계좌 원장.

    Parameters
    ----------
    account_id : 계좌 식별자
    tax_rate : 양도세율 (e.g. 0.22)
    annual_exemption : 연간 공제액 (KRW)
    isa_exempt_limit : ISA 비과세 한도 (KRW, 0이면 비ISA)
    isa_excess_rate : ISA 초과분 세율
    """

    def __init__(
        self,
        account_id: str,
        account_type: str = "TAXABLE",
        tax_rate: float = 0.22,
        annual_exemption: float = 2_500_000.0,
        isa_exempt_limit: float = 0.0,
        isa_excess_rate: float = 0.099,
    ):
        self.account_id = account_id
        self.account_type = account_type
        self.tax_rate = tax_rate
        self.annual_exemption = annual_exemption
        self.isa_exempt_limit = isa_exempt_limit
        self.isa_excess_rate = isa_excess_rate

        # ── 잔고 ──
        self.cash_usd: float = 0.0
        self.positions: Dict[str, Position] = {}

        # ── 세금 (KRW) ──
        self.annual_realized_gain_krw: float = 0.0
        self.annual_realized_loss_krw: float = 0.0
        self.cumulative_realized_gain_krw: float = 0.0
        self.cumulative_realized_loss_krw: float = 0.0
        self._total_tax_assessed_krw: float = 0.0
        self.unpaid_tax_liability_krw: float = 0.0
        self.loss_carryforward_krw: List[Tuple[int, float]] = []

        # ── 누적 ──
        self.total_invested_usd: float = 0.0

        # ── 기록 ──
        self.monthly_values: List[float] = []

    # ── 잔고 조회 ──

    def portfolio_value_usd(self) -> float:
        return sum(p.market_value_usd for p in self.positions.values())

    def total_value_usd(self) -> float:
        return self.cash_usd + self.portfolio_value_usd()

    # ── 시가 반영 ──

    def mark_to_market(self, price_map: Dict[str, float]) -> None:
        """가격 갱신."""
        for asset, pos in self.positions.items():
            if asset in price_map and pos.qty > 1e-12:
                pos.market_value_usd = pos.qty * price_map[asset]

    # ── 입금 ──

    def deposit(self, amount_usd: float) -> None:
        self.cash_usd += amount_usd
        self.total_invested_usd += amount_usd

    # ── 매수 (FX) ──

    def buy(self, asset: str, qty: float, px_usd: float, fx_rate: float) -> None:
        """매수. cash 차감 + position 갱신 + KRW 원가 기록."""
        cost_usd = qty * px_usd
        if cost_usd > self.cash_usd + 1e-8:
            # 현금 부족 — 가능한 만큼만
            qty = self.cash_usd / px_usd
            cost_usd = qty * px_usd

        self.cash_usd -= cost_usd
        cost_krw = cost_usd * fx_rate

        if asset not in self.positions:
            self.positions[asset] = Position()

        pos = self.positions[asset]
        pos.qty += qty
        pos.cost_basis_usd += cost_usd
        pos.cost_basis_krw += cost_krw
        pos.market_value_usd = pos.qty * px_usd

    # ── 매도 (FX) ──

    def sell(self, asset: str, qty: float, px_usd: float, fx_rate: float) -> float:
        """매도. AVGCOST 기준 실현손익(KRW) 계산.

        Returns: realized_pnl_krw
        """
        pos = self.positions.get(asset)
        if pos is None or pos.qty < 1e-12:
            return 0.0

        qty = min(qty, pos.qty)
        proceeds_usd = qty * px_usd
        proceeds_krw = proceeds_usd * fx_rate

        # AVGCOST: 비례 원가
        fraction = qty / pos.qty
        cost_krw = pos.cost_basis_krw * fraction
        cost_usd = pos.cost_basis_usd * fraction

        realized_krw = proceeds_krw - cost_krw

        # 상태 갱신
        self.cash_usd += proceeds_usd
        pos.qty -= qty
        pos.cost_basis_usd -= cost_usd
        pos.cost_basis_krw -= cost_krw
        pos.market_value_usd = pos.qty * px_usd

        # 실현손익 기록
        if realized_krw > 0:
            self.annual_realized_gain_krw += realized_krw
            self.cumulative_realized_gain_krw += realized_krw
        else:
            self.annual_realized_loss_krw += abs(realized_krw)
            self.cumulative_realized_loss_krw += abs(realized_krw)

        return realized_krw

    # ── 전량 청산 ──

    def liquidate(self, price_map: Dict[str, float], fx_rate: float) -> None:
        """전 포지션 매도."""
        for asset in list(self.positions.keys()):
            pos = self.positions[asset]
            if pos.qty > 1e-12 and asset in price_map:
                self.sell(asset, pos.qty, price_map[asset], fx_rate)

    # ── 세금 정산 ──

    def settle_annual_tax(self, current_year: int = 0) -> float:
        """연말 세금 정산. Returns: tax_krw."""
        net = self.annual_realized_gain_krw - self.annual_realized_loss_krw

        # 이월결손금 차감
        remaining_loss = 0.0
        new_carry = []
        for yr, amt in self.loss_carryforward_krw:
            if current_year > 0 and yr > 0 and (current_year - yr) >= 5:
                continue  # 5년 만료
            remaining_loss += amt

        if net > 0:
            # 이월결손금으로 상쇄
            offset = min(net, remaining_loss)
            net -= offset
            remaining_loss -= offset
        else:
            # 올해 순손실 → 이월
            new_carry.append((current_year, abs(net)))
            net = 0.0

        # 남은 이월결손금 유지
        if remaining_loss > 1e-6:
            new_carry.append((current_year, remaining_loss))

        # 공제 적용
        taxable = max(0.0, net - self.annual_exemption)
        tax_krw = taxable * self.tax_rate

        # 상태 갱신
        self._total_tax_assessed_krw += tax_krw
        self.unpaid_tax_liability_krw += tax_krw
        self.loss_carryforward_krw = new_carry
        self.annual_realized_gain_krw = 0.0
        self.annual_realized_loss_krw = 0.0

        return tax_krw

    # ── ISA 만기 정산 ──

    def settle_isa(self) -> float:
        """ISA 만기: 누적 순이익 중 비과세 한도 초과분에 과세."""
        if self.isa_exempt_limit <= 0:
            return 0.0
        net = self.cumulative_realized_gain_krw - self.cumulative_realized_loss_krw
        taxable = max(0.0, net - self.isa_exempt_limit)
        tax_krw = taxable * self.isa_excess_rate
        self._total_tax_assessed_krw += tax_krw
        self.unpaid_tax_liability_krw += tax_krw
        return tax_krw

    # ── 세금 납부 (KRW → USD 차감) ──

    def pay_tax(self, fx_rate: float) -> float:
        """미납 세금을 USD cash에서 차감. Returns: tax_usd."""
        if self.unpaid_tax_liability_krw < 1e-8 or fx_rate <= 0:
            return 0.0
        tax_usd = self.unpaid_tax_liability_krw / fx_rate
        self.cash_usd -= tax_usd
        self.unpaid_tax_liability_krw = 0.0
        return tax_usd

    # ── 월말 기록 ──

    def record_month(self, *, replace_last: bool = False) -> None:
        pv = self.total_value_usd()
        if replace_last and self.monthly_values:
            self.monthly_values[-1] = pv
        else:
            self.monthly_values.append(pv)

    # ── 요약 ──

    def summary(self) -> dict:
        mv = np.array(self.monthly_values, dtype=float)
        if len(mv) > 0:
            peak = np.maximum.accumulate(np.where(mv > 0, mv, 1.0))
            mdd = float((mv / peak - 1.0).min())
        else:
            mdd = 0.0

        return {
            "account_id": self.account_id,
            "account_type": self.account_type,
            "gross_pv_usd": self.total_value_usd(),
            "invested_usd": self.total_invested_usd,
            "tax_assessed_krw": self._total_tax_assessed_krw,
            "tax_unpaid_krw": self.unpaid_tax_liability_krw,
            "mdd": mdd,
            "n_months": len(self.monthly_values),
            "monthly_values": mv,
        }
