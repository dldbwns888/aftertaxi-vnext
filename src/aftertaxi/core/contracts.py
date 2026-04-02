# -*- coding: utf-8 -*-
"""
contracts.py — 엔진 입출력 타입 계약
=====================================
PR 1 slim schema: 의미가 확실한 코어 필드만.
Lane metadata, execution trace 등은 후속 PR에서 Optional로 추가.

세금 필드 의미론 (불변식):
  - gross_pv_krw == gross_pv_usd × reporting_fx_rate
  - net_pv_krw == gross_pv_krw − tax_unpaid_krw
  - tax_assessed_krw >= tax_unpaid_krw  (납부하면 unpaid 줄어듦)
  - C/O 모드 + 양수 수익 → tax_assessed_krw == 0 (매도 없으므로)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

import numpy as np


# ══════════════════════════════════════════════
# 입력 계약
# ══════════════════════════════════════════════

class AccountType(str, Enum):
    TAXABLE = "TAXABLE"
    ISA = "ISA"


class RebalanceMode(str, Enum):
    CONTRIBUTION_ONLY = "CONTRIBUTION_ONLY"
    FULL = "FULL"
    BUDGET = "BUDGET"  # TODO: 미구현. 세금 예산 이내에서만 FULL


@dataclass(frozen=True)
class TaxConfig:
    """세금 규칙."""
    capital_gains_rate: float = 0.22
    annual_exemption: float = 2_500_000.0
    isa_exempt_limit: float = 2_000_000.0


@dataclass(frozen=True)
class AccountConfig:
    """계좌 1개 설정."""
    account_id: str
    account_type: AccountType
    monthly_contribution: float
    rebalance_mode: RebalanceMode = RebalanceMode.CONTRIBUTION_ONLY
    tax_config: TaxConfig = field(default_factory=TaxConfig)
    annual_cap: Optional[float] = None  # ISA 연간 한도. TODO: runner에서 cap 체크 미구현
    lot_method: str = "AVGCOST"         # TODO: FIFO/HIFO 미구현, AVGCOST만 지원
    allowed_assets: Optional[set] = None  # TODO: runner에서 필터링 미구현
    transaction_cost_bps: float = 0.0    # 거래비용 (basis points, 매수/매도 각각 적용)


@dataclass(frozen=True)
class StrategyConfig:
    """전략 설정 (facade 레벨)."""
    name: str
    weights: Dict[str, float]  # asset → weight, 합 <= 1.0
    rebalance_every: int = 1   # N개월마다 리밸


@dataclass(frozen=True)
class BacktestConfig:
    """백테스트 실행 설정 — facade 단일 진입점 입력."""
    accounts: List[AccountConfig]
    strategy: StrategyConfig
    n_months: Optional[int] = None  # None이면 데이터 전체
    start_index: int = 0


# ══════════════════════════════════════════════
# 출력 계약
# ══════════════════════════════════════════════

@dataclass(frozen=True)
class AccountSummary:
    """계좌 1개 결과."""
    account_id: str
    account_type: str
    gross_pv_usd: float
    invested_usd: float
    tax_assessed_krw: float
    tax_unpaid_krw: float
    mdd: float
    n_months: int

    @property
    def mult_pre_tax(self) -> float:
        if self.invested_usd <= 0:
            return 0.0
        return self.gross_pv_usd / self.invested_usd


@dataclass(frozen=True)
class TaxSummary:
    """전체 세금 요약."""
    total_assessed_krw: float
    total_unpaid_krw: float
    total_paid_krw: float  # assessed - unpaid

    def __post_init__(self):
        # 불변식 검증
        diff = abs(self.total_assessed_krw - self.total_unpaid_krw - self.total_paid_krw)
        if diff > 1.0:  # KRW 1원 허용
            raise ValueError(
                f"TaxSummary 불변식 위반: assessed({self.total_assessed_krw:.0f}) "
                f"!= paid({self.total_paid_krw:.0f}) + unpaid({self.total_unpaid_krw:.0f})"
            )


@dataclass(frozen=True)
class EngineResult:
    """엔진 백테스트 최종 결과 — typed, 불변.

    dict 금지. 모든 필드가 명시적.
    """
    # ── 코어 ──
    gross_pv_usd: float
    invested_usd: float
    net_pv_krw: float
    gross_pv_krw: float
    reporting_fx_rate: float
    mdd: float
    n_months: int
    n_accounts: int

    # ── 세금 ──
    tax: TaxSummary

    # ── 계좌별 ──
    accounts: List[AccountSummary]

    # ── 시계열 ──
    monthly_values: np.ndarray  # 월별 합산 PV (USD)

    def __post_init__(self):
        """생성 시 불변식 검증."""
        # gross_pv_krw ≈ gross_pv_usd × fx_rate
        if self.reporting_fx_rate > 0:
            expected = self.gross_pv_usd * self.reporting_fx_rate
            if abs(self.gross_pv_krw - expected) > 1.0:
                raise ValueError(
                    f"gross_pv_krw({self.gross_pv_krw:.0f}) != "
                    f"gross_pv_usd({self.gross_pv_usd:.2f}) × "
                    f"fx({self.reporting_fx_rate:.2f}) = {expected:.0f}"
                )

        # net = gross - unpaid
        expected_net = self.gross_pv_krw - self.tax.total_unpaid_krw
        if abs(self.net_pv_krw - expected_net) > 1.0:
            raise ValueError(
                f"net_pv_krw({self.net_pv_krw:.0f}) != "
                f"gross({self.gross_pv_krw:.0f}) - unpaid({self.tax.total_unpaid_krw:.0f})"
            )

    @property
    def mult_pre_tax(self) -> float:
        if self.invested_usd <= 0:
            return 0.0
        return self.gross_pv_usd / self.invested_usd

    @property
    def mult_after_tax(self) -> float:
        if self.invested_usd <= 0:
            return 0.0
        if self.reporting_fx_rate <= 0:
            return self.mult_pre_tax
        return (self.net_pv_krw / self.reporting_fx_rate) / self.invested_usd

    @property
    def tax_drag(self) -> float:
        if self.gross_pv_krw <= 0:
            return 0.0
        return 1.0 - self.net_pv_krw / self.gross_pv_krw
