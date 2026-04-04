# -*- coding: utf-8 -*-
"""
test_lane_a_loader.py — Lane A 배당 로더 + explicit mode 테스트
===============================================================
yfinance 실데이터 사용. 네트워크 필요.
"""

import numpy as np
import pandas as pd
import pytest
from pathlib import Path
import tempfile

# yfinance가 없으면 전체 스킵
yf = pytest.importorskip("yfinance")

from aftertaxi.lanes.lane_a.loader import (
    load_dividends, load_lane_a, load_lane_a_explicit,
)
from aftertaxi.lanes.lane_a.data_contract import PriceMode


@pytest.fixture
def tmp_cache():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


# ══════════════════════════════════════════════
# load_dividends
# ══════════════════════════════════════════════

class TestLoadDividends:

    def test_loads_spy_dividends(self, tmp_cache):
        """SPY 배당 이력 로드."""
        divs = load_dividends(
            ["SPY"], start="2023-01-01", end="2024-01-01",
            cache_dir=tmp_cache,
        )
        assert isinstance(divs, pd.DataFrame)
        assert "SPY" in divs.columns
        # SPY는 분기 배당 → 최소 3~4건
        assert divs["SPY"].sum() > 0

    def test_monthly_aggregation(self, tmp_cache):
        """배당이 월별로 합산."""
        divs = load_dividends(
            ["SPY"], start="2023-01-01", end="2024-01-01",
            cache_dir=tmp_cache,
        )
        # 인덱스가 월말
        assert divs.index.freqstr == "ME" or all(
            d.is_month_end for d in divs.index
        )

    def test_cache_works(self, tmp_cache):
        """두 번째 로드는 캐시에서."""
        divs1 = load_dividends(["SPY"], start="2023-01-01", end="2024-01-01",
                                cache_dir=tmp_cache)
        divs2 = load_dividends(["SPY"], start="2023-01-01", end="2024-01-01",
                                cache_dir=tmp_cache)
        assert divs1.equals(divs2)

    def test_multi_ticker(self, tmp_cache):
        """여러 티커 동시 로드."""
        divs = load_dividends(
            ["SPY", "QQQ"], start="2023-01-01", end="2024-01-01",
            cache_dir=tmp_cache,
        )
        assert "SPY" in divs.columns
        assert "QQQ" in divs.columns


# ══════════════════════════════════════════════
# load_lane_a_explicit (AV + FRED 기반)
# ══════════════════════════════════════════════

AV_KEY = "1F77HAKH3TOIU5DZ"
FRED_KEY = "f8808fc62203cc8e92829766b2fde343"


@pytest.fixture(scope="module")
def explicit_data():
    """모듈 스코프: AV+FRED로 한 번만 로드."""
    return load_lane_a_explicit(
        ["SPY"], start="2020-01-01", end="2024-12-31",
        av_key=AV_KEY, fred_key=FRED_KEY,
    )


class TestLoadLaneAExplicit:

    def test_returns_lane_a_data(self, explicit_data):
        from aftertaxi.lanes.lane_a.data_contract import LaneAData
        assert isinstance(explicit_data, LaneAData)
        assert explicit_data.price_mode == PriceMode.EXPLICIT_DIVIDENDS

    def test_has_dividend_schedule(self, explicit_data):
        assert explicit_data.dividend_schedule is not None
        assert "SPY" in explicit_data.dividend_schedule.annual_yields
        assert explicit_data.dividend_schedule.annual_yields["SPY"] > 0

    def test_validates_ok(self, explicit_data):
        explicit_data.validate()

    def test_dividend_events_raw(self, explicit_data):
        assert explicit_data.dividend_events_raw is not None
        assert "SPY" in explicit_data.dividend_events_raw.columns

    def test_prices_are_unadjusted(self, explicit_data):
        """가격이 AV close (배당 미반영)인지 확인.
        AV close > yfinance Close (yfinance는 배당 반영)."""
        yf = pytest.importorskip("yfinance")
        raw = yf.download("SPY", start="2024-01-01", end="2025-01-01", progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            yf_close = raw["Close"]["SPY"]
        else:
            yf_close = raw["Close"]
        yf_monthly = yf_close.resample("ME").last().dropna()

        av_prices = explicit_data.prices["SPY"]
        common = av_prices.index.intersection(yf_monthly.index)
        if len(common) > 0:
            # AV close > yfinance Close (배당 차이)
            last = common[-1]
            assert av_prices.loc[last] > yf_monthly.loc[last], \
                "AV close가 yfinance보다 높아야 함 (배당 미반영 vs 반영)"

    def test_backward_compat_load_lane_a(self, tmp_cache):
        """기존 load_lane_a()는 dict 반환 (변경 없음)."""
        data = load_lane_a(
            ["SPY"], start="2023-01-01", end="2024-01-01",
            cache_dir=tmp_cache,
        )
        assert isinstance(data, dict)
        assert "prices" in data

    def test_explicit_can_run_engine(self, explicit_data):
        """explicit mode 데이터로 엔진 실행."""
        from aftertaxi.core.contracts import (
            AccountConfig, AccountType, BacktestConfig, StrategyConfig,
        )
        from aftertaxi.core.facade import run_backtest

        result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("spy_explicit", {"SPY": 1.0}),
                dividend_schedule=explicit_data.dividend_schedule,
            ),
            returns=explicit_data.returns,
            prices=explicit_data.prices,
            fx_rates=explicit_data.fx_rates,
        )

        assert result.gross_pv_usd > 0
        assert result.n_months > 0
