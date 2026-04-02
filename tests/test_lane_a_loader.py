# -*- coding: utf-8 -*-
"""
test_lane_a_loader.py — Lane A 배당 로더 + explicit mode 테스트
===============================================================
yfinance 실데이터 사용. 네트워크 필요.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

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
# load_lane_a_explicit
# ══════════════════════════════════════════════

class TestLoadLaneAExplicit:

    def test_returns_lane_a_data(self, tmp_cache):
        """LaneAData 객체 반환."""
        from aftertaxi.lanes.lane_a.data_contract import LaneAData
        data = load_lane_a_explicit(
            ["SPY"], start="2023-01-01", end="2024-01-01",
            cache_dir=tmp_cache,
        )
        assert isinstance(data, LaneAData)
        assert data.price_mode == PriceMode.EXPLICIT_DIVIDENDS

    def test_has_dividend_schedule(self, tmp_cache):
        """dividend_schedule이 채워져 있다."""
        data = load_lane_a_explicit(
            ["SPY"], start="2023-01-01", end="2024-01-01",
            cache_dir=tmp_cache,
        )
        assert data.dividend_schedule is not None
        assert "SPY" in data.dividend_schedule.annual_yields
        assert data.dividend_schedule.annual_yields["SPY"] > 0

    def test_validates_ok(self, tmp_cache):
        """validate() 통과."""
        data = load_lane_a_explicit(
            ["SPY"], start="2023-01-01", end="2024-01-01",
            cache_dir=tmp_cache,
        )
        data.validate()  # 에러 없어야

    def test_dividend_events_raw(self, tmp_cache):
        """원본 배당 이벤트가 보존."""
        data = load_lane_a_explicit(
            ["SPY"], start="2023-01-01", end="2024-01-01",
            cache_dir=tmp_cache,
        )
        assert data.dividend_events_raw is not None
        assert "SPY" in data.dividend_events_raw.columns

    def test_backward_compat_load_lane_a(self, tmp_cache):
        """기존 load_lane_a()는 dict 반환 (변경 없음)."""
        data = load_lane_a(
            ["SPY"], start="2023-01-01", end="2024-01-01",
            cache_dir=tmp_cache,
        )
        assert isinstance(data, dict)
        assert "prices" in data
        assert "returns" in data

    def test_explicit_can_run_engine(self, tmp_cache):
        """explicit mode 데이터로 엔진 실행 가능."""
        from aftertaxi.core.contracts import (
            AccountConfig, AccountType, BacktestConfig, StrategyConfig,
        )
        from aftertaxi.core.facade import run_backtest

        data = load_lane_a_explicit(
            ["SPY"], start="2023-01-01", end="2024-01-01",
            cache_dir=tmp_cache,
        )

        result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("spy_explicit", {"SPY": 1.0}),
                dividend_schedule=data.dividend_schedule,
            ),
            returns=data.returns, prices=data.prices, fx_rates=data.fx_rates,
        )

        assert result.gross_pv_usd > 0
        assert result.n_months > 0
