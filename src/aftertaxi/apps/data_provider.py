# -*- coding: utf-8 -*-
"""
apps/data_provider.py — 앱용 데이터 공급자
============================================
Streamlit/CLI/API가 데이터를 직접 로드하지 않고,
이 모듈을 통해 일관된 인터페이스로 가져감.

데이터 소스:
  synthetic:  합성 데이터 (데모/테스트용)
  yfinance:   yfinance 직접 로드 (설치 필요)
  lane_a:     Lane A 로더 (Alpha Vantage + FRED)

사용법:
  from aftertaxi.apps.data_provider import load_market_data

  data = load_market_data(
      assets=["SPY", "QQQ"],
      source="yfinance",
      n_months=240,
  )
  # data["returns"], data["prices"], data["fx"]
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


@dataclass
class MarketData:
    """앱에서 사용하는 시장 데이터."""
    returns: pd.DataFrame
    prices: pd.DataFrame
    fx: pd.Series
    source: str
    n_months: int
    start_date: Optional[pd.Timestamp] = None
    end_date: Optional[pd.Timestamp] = None


def load_synthetic(
    assets: List[str],
    n_months: int = 240,
    annual_growth: float = 0.08,
    annual_vol: float = 0.16,
    fx_rate: float = 1300.0,
    seed: int = 42,
) -> MarketData:
    """합성 데이터 생성."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2005-01-31", periods=n_months, freq="ME")
    mu = annual_growth / 12
    sigma = annual_vol / np.sqrt(12)

    data = {a: rng.normal(mu, sigma, n_months) for a in assets}
    returns = pd.DataFrame(data, index=idx)
    prices = 100.0 * (1 + returns).cumprod()
    fx = pd.Series(fx_rate, index=idx)

    return MarketData(
        returns=returns, prices=prices, fx=fx,
        source="synthetic", n_months=n_months,
        start_date=idx[0], end_date=idx[-1],
    )


def load_yfinance(
    assets: List[str],
    start: str = "2006-01-01",
    end: Optional[str] = None,
    fx_rate: float = 1300.0,
) -> MarketData:
    """yfinance에서 실제 ETF 가격 로드.

    FX는 고정 (FRED 없이 간단히).
    """
    try:
        import yfinance as yf
    except ImportError:
        raise ImportError("yfinance 필요: pip install yfinance")

    raw = yf.download(assets, start=start, end=end, progress=False)

    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]
    else:
        close = raw[["Close"]].rename(columns={"Close": assets[0]})

    monthly = close.resample("ME").last().dropna()
    returns = monthly.pct_change().dropna()

    # 공통 인덱스
    prices = monthly.loc[returns.index]
    fx = pd.Series(fx_rate, index=returns.index)

    return MarketData(
        returns=returns, prices=prices, fx=fx,
        source="yfinance", n_months=len(returns),
        start_date=returns.index[0], end_date=returns.index[-1],
    )


def load_yfinance_with_fx(
    assets: List[str],
    start: str = "2006-01-01",
    end: Optional[str] = None,
) -> MarketData:
    """yfinance에서 ETF 가격 + USDKRW 환율 로드."""
    try:
        import yfinance as yf
    except ImportError:
        raise ImportError("yfinance 필요: pip install yfinance")

    # 자산 가격
    tickers = assets + ["KRW=X"]
    raw = yf.download(tickers, start=start, end=end, progress=False)

    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]
    else:
        close = raw

    # 자산과 FX 분리
    asset_cols = [c for c in close.columns if c in assets]
    monthly_prices = close[asset_cols].resample("ME").last().dropna()

    # USDKRW
    if "KRW=X" in close.columns:
        fx_raw = close["KRW=X"].resample("ME").last().dropna()
    else:
        fx_raw = pd.Series(1300.0, index=monthly_prices.index)

    # 공통 인덱스
    common = monthly_prices.index.intersection(fx_raw.index)
    prices = monthly_prices.loc[common]
    fx = fx_raw.loc[common]
    returns = prices.pct_change().dropna()

    prices = prices.loc[returns.index]
    fx = fx.loc[returns.index]

    return MarketData(
        returns=returns, prices=prices, fx=fx,
        source="yfinance+fx", n_months=len(returns),
        start_date=returns.index[0], end_date=returns.index[-1],
    )


def load_lane_a_data(
    assets: List[str],
    start: str = "2006-06-01",
    end: Optional[str] = None,
) -> MarketData:
    """Lane A 로더 사용 (Alpha Vantage + FRED)."""
    from aftertaxi.lanes.lane_a.loader import load_lane_a

    data = load_lane_a(assets, start=start, end=end)
    return MarketData(
        returns=data["returns"],
        prices=data["prices"],
        fx=data["fx_rates"],
        source="lane_a",
        n_months=data["n_months"],
        start_date=data["start_date"],
        end_date=data["end_date"],
    )


# ══════════════════════════════════════════════
# 통합 인터페이스
# ══════════════════════════════════════════════

def load_market_data(
    assets: List[str],
    source: str = "synthetic",
    **kwargs,
) -> MarketData:
    """통합 데이터 로드.

    Parameters
    ----------
    assets : 자산 티커 리스트
    source : "synthetic", "yfinance", "yfinance_fx", "lane_a"
    **kwargs : 소스별 추가 파라미터
    """
    if source == "synthetic":
        return load_synthetic(assets, **kwargs)
    elif source == "yfinance":
        return load_yfinance(assets, **kwargs)
    elif source == "yfinance_fx":
        return load_yfinance_with_fx(assets, **kwargs)
    elif source == "lane_a":
        return load_lane_a_data(assets, **kwargs)
    else:
        raise ValueError(f"Unknown source: {source}. "
                         f"Available: synthetic, yfinance, yfinance_fx, lane_a")
