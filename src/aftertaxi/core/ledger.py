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
        transaction_cost_bps: float = 0.0,
        journal=None,
        progressive_brackets: tuple = None,
        progressive_threshold: float = 20_000_000.0,
    ):
        self.account_id = account_id
        self.account_type = account_type
        self.tax_rate = tax_rate
        self.annual_exemption = annual_exemption
        self.isa_exempt_limit = isa_exempt_limit
        self.isa_excess_rate = isa_excess_rate
        self.transaction_cost_bps = transaction_cost_bps
        self._journal = journal  # Optional[EventJournal], None이면 기록 안 함
        self.progressive_brackets = progressive_brackets
        self.progressive_threshold = progressive_threshold

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
        # 항목별 버킷 (attribution용)
        self._capital_gains_tax_assessed_krw: float = 0.0
        self._dividend_tax_assessed_krw: float = 0.0
        self._health_insurance_assessed_krw: float = 0.0

        # ── 거래비용 (attribution용) ──
        self.total_transaction_cost_usd: float = 0.0

        # ── 배당 (attribution용) ──
        self.annual_dividend_gross_usd: float = 0.0
        self.annual_dividend_withholding_usd: float = 0.0
        self.cumulative_dividend_gross_usd: float = 0.0
        self.cumulative_dividend_withholding_usd: float = 0.0

        # ── 누적 ──
        self.total_invested_usd: float = 0.0
        self.annual_contribution_usd: float = 0.0  # 연간 납입 USD (연말 리셋)
        self.annual_contribution_krw: float = 0.0  # 연간 납입 KRW (cap 체크용, 연말 리셋)

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

    # ── 배당 처리 ──

    def apply_dividend(self, asset: str, gross_per_share: float,
                       withholding_rate: float, fx_rate: float,
                       reinvest: bool = True, px_usd: float = 0.0) -> float:
        """배당 이벤트 처리. Returns: net_dividend_usd.

        1. 보유 수량 × gross_per_share = gross dividend
        2. 원천징수 차감
        3. net을 현금에 추가 (또는 재투자)
        """
        pos = self.positions.get(asset)
        if pos is None or pos.qty < 1e-12:
            return 0.0

        gross_usd = pos.qty * gross_per_share
        withholding_usd = gross_usd * withholding_rate
        net_usd = gross_usd - withholding_usd

        # 상태 갱신
        self.annual_dividend_gross_usd += gross_usd
        self.annual_dividend_withholding_usd += withholding_usd
        self.cumulative_dividend_gross_usd += gross_usd
        self.cumulative_dividend_withholding_usd += withholding_usd

        if reinvest and px_usd > 0:
            # 재투자: net으로 같은 자산 매수 (fee 적용)
            reinvest_qty = net_usd / px_usd
            # 직접 position에 추가 (fee는 여기선 적용 안 함 — 배당 재투자는 별도)
            self.cash_usd += net_usd
            self.buy(asset, reinvest_qty, px_usd, fx_rate)
        else:
            # 현금유지
            self.cash_usd += net_usd

        self._log("dividend", amount_usd=net_usd, asset=asset, fx_rate=fx_rate,
                  metadata={"gross_usd": gross_usd, "withholding_usd": withholding_usd,
                            "withholding_rate": withholding_rate, "reinvest": reinvest})

        return net_usd

    def _log(self, event_type: str, **kwargs) -> None:
        """journal이 있으면 기록, 없으면 무시."""
        if self._journal is not None:
            self._journal.record(event_type, self.account_id, **kwargs)

    # ── 입금 ──

    def deposit(self, amount_usd: float, fx_rate: float = 1300.0) -> float:
        """입금. 납입 사건의 단일 소유자.

        cash_usd, annual_contribution_usd, annual_contribution_krw를
        한 호출에서 원자적으로 갱신.
        """
        if amount_usd <= 0:
            return 0.0
        if fx_rate <= 0:
            raise ValueError(f"fx_rate must be positive, got {fx_rate}")
        self.cash_usd += amount_usd
        self.total_invested_usd += amount_usd
        self.annual_contribution_usd += amount_usd
        self.annual_contribution_krw += amount_usd * fx_rate
        self._log("deposit", amount_usd=amount_usd, fx_rate=fx_rate)
        return amount_usd

    # ── 매수 (FX) ──

    def buy(self, asset: str, qty: float, px_usd: float, fx_rate: float) -> None:
        """매수. cash 차감 + position 갱신 + KRW 원가 기록.

        거래비용은 취득가에 포함 (한국 세법: 필요경비).
        """
        cost_usd = qty * px_usd
        fee_usd = cost_usd * (self.transaction_cost_bps / 10_000)
        total_cost_usd = cost_usd + fee_usd

        if total_cost_usd > self.cash_usd + 1e-8:
            # 현금 부족 — 가능한 만큼만 (fee 포함)
            available = self.cash_usd
            cost_usd = available / (1 + self.transaction_cost_bps / 10_000)
            fee_usd = available - cost_usd
            total_cost_usd = available
            qty = cost_usd / px_usd

        self.cash_usd -= total_cost_usd
        self.total_transaction_cost_usd += fee_usd

        # 원가에 fee 포함 (세법상 취득가)
        cost_with_fee_krw = total_cost_usd * fx_rate

        if asset not in self.positions:
            self.positions[asset] = Position()

        pos = self.positions[asset]
        pos.qty += qty
        pos.cost_basis_usd += total_cost_usd
        pos.cost_basis_krw += cost_with_fee_krw
        pos.market_value_usd = pos.qty * px_usd

        self._log("buy", amount_usd=cost_usd, asset=asset, fx_rate=fx_rate,
                  metadata={"qty": qty, "px": px_usd, "fee_usd": fee_usd})

    # ── 매도 (FX) ──

    def sell(self, asset: str, qty: float, px_usd: float, fx_rate: float) -> float:
        """매도. AVGCOST 기준 실현손익(KRW) 계산.

        거래비용은 양도가에서 차감 (한국 세법: 필요경비).
        Returns: realized_pnl_krw
        """
        pos = self.positions.get(asset)
        if pos is None or pos.qty < 1e-12:
            return 0.0

        qty = min(qty, pos.qty)
        gross_proceeds_usd = qty * px_usd
        fee_usd = gross_proceeds_usd * (self.transaction_cost_bps / 10_000)
        net_proceeds_usd = gross_proceeds_usd - fee_usd
        net_proceeds_krw = net_proceeds_usd * fx_rate

        # AVGCOST: 비례 원가
        fraction = qty / pos.qty
        cost_krw = pos.cost_basis_krw * fraction
        cost_usd = pos.cost_basis_usd * fraction

        # 실현손익 (fee 차감 후 수취액 - 원가)
        realized_krw = net_proceeds_krw - cost_krw

        # 상태 갱신
        self.cash_usd += net_proceeds_usd
        self.total_transaction_cost_usd += fee_usd
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

        self._log("sell", amount_usd=net_proceeds_usd, asset=asset, fx_rate=fx_rate,
                  amount_krw=net_proceeds_krw,
                  metadata={"qty": qty, "px": px_usd, "fee_usd": fee_usd,
                            "realized_krw": realized_krw})
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
        """연말 양도세 정산. get → compute → apply 패턴.

        직접 호출 시 하위 호환 유지 (settlement 경유 권장).
        """
        from aftertaxi.core.tax_engine import compute_capital_gains_tax
        inputs = self.get_cgt_inputs(current_year)
        result = compute_capital_gains_tax(**inputs)
        return self.apply_cgt_result(result)

    def get_cgt_inputs(self, current_year: int = 0) -> dict:
        """양도세 계산에 필요한 입력. settlement가 사용."""
        return dict(
            realized_gain_krw=self.annual_realized_gain_krw,
            realized_loss_krw=self.annual_realized_loss_krw,
            carryforward=self.loss_carryforward_krw,
            current_year=current_year,
            rate=self.tax_rate,
            exemption=self.annual_exemption,
            progressive_brackets=self.progressive_brackets,
            progressive_threshold=self.progressive_threshold,
        )

    def apply_cgt_result(self, result) -> float:
        """양도세 계산 결과 적용. settlement가 사용."""
        self._total_tax_assessed_krw += result.tax_krw
        self._capital_gains_tax_assessed_krw += result.tax_krw
        self.unpaid_tax_liability_krw += result.tax_krw
        self.loss_carryforward_krw = (
            result.carryforward_remaining + result.new_loss_carry
        )
        self.annual_realized_gain_krw = 0.0
        self.annual_realized_loss_krw = 0.0

        self._log("tax_assessed", amount_krw=result.tax_krw,
                  metadata={"taxable_base": result.taxable_base_krw,
                            "exemption_used": result.exemption_used_krw})
        return result.tax_krw
        # NOTE: annual_dividend_*는 settle_dividend_tax()에서 리셋 (순서 의존)

        self._log("tax_assessed", amount_krw=result.tax_krw,
                  metadata={"taxable_base": result.taxable_base_krw,
                            "exemption_used": result.exemption_used_krw})
        return result.tax_krw

    # ── ISA 만기 정산 ──

    def settle_isa(self) -> float:
        """ISA 만기 정산. get → compute → apply 패턴."""
        if self.isa_exempt_limit <= 0:
            return 0.0
        from aftertaxi.core.tax_engine import compute_isa_settlement
        inputs = self.get_isa_inputs()
        result = compute_isa_settlement(**inputs)
        return self.apply_isa_result(result)

    def get_isa_inputs(self) -> dict:
        """ISA 정산 입력. settlement가 사용."""
        return dict(
            cumulative_gain_krw=self.cumulative_realized_gain_krw,
            cumulative_loss_krw=self.cumulative_realized_loss_krw,
            exempt_limit=self.isa_exempt_limit,
            excess_rate=self.isa_excess_rate,
        )

    def apply_isa_result(self, result) -> float:
        """ISA 정산 결과 적용."""
        self._total_tax_assessed_krw += result.tax_krw
        self.unpaid_tax_liability_krw += result.tax_krw
        self._log("isa_settlement", amount_krw=result.tax_krw,
                  metadata={"net_gain": result.net_gain_krw,
                            "exempt": result.exempt_amount_krw,
                            "excess": result.excess_amount_krw})
        return result.tax_krw

    # ── 배당소득세 정산 ──

    def settle_dividend_tax(self, fx_rate: float) -> float:
        """연간 배당소득세 정산. get → compute → apply 패턴."""
        if self.annual_dividend_gross_usd < 1e-8:
            return 0.0
        from aftertaxi.core.tax_engine import compute_dividend_tax
        inputs = self.get_dividend_tax_inputs(fx_rate)
        result = compute_dividend_tax(**inputs)
        return self.apply_dividend_tax_result(result)

    def get_dividend_tax_inputs(self, fx_rate: float) -> dict:
        """배당세 계산 입력. settlement가 사용."""
        return dict(
            annual_dividend_gross_usd=self.annual_dividend_gross_usd,
            annual_withholding_usd=self.annual_dividend_withholding_usd,
            fx_rate=fx_rate,
        )

    def apply_dividend_tax_result(self, result) -> float:
        """배당세 결과 적용."""
        if result.additional_tax_krw > 0:
            self._total_tax_assessed_krw += result.additional_tax_krw
            self._dividend_tax_assessed_krw += result.additional_tax_krw
            self.unpaid_tax_liability_krw += result.additional_tax_krw

        self._log("dividend_tax", amount_krw=result.additional_tax_krw,
                  metadata={"gross_krw": result.annual_dividend_gross_krw,
                            "withholding_krw": result.annual_withholding_krw,
                            "is_comprehensive": result.is_comprehensive,
                            "foreign_credit": result.foreign_tax_credit_krw})

        # 연간 배당 카운터 리셋
        self.annual_dividend_gross_usd = 0.0
        self.annual_dividend_withholding_usd = 0.0
        return result.additional_tax_krw

    # ── 건강보험료 적용 ──

    def apply_health_insurance(self, premium_krw: float, fx_rate: float) -> float:
        """건강보험료 부과. person scope에서 계산된 금액을 적용.

        건보료는 세금과 별도 버킷이지만, 납부는 unpaid_tax_liability에 합산.
        (실제로는 별도 납부이지만, 엔진에서는 cash drag로 통합 처리)
        """
        if premium_krw < 1e-8:
            return 0.0

        self._health_insurance_assessed_krw += premium_krw
        self._total_tax_assessed_krw += premium_krw
        self.unpaid_tax_liability_krw += premium_krw

        self._log("health_insurance", amount_krw=premium_krw, fx_rate=fx_rate,
                  metadata={"premium_krw": premium_krw})

        return premium_krw

    # ── 세금 납부 (KRW → USD 차감) ──

    def pay_tax(self, fx_rate: float) -> float:
        """미납 세금을 USD cash에서 차감. Returns: tax_usd."""
        if self.unpaid_tax_liability_krw < 1e-8 or fx_rate <= 0:
            return 0.0
        tax_usd = self.unpaid_tax_liability_krw / fx_rate
        self.cash_usd -= tax_usd
        self._log("tax_paid", amount_usd=tax_usd, amount_krw=self.unpaid_tax_liability_krw,
                  fx_rate=fx_rate)
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
            "capital_gains_tax_krw": self._capital_gains_tax_assessed_krw,
            "dividend_tax_krw": self._dividend_tax_assessed_krw,
            "health_insurance_krw": self._health_insurance_assessed_krw,
            "transaction_cost_usd": self.total_transaction_cost_usd,
            "dividend_gross_usd": self.cumulative_dividend_gross_usd,
            "dividend_withholding_usd": self.cumulative_dividend_withholding_usd,
            "mdd": mdd,
            "n_months": len(self.monthly_values),
            "monthly_values": mv,
        }
