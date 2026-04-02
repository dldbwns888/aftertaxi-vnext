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


# ══════════════════════════════════════════════
# 배당소득세 (금융소득 기초)
# ══════════════════════════════════════════════

@dataclass(frozen=True)
class DividendTaxResult:
    """배당소득세 계산 결과.

    한국 해외 ETF 배당 과세 구조:
      - 해외 원천징수 15% (지급 시점에 이미 차감됨)
      - 국내 금융소득 2천만원 이하: 원천징수로 종결 (분리과세)
      - 2천만원 초과: 종합과세 대상 (추가 세금 발생 가능)
      - 외국납부세액공제: 해외에서 낸 세금을 국내 세금에서 공제
    """
    annual_dividend_gross_krw: float     # 연간 배당 총액 (KRW 환산)
    annual_withholding_krw: float        # 연간 해외 원천징수액 (KRW 환산)
    is_comprehensive: bool               # 종합과세 대상 여부
    foreign_tax_credit_krw: float        # 외국납부세액공제 가능 금액
    additional_tax_krw: float            # 추가 납부 세금 (종합과세 시)
    # 종합과세 미만이면 additional_tax = 0 (원천징수로 종결)


def compute_dividend_tax(
    annual_dividend_gross_usd: float,
    annual_withholding_usd: float,
    fx_rate: float,
    comprehensive_threshold_krw: float = 20_000_000.0,
    domestic_dividend_rate: float = 0.154,  # 배당소득 원천징수율 15.4%
) -> DividendTaxResult:
    """배당소득세 계산. 순수 함수.

    Parameters
    ----------
    annual_dividend_gross_usd : 연간 배당 총액 (USD)
    annual_withholding_usd : 연간 해외 원천징수액 (USD)
    fx_rate : 환산 환율
    comprehensive_threshold_krw : 금융소득 종합과세 기준 (2천만원)
    domestic_dividend_rate : 국내 배당소득 원천징수율

    Returns
    -------
    DividendTaxResult

    Note
    ----
    종합과세 시 실제 세율은 다른 소득에 따라 달라진다.
    MVP에서는 domestic_dividend_rate를 기본 세율로 사용.
    """
    gross_krw = annual_dividend_gross_usd * fx_rate
    withholding_krw = annual_withholding_usd * fx_rate

    is_comprehensive = gross_krw > comprehensive_threshold_krw

    if not is_comprehensive:
        # 분리과세: 해외 원천징수로 종결. 추가 세금 없음.
        return DividendTaxResult(
            annual_dividend_gross_krw=gross_krw,
            annual_withholding_krw=withholding_krw,
            is_comprehensive=False,
            foreign_tax_credit_krw=0.0,
            additional_tax_krw=0.0,
        )

    # 종합과세: 국내 세율 적용 후 외국납부세액공제
    domestic_tax = gross_krw * domestic_dividend_rate
    credit = min(withholding_krw, domestic_tax)  # 공제는 국내 세액 한도
    additional = max(0.0, domestic_tax - credit)

    return DividendTaxResult(
        annual_dividend_gross_krw=gross_krw,
        annual_withholding_krw=withholding_krw,
        is_comprehensive=True,
        foreign_tax_credit_krw=credit,
        additional_tax_krw=additional,
    )


# ══════════════════════════════════════════════
# 건강보험료 (직장가입자 보수 외 소득월액보험료 근사)
# ══════════════════════════════════════════════

@dataclass(frozen=True)
class HealthInsuranceResult:
    """건강보험료 계산 결과.

    근사 대상: 직장가입자 보수 외 소득월액보험료 중 투자소득 부분.

    법적 근거:
      - 국민건강보험법 시행령 제41조: 소득월액 산정 대상 소득
        → 이자, 배당, 사업, 근로, 연금, 기타소득
        → 양도소득은 포함 목록에 없음
      - 기준: 보수 외 소득 연 2천만원 초과 시 소득월액보험료 부과

    MVP 한계:
      - 직장가입자만 근사 (지역가입자 세대단위 모델 미포함)
      - 이자/사업/근로/연금/기타소득 미포함 (배당소득만)
      - 피부양자 탈락 판정 없음
    """
    dividend_income_krw: float    # 연간 배당소득 (KRW)
    threshold_krw: float          # 부과 기준 (2천만원)
    is_subject: bool              # 부과 대상 여부
    premium_krw: float            # 추가 건보료


def compute_health_insurance(
    dividend_income_krw: float,
    threshold_krw: float = 20_000_000.0,
    rate: float = 0.0699,
    annual_cap_krw: float = 40_000_000.0,
) -> HealthInsuranceResult:
    """직장가입자 보수 외 소득월액보험료 근사. 순수 함수.

    양도소득은 시행령 제41조 소득월액 산정 대상에 포함되지 않으므로
    배당소득만 사용한다.

    Parameters
    ----------
    dividend_income_krw : 연간 배당소득 (KRW)
    threshold_krw : 부과 기준 (2천만원, 보수 외 소득)
    rate : 건보료율 (6.99% ≈ 건강보험 3.545% × 2 + 장기요양)
    annual_cap_krw : 연간 상한
    """
    is_subject = dividend_income_krw > threshold_krw

    if not is_subject:
        return HealthInsuranceResult(
            dividend_income_krw=dividend_income_krw,
            threshold_krw=threshold_krw,
            is_subject=False,
            premium_krw=0.0,
        )

    taxable = dividend_income_krw - threshold_krw
    premium = min(taxable * rate, annual_cap_krw)

    return HealthInsuranceResult(
        dividend_income_krw=dividend_income_krw,
        threshold_krw=threshold_krw,
        is_subject=True,
        premium_krw=premium,
    )
