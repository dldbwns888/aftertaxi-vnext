# -*- coding: utf-8 -*-
"""
test_lane_a.py — Lane A 실데이터 테스트
========================================
실제 ETF + FX로 엔진 실행 검증.
yfinance 필요 (없으면 skip).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
import pandas as pd
import numpy as np

from aftertaxi.core.contracts import EngineResult


# yfinance 없으면 전체 skip
yf = pytest.importorskip("yfinance", reason="yfinance not installed")


class TestLaneALoader:
    """데이터 로더 기본 검증."""

    def test_load_prices(self):
        from aftertaxi.lanes.lane_a.loader import load_prices
        prices = load_prices(["SPY"], start="2020-01-01", end="2021-12-31")
        assert isinstance(prices, pd.DataFrame)
        assert "SPY" in prices.columns
        assert len(prices) >= 20  # 최소 20개월
        assert prices.index.is_monotonic_increasing

    def test_load_fx_rates(self):
        from aftertaxi.lanes.lane_a.loader import load_fx_rates
        fx = load_fx_rates(start="2020-01-01", end="2021-12-31")
        assert isinstance(fx, pd.Series)
        assert len(fx) >= 20
        assert (fx > 900).all()  # USDKRW는 최소 900 이상
        assert (fx < 1700).all()  # 1700 이하

    def test_load_lane_a_bundle(self):
        from aftertaxi.lanes.lane_a.loader import load_lane_a
        data = load_lane_a(["SPY"], start="2020-01-01", end="2021-12-31")
        assert "prices" in data
        assert "fx_rates" in data
        assert "returns" in data
        assert len(data["prices"]) == len(data["fx_rates"])


class TestLaneABacktest:
    """실제 데이터로 엔진 실행."""

    def test_spy_co_basic(self):
        """SPY 100% C/O — 기본 실행."""
        from aftertaxi.lanes.lane_a.run import run_lane_a
        result = run_lane_a(
            tickers=["SPY"],
            weights={"SPY": 1.0},
            monthly_usd=1000.0,
            start="2020-01-01",
            end="2022-12-31",
        )
        assert isinstance(result, EngineResult)
        assert result.gross_pv_usd > 0
        assert result.invested_usd > 0
        assert result.n_months >= 20  # FX 데이터 overlap에 따라 가변
        assert result.mult_pre_tax > 0

    def test_q60s40_co(self):
        """Q60S40 B&H C/O — 코어 전략."""
        from aftertaxi.lanes.lane_a.run import run_lane_a
        result = run_lane_a(
            tickers=["QQQ", "SSO"],
            weights={"QQQ": 0.6, "SSO": 0.4},
            monthly_usd=1000.0,
            start="2010-01-01",
            end="2023-12-31",
        )
        assert isinstance(result, EngineResult)
        assert result.n_accounts == 1
        assert result.n_months >= 100
        # 장기 적립식이면 배수 > 1
        assert result.mult_pre_tax > 1.0

    def test_invariants_hold(self):
        """실데이터에서도 세금 불변식 유지."""
        from aftertaxi.lanes.lane_a.run import run_lane_a
        result = run_lane_a(
            tickers=["SPY"],
            weights={"SPY": 1.0},
            monthly_usd=1000.0,
            start="2020-01-01",
            end="2022-12-31",
        )
        # gross_krw ≈ gross_usd × fx_rate
        expected_gross = result.gross_pv_usd * result.reporting_fx_rate
        assert abs(result.gross_pv_krw - expected_gross) < 10.0

        # net = gross - unpaid
        expected_net = result.gross_pv_krw - result.tax.total_unpaid_krw
        assert abs(result.net_pv_krw - expected_net) < 10.0

        # assessed >= unpaid
        assert result.tax.total_assessed_krw >= result.tax.total_unpaid_krw - 1.0

    def test_full_rebalance_generates_tax(self):
        """FULL 리밸런싱 + 2자산 → 세금 발생."""
        from aftertaxi.lanes.lane_a.run import run_lane_a
        result = run_lane_a(
            tickers=["SPY", "QQQ"],
            weights={"SPY": 0.5, "QQQ": 0.5},
            monthly_usd=1000.0,
            start="2015-01-01",
            end="2023-12-31",
            rebalance_mode="FULL",
        )
        # 장기 FULL이면 실현이익 → 세금 > 0
        assert result.tax.total_assessed_krw > 0
