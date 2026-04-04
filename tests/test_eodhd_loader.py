import os
# -*- coding: utf-8 -*-
"""
test_eodhd_loader.py — EODHD 로더 테스트 + yfinance 교차 검증
===============================================================
"""

import numpy as np
import pandas as pd
import pytest
from pathlib import Path
import tempfile

from aftertaxi.loaders import (
    load_prices_eodhd, load_dividends_eodhd, load_fx_eodhd,
    dividends_to_monthly, DividendRecord,
)

API_TOKEN = os.environ.get("EODHD_KEY", "")


@pytest.fixture
def tmp_cache():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


# ══════════════════════════════════════════════
# 가격 로더
# ══════════════════════════════════════════════

class TestLoadPricesEodhd:

    def test_loads_spy(self, tmp_cache):
        result = load_prices_eodhd(["SPY"], API_TOKEN, start="2024-06-01",
                                    cache_dir=tmp_cache)
        assert "close" in result
        assert "adjusted_close" in result
        assert "SPY" in result["close"].columns

    def test_close_and_adjusted_differ(self, tmp_cache):
        """close(배당 미반영)과 adjusted_close(배당 반영)이 다르다."""
        result = load_prices_eodhd(["SPY"], API_TOKEN, start="2024-06-01",
                                    cache_dir=tmp_cache)
        close = result["close"]["SPY"]
        adj = result["adjusted_close"]["SPY"]

        if len(close) > 0 and len(adj) > 0:
            # adjusted는 배당이 반영되어 약간 낮아야 (과거로 갈수록)
            # 또는 최근은 거의 같고 과거일수록 차이
            assert not close.equals(adj) or len(close) == 1

    def test_cache_works(self, tmp_cache):
        r1 = load_prices_eodhd(["SPY"], API_TOKEN, start="2024-06-01",
                                cache_dir=tmp_cache)
        r2 = load_prices_eodhd(["SPY"], API_TOKEN, start="2024-06-01",
                                cache_dir=tmp_cache)
        assert r1["close"].equals(r2["close"])


# ══════════════════════════════════════════════
# 배당 로더
# ══════════════════════════════════════════════

class TestLoadDividendsEodhd:

    def test_loads_spy_dividends(self, tmp_cache):
        divs = load_dividends_eodhd(["SPY"], API_TOKEN, start="2024-01-01",
                                     cache_dir=tmp_cache)
        assert "SPY" in divs
        assert len(divs["SPY"]) >= 3  # SPY 분기배당 → 최소 3건/년

    def test_dividend_fields(self, tmp_cache):
        divs = load_dividends_eodhd(["SPY"], API_TOKEN, start="2024-01-01",
                                     cache_dir=tmp_cache)
        rec = divs["SPY"][0]
        assert isinstance(rec, DividendRecord)
        assert rec.ex_date != ""
        assert rec.pay_date != ""
        assert rec.value > 0

    def test_to_monthly(self, tmp_cache):
        divs = load_dividends_eodhd(["SPY"], API_TOKEN, start="2024-01-01",
                                     cache_dir=tmp_cache)
        monthly = dividends_to_monthly(divs, date_field="pay_date")
        assert isinstance(monthly, pd.DataFrame)
        assert "SPY" in monthly.columns
        assert monthly["SPY"].sum() > 0


# ══════════════════════════════════════════════
# FX 로더
# ══════════════════════════════════════════════

class TestLoadFxEodhd:

    def test_loads_usdkrw(self, tmp_cache):
        fx = load_fx_eodhd(API_TOKEN, start="2024-06-01", cache_dir=tmp_cache)
        assert isinstance(fx, pd.Series)
        assert len(fx) > 0
        assert fx.iloc[-1] > 1000  # USDKRW > 1000


# ══════════════════════════════════════════════
# yfinance 교차 검증
# ══════════════════════════════════════════════

class TestCrossValidation:

    def test_price_similar_to_yfinance(self, tmp_cache):
        """EODHD close와 yfinance Close가 비슷."""
        yf = pytest.importorskip("yfinance")

        # EODHD
        eodhd = load_prices_eodhd(["SPY"], API_TOKEN, start="2024-06-01",
                                   cache_dir=tmp_cache)
        eodhd_close = eodhd["close"]["SPY"]

        # yfinance
        raw = yf.download("SPY", start="2024-06-01", progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            yf_close = raw["Close"]["SPY"]
        else:
            yf_close = raw["Close"]
        yf_monthly = yf_close.resample("ME").last().dropna()

        # 공통 날짜
        common = eodhd_close.index.intersection(yf_monthly.index)
        if len(common) < 2:
            pytest.skip("공통 기간 부족")

        e = eodhd_close.loc[common].values
        y = yf_monthly.loc[common].values

        # 5% 이내로 비슷해야
        for i in range(len(common)):
            ratio = e[i] / y[i] if y[i] != 0 else 1.0
            assert 0.95 < ratio < 1.05, (
                f"{common[i]}: EODHD {e[i]:.2f} vs yfinance {y[i]:.2f}"
            )

    def test_dividend_similar_to_yfinance(self, tmp_cache):
        """EODHD 배당 합계와 yfinance 배당 합계가 비슷."""
        yf = pytest.importorskip("yfinance")

        # EODHD
        divs_eodhd = load_dividends_eodhd(["SPY"], API_TOKEN,
                                            start="2024-01-01", end="2025-01-01",
                                            cache_dir=tmp_cache)
        eodhd_total = sum(r.value for r in divs_eodhd["SPY"])

        # yfinance
        tk = yf.Ticker("SPY")
        yf_divs = tk.dividends
        if yf_divs.index.tz is not None:
            yf_divs.index = yf_divs.index.tz_localize(None)
        yf_2024 = yf_divs.loc["2024-01-01":"2025-01-01"]
        yf_total = yf_2024.sum()

        # 10% 이내
        if eodhd_total > 0 and yf_total > 0:
            ratio = eodhd_total / yf_total
            assert 0.9 < ratio < 1.1, (
                f"EODHD total {eodhd_total:.3f} vs yfinance {yf_total:.3f}"
            )
