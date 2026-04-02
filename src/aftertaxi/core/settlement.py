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
      2. [Person]  건보료용 연간 배당소득 스냅샷 (배당세 리셋 전에 캡처)
      3. [Account] 배당소득세 정산 (annual_dividend 리셋)
      4. [Person]  건강보험료 (배당소득 기반, opt-in)
      5. [Account] 세금 납부

    건보료 법적 근거: 시행령 제41조 — 양도소득은 소득월액 산정 대상 아님.
    """
    from aftertaxi.core.tax_engine import compute_health_insurance

    # 1. 양도소득세 정산
    for ledger in ledgers.values():
        ledger.settle_annual_tax(current_year=year)

    # 2. 건보료용 배당소득 스냅샷 (settle_dividend_tax가 리셋하기 전에 캡처)
    annual_div_krw = 0.0
    if enable_health_insurance:
        annual_div_krw = sum(
            l.annual_dividend_gross_usd * fx_rate
            for l in ledgers.values()
            if l.account_type == "TAXABLE"
        )

    # 3. 배당소득세 정산 (annual_dividend 리셋)
    for ledger in ledgers.values():
        if ledger.account_type == "TAXABLE":
            ledger.settle_dividend_tax(fx_rate)

    # 4. 건보료 (배당소득 기반, person scope)
    # ⚠ MVP 한계: person-scope premium을 첫 번째 TAXABLE 계좌에 전액 귀속.
    #   멀티 TAXABLE 계좌일 때 계좌별 attribution이 왜곡될 수 있음.
    #   향후: 배당소득 비례 배분 또는 별도 person-level liability 필드.
    if enable_health_insurance:
        hi_result = compute_health_insurance(dividend_income_krw=annual_div_krw)
        if hi_result.premium_krw > 0:
            for ledger in ledgers.values():
                if ledger.account_type == "TAXABLE":
                    ledger.apply_health_insurance(hi_result.premium_krw, fx_rate)
                    break

    # 5. 세금 납부
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
      1. [Account] 전량 청산 → 양도세
      2. [Person]  건보료용 배당소득 스냅샷
      3. [Account] 배당세 → ISA
      4. [Person]  건보료
      5. [Account] 납부 + 기록
    """
    from aftertaxi.core.tax_engine import compute_health_insurance

    # Pass 1: 청산 + 양도세
    for ledger in ledgers.values():
        ledger.liquidate(price_map, fx_rate)
        ledger.settle_annual_tax(current_year=year)

    # 건보료용 배당소득 스냅샷 (배당세 리셋 전)
    annual_div_krw = 0.0
    if enable_health_insurance:
        annual_div_krw = sum(
            l.annual_dividend_gross_usd * fx_rate
            for l in ledgers.values()
            if l.account_type == "TAXABLE"
        )

    # Pass 2: 배당세 + ISA
    for ledger in ledgers.values():
        if ledger.account_type == "TAXABLE":
            ledger.settle_dividend_tax(fx_rate)
        if ledger.isa_exempt_limit > 0:
            ledger.settle_isa()

    # Pass 3: 건보료 (person scope → 첫 TAXABLE에 귀속, MVP 한계)
    if enable_health_insurance:
        hi_result = compute_health_insurance(dividend_income_krw=annual_div_krw)
        if hi_result.premium_krw > 0:
            for ledger in ledgers.values():
                if ledger.account_type == "TAXABLE":
                    ledger.apply_health_insurance(hi_result.premium_krw, fx_rate)
                    break

    # Pass 4: 납부 + 기록
    for ledger in ledgers.values():
        ledger.pay_tax(fx_rate)
        ledger.record_month(replace_last=True)
