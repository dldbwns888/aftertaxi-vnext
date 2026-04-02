# -*- coding: utf-8 -*-
"""
lane_b/synthetic.py — 합성 레버리지 수익률 생성기
==================================================
Lane B: 장기 지수 데이터에서 레버리지 ETF 수익률을 합성.

합성 공식:
  synthetic_Lx = L × index_ret − financing − fee − vol_drag

  financing = (tbill / 12) × (L − 1)
  fee       = annual_fee / 12
  vol_drag  = 0.5 × (L² − L) × monthly_variance

NOTE: 월간 근사. 일중 리밸런싱 효과를 정확히 반영하지 않음.
결과는 "실행 리스크의 정확한 추정"이 아니라 "구조 검증"용.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class SyntheticParams:
    """합성 레버리지 파라미터."""
    leverage: float = 2.0
    annual_fee: float = 0.0089   # SSO: 0.89%
    vol_lookback: int = 12       # vol drag 추정 윈도우 (월)


def synthesize_leveraged_returns(
    index_returns: pd.Series,
    tbill_rate: pd.Series,
    params: SyntheticParams = None,
) -> pd.Series:
    """지수 월간 수익률 → 합성 레버리지 ETF 수익률.

    Parameters
    ----------
    index_returns : 월간 수익률 (decimal, e.g. 0.01 = 1%)
    tbill_rate : 월말 연율 수익률 (decimal, e.g. 0.05 = 5%)
    params : 합성 파라미터

    Returns
    -------
    Series: 합성 레버리지 월간 수익률
    """
    if params is None:
        params = SyntheticParams()

    L = params.leverage

    # 월간 financing cost: (tbill/12) × (leverage - 1)
    financing = (tbill_rate / 12.0) * (L - 1)

    # 월간 fee
    fee = params.annual_fee / 12.0

    # vol drag: 0.5 × (L² - L) × rolling variance
    min_p = min(2, params.vol_lookback)
    rolling_var = index_returns.rolling(params.vol_lookback, min_periods=min_p).var().fillna(0.0)
    vol_drag = 0.5 * (L**2 - L) * rolling_var

    # 합성 수익률
    synthetic = L * index_returns - financing - fee - vol_drag

    synthetic.name = f"synthetic_{L:.0f}x"
    return synthetic


def returns_to_prices(returns: pd.Series, base: float = 100.0) -> pd.Series:
    """월간 수익률 → 누적 가격."""
    return base * (1 + returns).cumprod()
