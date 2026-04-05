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

from aftertaxi.core.contracts import AccountType
from aftertaxi.core.ledger import AccountLedger
from aftertaxi.core.constants import AMOUNT_EPSILON_USD

# account_type 상수: ledger는 str로 저장하므로 enum.value로 비교
_TAXABLE = AccountType.TAXABLE.value


# ══════════════════════════════════════════════
# Account-level Settlement
# ══════════════════════════════════════════════

def _settle_post_cgt(
    ledgers: Dict[str, AccountLedger],
    fx_rate: float,
    enable_health_insurance: bool,
    settle_isa: bool = False,
) -> None:
    """CGT 정산 이후 공통 정산 순서.

    settle_year_end과 settle_final이 공유하는 핵심 로직.

    순서:
      1. [Person]  건보료용 연간 배당소득 스냅샷
      2. [Account] 배당소득세 (+ ISA if settle_isa)
      3. [Person]  건강보험료
      4. [Account] 세금 납부
    """
    from aftertaxi.core.tax_engine import (
        compute_dividend_tax, compute_health_insurance,
    )

    # 1. 건보료용 배당소득 스냅샷
    annual_div_krw = 0.0
    if enable_health_insurance:
        annual_div_krw = sum(
            l.annual_dividend_gross_usd * fx_rate
            for l in ledgers.values()
            if l.account_type == _TAXABLE
        )

    # 2. 배당소득세 (+ ISA)
    for ledger in ledgers.values():
        if ledger.account_type == _TAXABLE:
            if ledger.annual_dividend_gross_usd >= AMOUNT_EPSILON_USD:
                inputs = ledger.get_dividend_tax_inputs(fx_rate)
                result = compute_dividend_tax(**inputs)
                ledger.apply_dividend_tax_result(result)
            else:
                ledger.annual_dividend_gross_usd = 0.0
                ledger.annual_dividend_withholding_usd = 0.0
        if settle_isa and ledger.isa_exempt_limit > 0:
            from aftertaxi.core.tax_engine import compute_isa_settlement
            isa_inputs = ledger.get_isa_inputs()
            isa_result = compute_isa_settlement(**isa_inputs)
            ledger.apply_isa_result(isa_result)

    # 3. 건보료
    if enable_health_insurance:
        hi_result = compute_health_insurance(dividend_income_krw=annual_div_krw)
        if hi_result.premium_krw > 0:
            for ledger in ledgers.values():
                if ledger.account_type == _TAXABLE:
                    ledger.apply_health_insurance(hi_result.premium_krw, fx_rate)
                    break

    # 4. 세금 납부
    for ledger in ledgers.values():
        ledger.pay_tax(fx_rate)


def settle_year_end(
    ledgers: Dict[str, AccountLedger],
    year: int,
    fx_rate: float,
    enable_health_insurance: bool = False,
) -> None:
    """연도 전환 시 정산.

    순서: 양도소득세 → 배당세/건보료/납부 (공통)
    """
    from aftertaxi.core.tax_engine import compute_capital_gains_tax

    # 1. 양도소득세
    for ledger in ledgers.values():
        inputs = ledger.get_cgt_inputs(year)
        result = compute_capital_gains_tax(**inputs)
        ledger.apply_cgt_result(result)

    # 2~5. 배당세/건보료/납부 (공통)
    _settle_post_cgt(ledgers, fx_rate, enable_health_insurance)


def settle_final(
    ledgers: Dict[str, AccountLedger],
    year: int,
    price_map: Dict[str, float],
    fx_rate: float,
    enable_health_insurance: bool = False,
) -> None:
    """최종 청산 시 정산.

    순서: 청산+양도세 → 배당세/ISA/건보료/납부 (공통) → 기록
    """
    from aftertaxi.core.tax_engine import compute_capital_gains_tax

    # 1. 전량 청산 + 양도소득세
    for ledger in ledgers.values():
        ledger.liquidate(price_map, fx_rate)
        inputs = ledger.get_cgt_inputs(year)
        result = compute_capital_gains_tax(**inputs)
        ledger.apply_cgt_result(result)

    # 2~5. 배당세/ISA/건보료/납부 (공통)
    _settle_post_cgt(ledgers, fx_rate, enable_health_insurance, settle_isa=True)

    # 6. 최종 기록
    for ledger in ledgers.values():
        ledger.record_month(replace_last=True)
