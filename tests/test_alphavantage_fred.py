import os
# -*- coding: utf-8 -*-
"""
test_alphavantage_fred.py — Alpha Vantage + FRED 로더 테스트
=============================================================
"""

import numpy as np
import pandas as pd
import pytest
from pathlib import Path
import tempfile

from aftertaxi.loaders.alphavantage import load_prices_alphavantage
from aftertaxi.loaders.fred import load_fx_fred

AV_KEY = os.environ.get("ALPHAVANTAGE_KEY", "")
FRED_KEY = os.environ.get("FRED_KEY", "")


@pytest.fixture(scope="module")
def shared_cache():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def tmp_cache():
    """개별 테스트용 (FRED 등 rate limit 없는 것)."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


# 모듈 레벨에서 SPY 데이터 한 번만 로드
@pytest.fixture(scope="module")
def spy_av_data(shared_cache):
    """SPY Alpha Vantage 데이터 — 모듈에서 1회만 로드."""
    return load_prices_alphavantage(["SPY"], AV_KEY, cache_dir=shared_cache)


# ══════════════════════════════════════════════
# Alpha Vantage
# ══════════════════════════════════════════════

class TestAlphaVantage:

    def test_loads_spy(self, spy_av_data):
        av = spy_av_data
        assert "close" in av
        assert "adjusted_close" in av
        assert "dividends" in av
        assert "SPY" in av["close"].columns

    def test_close_higher_than_adjusted_for_past(self, spy_av_data):
        """과거 close > adjusted (배당 소급 차감이므로)."""
        av = spy_av_data
        old_close = av["close"]["SPY"].iloc[0]
        old_adj = av["adjusted_close"]["SPY"].iloc[0]
        assert old_close > old_adj

    def test_dividends_sum_reasonable(self, spy_av_data):
        """SPY 연간 배당 $5~$10 범위."""
        av = spy_av_data
        d = av["dividends"]["SPY"]
        d_2024 = d.loc["2024-01-01":"2024-12-31"]
        annual = d_2024.sum()
        assert 5.0 < annual < 12.0, f"SPY 2024 연배당 {annual:.2f} 비정상"

    def test_history_depth(self, spy_av_data):
        """20년+ 이력 확인."""
        assert len(spy_av_data["close"]) > 240

    def test_cache_works(self, shared_cache):
        """캐시에서 다시 로드해도 같은 결과."""
        av1 = load_prices_alphavantage(["SPY"], AV_KEY, cache_dir=shared_cache)
        av2 = load_prices_alphavantage(["SPY"], AV_KEY, cache_dir=shared_cache)
        assert av1["close"].equals(av2["close"])


# ══════════════════════════════════════════════
# FRED FX
# ══════════════════════════════════════════════

class TestFredFx:

    def test_loads_usdkrw(self, tmp_cache):
        fx = load_fx_fred(FRED_KEY, start="2024-01-01", cache_dir=tmp_cache)
        assert isinstance(fx, pd.Series)
        assert len(fx) > 0
        assert fx.iloc[-1] > 1000  # KRW/USD > 1000

    def test_history_depth(self, tmp_cache):
        fx = load_fx_fred(FRED_KEY, start="2000-01-01", cache_dir=tmp_cache)
        assert len(fx) > 240  # 20년+

    def test_cache_works(self, tmp_cache):
        fx1 = load_fx_fred(FRED_KEY, start="2024-01-01", cache_dir=tmp_cache)
        fx2 = load_fx_fred(FRED_KEY, start="2024-01-01", cache_dir=tmp_cache)
        assert fx1.equals(fx2)


# ══════════════════════════════════════════════
# 교차 검증: Alpha Vantage vs EODHD vs yfinance
# ══════════════════════════════════════════════

class TestCrossValidation:

    def test_av_vs_yfinance_price(self, spy_av_data):
        """Alpha Vantage close ≈ yfinance Close."""
        yf = pytest.importorskip("yfinance")

        av_close = spy_av_data["close"]["SPY"].loc["2024-06-01":"2024-12-31"]

        raw = yf.download("SPY", start="2024-06-01", end="2025-01-01", progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            yf_close = raw["Close"]["SPY"]
        else:
            yf_close = raw["Close"]
        yf_monthly = yf_close.resample("ME").last().dropna()

        common = av_close.index.intersection(yf_monthly.index)
        if len(common) < 2:
            pytest.skip("공통 기간 부족")

        for dt in common:
            ratio = av_close.loc[dt] / yf_monthly.loc[dt]
            assert 0.95 < ratio < 1.05

    def test_av_vs_yfinance_dividend(self, spy_av_data):
        """Alpha Vantage 배당 ≈ yfinance 배당."""
        yf = pytest.importorskip("yfinance")

        av_div = spy_av_data["dividends"]["SPY"].loc["2024-01-01":"2024-12-31"].sum()

        tk = yf.Ticker("SPY")
        yf_divs = tk.dividends
        if yf_divs.index.tz is not None:
            yf_divs.index = yf_divs.index.tz_localize(None)
        yf_div = yf_divs.loc["2024-01-01":"2024-12-31"].sum()

        if av_div > 0 and yf_div > 0:
            ratio = av_div / yf_div
            assert 0.9 < ratio < 1.1

    def test_av_plus_fred_can_run_engine(self, spy_av_data, tmp_cache):
        """Alpha Vantage(가격+배당) + FRED(FX)로 엔진 실행."""
        from aftertaxi.core.contracts import (
            AccountConfig, AccountType, BacktestConfig, StrategyConfig,
        )
        from aftertaxi.core.facade import run_backtest
        from aftertaxi.lanes.lane_a.data_contract import build_dividend_schedule_from_history

        prices = spy_av_data["close"].loc["2020-01-01":"2024-12-31"]
        dividends = spy_av_data["dividends"].loc["2020-01-01":"2024-12-31"]
        fx = load_fx_fred(FRED_KEY, start="2020-01-01", end="2024-12-31",
                          cache_dir=tmp_cache)

        common = prices.index.intersection(fx.index)
        prices = prices.loc[common]
        fx = fx.loc[common]
        returns = prices.pct_change().fillna(0.0)
        div_schedule = build_dividend_schedule_from_history(dividends, prices)

        result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("spy_av_fred", {"SPY": 1.0}),
                dividend_schedule=div_schedule,
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        assert result.gross_pv_usd > 0
        assert result.n_months > 0
