# -*- coding: utf-8 -*-
"""
dividend.py — 배당 이벤트 모델
===============================
해외 ETF 배당의 현금 흐름을 모델링.

설계 원칙:
  - 배당은 가격 수익률과 분리. adjusted close에 묻지 않는다.
  - 원천징수는 지급 시점에 반영.
  - 재투자 vs 현금유지는 정책 선택.
  - 배당 이벤트는 EventJournal에 기록.

사용법:
  schedule = DividendSchedule({"SPY": 0.015, "QQQ": 0.005})
  # runner가 매 분기 apply_dividend() 호출
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class DividendEvent:
    """단일 배당 이벤트."""
    asset: str
    gross_per_share_usd: float
    withholding_rate: float = 0.15   # 해외 원천징수율 (미국 15%)
    reinvest: bool = True            # True: 배당금으로 재매수, False: 현금유지

    @property
    def net_per_share_usd(self) -> float:
        return self.gross_per_share_usd * (1 - self.withholding_rate)

    @property
    def withholding_per_share_usd(self) -> float:
        return self.gross_per_share_usd * self.withholding_rate


@dataclass
class DividendSchedule:
    """자산별 연간 배당 수익률 스케줄.

    Parameters
    ----------
    annual_yields : {"SPY": 0.015, "QQQ": 0.005} — 연간 배당수익률
    frequency : 연간 배당 횟수 (4 = 분기, 12 = 월배당)
    withholding_rate : 해외 원천징수율
    reinvest : 배당 재투자 여부
    """
    annual_yields: Dict[str, float]
    frequency: int = 4               # 분기 배당이 기본
    withholding_rate: float = 0.15
    reinvest: bool = True

    def is_dividend_month(self, step: int) -> bool:
        """이번 step이 배당 지급 월인지."""
        months_per_payment = 12 // self.frequency
        # step 0 = 첫 달, 배당은 3,6,9,12월 (step 2,5,8,11)
        return (step + 1) % months_per_payment == 0

    def create_event(self, asset: str, current_price: float) -> Optional[DividendEvent]:
        """해당 자산의 배당 이벤트 생성."""
        annual_yield = self.annual_yields.get(asset, 0.0)
        if annual_yield <= 0:
            return None
        gross_per_share = current_price * annual_yield / self.frequency
        return DividendEvent(
            asset=asset,
            gross_per_share_usd=gross_per_share,
            withholding_rate=self.withholding_rate,
            reinvest=self.reinvest,
        )
