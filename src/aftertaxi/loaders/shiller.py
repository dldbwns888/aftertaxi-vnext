# -*- coding: utf-8 -*-
"""
loaders/shiller.py — Shiller 152년 장기 데이터 로더
====================================================
Robert Shiller의 S&P 500 월간 데이터 (1871~현재).
코어 무관. Lane B 합성 레버리지 역사 입력용.

데이터 출처:
  http://www.econ.yale.edu/~shiller/data/ie_data.xls

포함:
  - S&P 500 월간 가격/수익률
  - 배당수익률 (연율)
  - GS10 (10년 국채 금리, T-bill 근사)
  - CPI (인플레이션)

사용법:
  from aftertaxi.loaders.shiller import load_shiller

  data = load_shiller()
  data["sp_returns"]    # 월간 S&P 수익률
  data["gs10_annual"]   # 10yr Treasury (연율)
  data["n_months"]      # 1800+
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Union

import numpy as np
import pandas as pd


_SHILLER_URL = "http://www.econ.yale.edu/~shiller/data/ie_data.xls"


def _parse_shiller_date(date_val: float) -> Optional[pd.Timestamp]:
    """1871.01 → Timestamp(1871-01-31)."""
    try:
        year = int(date_val)
        month = round((date_val - year) * 100)
        if month < 1:
            month = 1
        if month > 12:
            month = 12
        return pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)
    except (ValueError, TypeError):
        return None


def load_shiller(
    source: Union[str, Path] = _SHILLER_URL,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    cache_path: Optional[Union[str, Path]] = None,
) -> Dict[str, object]:
    """Shiller 데이터 로드 + 파싱.

    Parameters
    ----------
    source : URL 또는 로컬 파일 경로
    start_year : 시작 연도 필터 (None이면 전체)
    end_year : 종료 연도 필터
    cache_path : 로컬 캐시 경로 (None이면 캐시 안 함)

    Returns
    -------
    dict:
        sp_prices     : Series — S&P 500 월간 가격
        sp_returns    : Series — S&P 500 월간 수익률
        dividend_yield: Series — 연율 배당수익률 (D/P)
        gs10_annual   : Series — 10yr Treasury 연율 금리
        cpi           : Series — CPI
        n_months      : int
        start_date    : Timestamp
        end_date      : Timestamp
    """
    # 캐시 확인
    if cache_path and Path(cache_path).exists():
        source = cache_path

    raw = pd.read_excel(source, sheet_name="Data", header=7)

    # 날짜 파싱
    raw["date"] = raw["Date"].apply(_parse_shiller_date)
    raw = raw.dropna(subset=["date"])
    raw = raw.set_index("date").sort_index()

    # 컬럼 추출 (이름 기반)
    sp_prices = pd.to_numeric(raw["P"], errors="coerce").dropna()
    sp_prices.name = "SP500"

    # 배당 (연율)
    dividends = pd.to_numeric(raw["D"], errors="coerce").dropna()

    # GS10 (이미 % 단위)
    gs10 = pd.to_numeric(raw["Rate GS10"], errors="coerce").dropna()
    gs10 = gs10 / 100.0  # % → decimal
    gs10.name = "GS10"

    # CPI
    cpi = pd.to_numeric(raw["CPI"], errors="coerce").dropna()
    cpi.name = "CPI"

    # 수익률
    sp_returns = sp_prices.pct_change().dropna()
    sp_returns.name = "SP500_return"

    # 배당수익률 (연율)
    div_yield = (dividends / sp_prices).dropna()
    div_yield.name = "dividend_yield"

    # 연도 필터
    if start_year:
        mask = sp_returns.index.year >= start_year
        sp_returns = sp_returns[mask]
        sp_prices = sp_prices[sp_prices.index.isin(sp_returns.index) |
                              (sp_prices.index == sp_returns.index[0] - pd.offsets.MonthEnd(1))]
    if end_year:
        mask = sp_returns.index.year <= end_year
        sp_returns = sp_returns[mask]

    # 공통 인덱스
    common = sp_returns.index.intersection(gs10.index)
    sp_returns_common = sp_returns.loc[common]
    gs10_common = gs10.loc[common]

    # 캐시 저장
    if cache_path and not Path(cache_path).exists():
        try:
            import urllib.request
            urllib.request.urlretrieve(str(source), str(cache_path))
        except Exception:
            pass  # 캐시 실패는 무시

    return {
        "sp_prices": sp_prices,
        "sp_returns": sp_returns,
        "sp_returns_with_gs10": sp_returns_common,
        "gs10_annual": gs10_common,
        "dividend_yield": div_yield,
        "cpi": cpi,
        "n_months": len(sp_returns),
        "n_months_with_gs10": len(common),
        "start_date": sp_returns.index[0] if len(sp_returns) > 0 else None,
        "end_date": sp_returns.index[-1] if len(sp_returns) > 0 else None,
    }
