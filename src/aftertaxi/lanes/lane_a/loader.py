# -*- coding: utf-8 -*-
"""
lane_a/loader.py — 실제 ETF + FX 데이터 로더
=============================================
Lane A: 실제 시장 데이터로 백테스트.

데이터 소스:
  - ETF 가격: yfinance (월말 adjusted close)
  - FX 환율: yfinance KRW=X (월말)

캐시:
  - 첫 로드 시 parquet 저장
  - 이후 캐시 사용 (max_age 이내)
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import pandas as pd


# ══════════════════════════════════════════════
# 캐시 경로
# ══════════════════════════════════════════════

_DEFAULT_CACHE_DIR = Path.home() / ".aftertaxi" / "cache"


# ══════════════════════════════════════════════
# ETF 가격 로더
# ══════════════════════════════════════════════

def load_prices(
    tickers: List[str],
    start: str = "2006-01-01",
    end: Optional[str] = None,
    cache_dir: Optional[Path] = None,
) -> pd.DataFrame:
    """실제 ETF 월별 adjusted close (USD).

    Parameters
    ----------
    tickers : ["QQQ", "SSO", "SPY"] 등
    start : 시작일
    end : 종료일 (None이면 현재)
    cache_dir : 캐시 디렉토리

    Returns
    -------
    DataFrame: index=DatetimeIndex(month-end), columns=tickers, values=USD price
    """
    cache_dir = cache_dir or _DEFAULT_CACHE_DIR
    cache_file = cache_dir / f"prices_{'_'.join(sorted(tickers))}_{start}.parquet"

    if cache_file.exists():
        df = pd.read_parquet(cache_file)
        # 캐시된 데이터에 필요한 티커가 다 있으면 사용
        if all(t in df.columns for t in tickers):
            df = df[tickers]
            if end:
                df = df.loc[:end]
            return df

    # yfinance 다운로드
    try:
        import yfinance as yf
    except ImportError:
        raise ImportError("yfinance가 필요합니다: pip install yfinance")

    raw = yf.download(tickers, start=start, end=end, progress=False)

    # yfinance 1.2+: MultiIndex columns 처리
    if isinstance(raw.columns, pd.MultiIndex):
        df = raw["Close"]
    else:
        df = raw[["Close"]] if len(tickers) == 1 else raw
        if len(tickers) == 1:
            df.columns = tickers

    # 월말 리샘플링
    df = df.resample("ME").last().dropna(how="all")

    # 캐시 저장
    cache_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache_file)

    if end:
        df = df.loc[:end]
    return df


# ══════════════════════════════════════════════
# FX 환율 로더
# ══════════════════════════════════════════════

def load_fx_rates(
    start: str = "2006-01-01",
    end: Optional[str] = None,
    cache_dir: Optional[Path] = None,
) -> pd.Series:
    """USDKRW 월말 환율.

    Returns
    -------
    Series: index=DatetimeIndex(month-end), values=USDKRW rate
    """
    cache_dir = cache_dir or _DEFAULT_CACHE_DIR
    cache_file = cache_dir / f"fx_usdkrw_{start}.parquet"

    if cache_file.exists():
        df = pd.read_parquet(cache_file)
        series = df.iloc[:, 0]
        if end:
            series = series.loc[:end]
        return series

    try:
        import yfinance as yf
    except ImportError:
        raise ImportError("yfinance가 필요합니다: pip install yfinance")

    raw = yf.download("KRW=X", start=start, end=end, progress=False)

    if isinstance(raw.columns, pd.MultiIndex):
        series = raw["Close"].iloc[:, 0]
    elif "Close" in raw.columns:
        series = raw["Close"]
    else:
        series = raw.iloc[:, 0]

    series = series.resample("ME").last().dropna()
    series.name = "USDKRW"

    # 캐시 저장
    cache_dir.mkdir(parents=True, exist_ok=True)
    series.to_frame().to_parquet(cache_file)

    if end:
        series = series.loc[:end]
    return series


# ══════════════════════════════════════════════
# Lane A 통합 로더
# ══════════════════════════════════════════════

def load_lane_a(
    tickers: List[str],
    start: str = "2006-06-01",
    end: Optional[str] = None,
    cache_dir: Optional[Path] = None,
) -> dict:
    """Lane A 데이터 일괄 로드.

    Returns
    -------
    dict with:
      prices: DataFrame (monthly, USD)
      fx_rates: Series (monthly, USDKRW)
      returns: DataFrame (monthly returns)
      start_date: Timestamp
      end_date: Timestamp
    """
    prices = load_prices(tickers, start=start, end=end, cache_dir=cache_dir)
    fx_rates = load_fx_rates(start=start, end=end, cache_dir=cache_dir)

    # 공통 인덱스 정렬
    common_idx = prices.index.intersection(fx_rates.index)
    prices = prices.loc[common_idx]
    fx_rates = fx_rates.loc[common_idx]

    returns = prices.pct_change().fillna(0.0)

    return {
        "prices": prices,
        "fx_rates": fx_rates,
        "returns": returns,
        "start_date": common_idx[0],
        "end_date": common_idx[-1],
        "n_months": len(common_idx),
    }
