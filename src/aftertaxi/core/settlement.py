# -*- coding: utf-8 -*-
"""
settlement.py — 정산 순서 캡슐화
=================================
runner에서 정산 로직을 분리. runner는 이 모듈의 함수를 한 줄 호출.

2층 구조:
  - Account-level: 계좌 내부 세금 정산
  - Person-level: 여러 계좌 합산 판단 (건보료, 종합과세 등)

현재는 Account-level만 구현. Person-level은 건보료/종합과세 추가 시 확장.

정산 순서가 중요한 이유:
  - 연말: settle_annual_tax → pay_tax (순서 바뀌면 이중 과세)
  - 최종: liquidate → settle → ISA settle → (건보료) → pay_tax
  - 새 세금 종류 추가 시 이 모듈만 수정. runner는 안 건드림.
"""
from __future__ import annotations

from typing import Dict

from aftertaxi.core.ledger import AccountLedger


# ══════════════════════════════════════════════
# Account-level Settlement
# ══════════════════════════════════════════════

def settle_year_end(
    ledgers: Dict[str, AccountLedger],
    year: int,
    fx_rate: float,
    enable_health_insurance: bool = False,
) -> None:
    """연도 전환 시 정산.

    순서:
      1. [Account] 양도소득세 정산
      2. [Account] 배당소득세 정산 (TAXABLE만)
      3. [Person]  건강보험료 (전 계좌 합산, opt-in)
      4. [Account] 세금 납부
    """
    from aftertaxi.core.tax_engine import compute_health_insurance

    # 1~2. 계좌별 세금 정산
    for ledger in ledgers.values():
        ledger.settle_annual_tax(current_year=year)
        if ledger.account_type == "TAXABLE":
            ledger.settle_dividend_tax(fx_rate)

    # 3. 건보료 (person scope, opt-in)
    if enable_health_insurance:
        total_cg_income = sum(l._last_annual_taxable_income_krw for l in ledgers.values())
        hi_result = compute_health_insurance(
            capital_gains_krw=total_cg_income,
            dividend_income_krw=0.0,  # MVP: 양도차익만
        )
        if hi_result.premium_krw > 0:
            for ledger in ledgers.values():
                if ledger.account_type == "TAXABLE":
                    ledger.apply_health_insurance(hi_result.premium_krw, fx_rate)
                    break

    # 4. 세금 납부
    for ledger in ledgers.values():
        ledger.pay_tax(fx_rate)


def settle_final(
    ledgers: Dict[str, AccountLedger],
    year: int,
    price_map: Dict[str, float],
    fx_rate: float,
    enable_health_insurance: bool = False,
) -> None:
    """최종 청산 시 정산.

    순서:
      1. [Account] 전량 청산 → 양도세 → 배당세 → ISA
      2. [Person]  건강보험료 (전 계좌 합산, opt-in)
      3. [Account] 세금 납부 + 최종 PV 기록
    """
    from aftertaxi.core.tax_engine import compute_health_insurance

    # Pass 1: 계좌별 정산
    for ledger in ledgers.values():
        ledger.liquidate(price_map, fx_rate)
        ledger.settle_annual_tax(current_year=year)
        if ledger.account_type == "TAXABLE":
            ledger.settle_dividend_tax(fx_rate)
        if ledger.isa_exempt_limit > 0:
            ledger.settle_isa()

    # Pass 2: 건보료 (person scope, opt-in)
    if enable_health_insurance:
        total_cg_income = sum(l._last_annual_taxable_income_krw for l in ledgers.values())
        hi_result = compute_health_insurance(
            capital_gains_krw=total_cg_income,
            dividend_income_krw=0.0,
        )
        if hi_result.premium_krw > 0:
            for ledger in ledgers.values():
                if ledger.account_type == "TAXABLE":
                    ledger.apply_health_insurance(hi_result.premium_krw, fx_rate)
                    break

    # Pass 3: 납부 + 기록
    for ledger in ledgers.values():
        ledger.pay_tax(fx_rate)
        ledger.record_month(replace_last=True)
