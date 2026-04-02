# -*- coding: utf-8 -*-
"""
lane_a/data_contract.py — Lane A 데이터 계약
=============================================
adjusted path vs explicit-dividend path를 명확히 분리.

두 경로의 차이:
  ADJUSTED:
    - 가격에 배당이 반영됨 (adjusted close)
    - pct_change()에 배당 수익이 포함
    - dividend_schedule = None → 엔진이 배당을 별도 처리하지 않음
    - 이중 계산 위험: 이 경로에서 dividend_schedule을 켜면 배당 이중 반영

  EXPLICIT_DIVIDENDS:
    - 가격에 배당 미반영 (split-adjusted close only)
    - pct_change()는 순수 가격 변동만
    - dividend_events를 별도 제공 → 엔진이 배당을 명시적으로 처리
    - 원천징수/재투자/종합과세를 정확히 모델링 가능

사용법:
  data = load_lane_a(tickers, price_mode=PriceMode.EXPLICIT_DIVIDENDS)
  config = BacktestConfig(..., dividend_schedule=data["dividend_schedule"])
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from aftertaxi.core.dividend import DividendSchedule


class PriceMode(str, Enum):
    """가격 데이터 모드."""
    ADJUSTED = "adjusted"                       # 배당 반영된 가격 (기존)
    EXPLICIT_DIVIDENDS = "explicit_dividends"   # 배당 미반영 + 별도 이벤트


@dataclass
class LaneAData:
    """Lane A 데이터 패키지."""
    prices: pd.DataFrame          # 월별 가격 (USD)
    fx_rates: pd.Series           # 월별 환율 (USDKRW)
    returns: pd.DataFrame         # 월별 수익률
    price_mode: PriceMode         # 가격 모드
    start_date: pd.Timestamp
    end_date: pd.Timestamp
    n_months: int

    # explicit dividend path에서만 채워짐
    dividend_schedule: Optional[DividendSchedule] = None
    dividend_events_raw: Optional[pd.DataFrame] = None  # 원본 배당 이벤트

    def validate(self) -> None:
        """데이터 일관성 검증."""
        if self.price_mode == PriceMode.EXPLICIT_DIVIDENDS:
            if self.dividend_schedule is None:
                raise ValueError(
                    "EXPLICIT_DIVIDENDS 모드에서는 dividend_schedule이 필요합니다."
                )
        if self.price_mode == PriceMode.ADJUSTED:
            if self.dividend_schedule is not None:
                raise ValueError(
                    "ADJUSTED 모드에서 dividend_schedule을 쓰면 배당 이중 계산 위험. "
                    "EXPLICIT_DIVIDENDS 모드를 사용하세요."
                )


def build_dividend_schedule_from_history(
    dividend_history: pd.DataFrame,
    prices: pd.DataFrame,
    withholding_rate: float = 0.15,
    reinvest: bool = True,
) -> DividendSchedule:
    """실제 배당 이력에서 DividendSchedule을 생성.

    Parameters
    ----------
    dividend_history : DataFrame, index=date, columns=tickers, values=dividend per share
    prices : 월별 가격 (연간 수익률 계산용)

    Returns
    -------
    DividendSchedule
    """
    # 연간 배당수익률 계산 (최근 12개월 합 / 현재 가격)
    annual_yields = {}
    for ticker in dividend_history.columns:
        total_div = dividend_history[ticker].sum()
        n_years = max(len(prices) / 12, 1)
        annual_div = total_div / n_years

        last_price = prices[ticker].iloc[-1] if ticker in prices.columns else 1.0
        if last_price > 0:
            annual_yields[ticker] = annual_div / last_price
        else:
            annual_yields[ticker] = 0.0

    # 배당 빈도 추정 (연간 배당 횟수)
    # 대부분 미국 ETF는 분기 배당
    frequency = 4

    return DividendSchedule(
        annual_yields=annual_yields,
        frequency=frequency,
        withholding_rate=withholding_rate,
        reinvest=reinvest,
    )
