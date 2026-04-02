# -*- coding: utf-8 -*-
"""
tax_engine.py — 세금 계산 순수 함수
====================================
상태 없음. 입력 → 풍부한 결과 객체. 테스트 가능.

ledger는 이 함수들의 결과를 받아서 자기 상태를 갱신한다.
"왜 이 세금인지"는 tax_engine이 안다. ledger는 모른다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


# ══════════════════════════════════════════════
# 결과 객체 (풍부한 반환값)
# ══════════════════════════════════════════════

@dataclass(frozen=True)
class CapitalGainsTaxResult:
    """양도소득세 계산 결과."""
    tax_krw: float
    taxable_base_krw: float           # 공제 후 과세표준
    net_gain_before_exemption: float  # 이월결손금 상쇄 후, 공제 전
    exemption_used_krw: float
    carryforward_used: List[Tuple[int, float]]      # 소진된 (연도, 금액)
    carryforward_remaining: List[Tuple[int, float]]  # 남은 (연도, 금액)
    new_loss_carry: List[Tuple[int, float]]          # 올해 새로 이월되는 손실


@dataclass(frozen=True)
class ISASettlementResult:
    """ISA 만기 정산 결과."""
    tax_krw: float
    net_gain_krw: float       # 누적 순이익
    exempt_amount_krw: float  # 비과세 적용 금액
    excess_amount_krw: float  # 초과분 (과세 대상)


# ══════════════════════════════════════════════
# 순수 함수
# ══════════════════════════════════════════════

def compute_capital_gains_tax(
    realized_gain_krw: float,
    realized_loss_krw: float,
    carryforward: List[Tuple[int, float]],
    current_year: int,
    rate: float = 0.22,
    exemption: float = 2_500_000.0,
    carry_expiry_years: int = 5,
) -> CapitalGainsTaxResult:
    """양도소득세 계산. 순수 함수 — 상태 변경 없음.

    Parameters
    ----------
    realized_gain_krw : 올해 실현이익 (KRW)
    realized_loss_krw : 올해 실현손실 (KRW, 양수)
    carryforward : 이월결손금 리스트 [(발생연도, 금액), ...]
    current_year : 정산 연도
    rate : 양도세율
    exemption : 연간 기본공제
    carry_expiry_years : 이월결손금 만료 기간

    Returns
    -------
    CapitalGainsTaxResult
    """
    net = realized_gain_krw - realized_loss_krw

    # 1. 만료되지 않은 이월결손금 필터
    valid_carry = []
    for yr, amt in carryforward:
        if current_year > 0 and yr > 0 and (current_year - yr) >= carry_expiry_years:
            continue
        if amt > 1e-6:
            valid_carry.append((yr, amt))

    # 2. 상쇄 처리
    carryforward_used = []
    carryforward_remaining = []
    new_loss_carry = []

    if net > 0:
        # 이월결손금으로 상쇄 (오래된 것부터)
        remaining_net = net
        for yr, amt in valid_carry:
            if remaining_net <= 0:
                carryforward_remaining.append((yr, amt))
                continue
            offset = min(remaining_net, amt)
            remaining_net -= offset
            carryforward_used.append((yr, offset))
            remainder = amt - offset
            if remainder > 1e-6:
                carryforward_remaining.append((yr, remainder))
        net_after_carry = remaining_net
    else:
        # 순손실 → 올해 손실 이월 + 기존 carry 유지
        if abs(net) > 1e-6:
            new_loss_carry.append((current_year, abs(net)))
        carryforward_remaining = list(valid_carry)
        net_after_carry = 0.0

    # 3. 공제 적용
    exemption_used = min(net_after_carry, exemption)
    taxable = max(0.0, net_after_carry - exemption)
    tax_krw = taxable * rate

    return CapitalGainsTaxResult(
        tax_krw=tax_krw,
        taxable_base_krw=taxable,
        net_gain_before_exemption=net_after_carry,
        exemption_used_krw=exemption_used,
        carryforward_used=carryforward_used,
        carryforward_remaining=carryforward_remaining,
        new_loss_carry=new_loss_carry,
    )


def compute_isa_settlement(
    cumulative_gain_krw: float,
    cumulative_loss_krw: float,
    exempt_limit: float = 2_000_000.0,
    excess_rate: float = 0.099,
) -> ISASettlementResult:
    """ISA 만기 정산. 순수 함수.

    Parameters
    ----------
    cumulative_gain_krw : 누적 실현이익
    cumulative_loss_krw : 누적 실현손실
    exempt_limit : 비과세 한도
    excess_rate : 초과분 세율
    """
    net = cumulative_gain_krw - cumulative_loss_krw
    exempt = min(max(net, 0.0), exempt_limit)
    excess = max(0.0, net - exempt_limit)
    tax = excess * excess_rate

    return ISASettlementResult(
        tax_krw=tax,
        net_gain_krw=net,
        exempt_amount_krw=exempt,
        excess_amount_krw=excess,
    )
