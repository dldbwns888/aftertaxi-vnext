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
) -> None:
    """연도 전환 시 정산. 모든 계좌에 대해 실행.

    순서:
      1. 양도소득세 정산 (연간 실현손익 → 세금 계산)
      2. 세금 납부 (KRW → USD cash 차감)

    향후 추가될 것:
      - 배당소득 정산
      - 건보료 (person-level로 승격 예정)
      - 외국납부세액공제
    """
    for ledger in ledgers.values():
        ledger.settle_annual_tax(current_year=year)
        ledger.pay_tax(fx_rate)


def settle_final(
    ledgers: Dict[str, AccountLedger],
    year: int,
    price_map: Dict[str, float],
    fx_rate: float,
) -> None:
    """최종 청산 시 정산. 순서가 더 중요하다.

    순서:
      1. 전량 청산 (매도 → 실현손익)
      2. 양도소득세 정산 (마지막 연도)
      3. ISA 만기 정산 (해당 계좌만)
      4. [TODO] 건보료
      5. [TODO] 외국납부세액공제 최종 정산
      6. 세금 납부
      7. 최종 PV로 마지막 월 갱신

    향후 추가될 것:
      - 건보료 (person scope)
      - 외국납부세액공제
      - 연금 계좌 수령 시 과세
    """
    for ledger in ledgers.values():
        # 1. 전량 청산
        ledger.liquidate(price_map, fx_rate)
        # 2. 양도소득세 정산
        ledger.settle_annual_tax(current_year=year)
        # 3. ISA 만기 정산
        if ledger.isa_exempt_limit > 0:
            ledger.settle_isa()
        # 4. 세금 납부
        ledger.pay_tax(fx_rate)
        # 5. 최종 PV 기록
        ledger.record_month(replace_last=True)
