# -*- coding: utf-8 -*-
"""test_data_provider.py — 데이터 공급자 테스트"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pandas as pd
import pytest

from aftertaxi.apps.data_provider import (
    load_market_data, load_synthetic, MarketData,
)


class TestSynthetic:

    def test_basic(self):
        data = load_synthetic(["SPY", "QQQ"], n_months=60)
        assert isinstance(data, MarketData)
        assert data.source == "synthetic"
        assert data.n_months == 60
        assert data.returns.shape == (60, 2)
        assert data.prices.shape == (60, 2)
        assert len(data.fx) == 60

    def test_seed_reproducible(self):
        d1 = load_synthetic(["SPY"], n_months=24, seed=42)
        d2 = load_synthetic(["SPY"], n_months=24, seed=42)
        np.testing.assert_array_equal(d1.returns.values, d2.returns.values)

    def test_different_seed(self):
        d1 = load_synthetic(["SPY"], n_months=24, seed=1)
        d2 = load_synthetic(["SPY"], n_months=24, seed=2)
        assert not np.array_equal(d1.returns.values, d2.returns.values)

    def test_fx_constant(self):
        data = load_synthetic(["SPY"], fx_rate=1400.0)
        assert (data.fx == 1400.0).all()


class TestYfinance:

    def test_yfinance_load(self):
        data = load_market_data(
            ["SPY"], source="yfinance",
            start="2023-01-01", fx_rate=1300.0,
        )
        assert data.source == "yfinance"
        assert data.n_months > 0
        assert "SPY" in data.returns.columns

    def test_yfinance_fx_load(self):
        data = load_market_data(
            ["SPY"], source="yfinance_fx",
            start="2023-01-01",
        )
        assert data.source == "yfinance+fx"
        assert data.n_months > 0
        # FX가 상수가 아님 (실제 환율)
        assert data.fx.std() > 0 or data.n_months < 3


class TestUnified:

    def test_unknown_source(self):
        with pytest.raises(ValueError, match="Unknown source"):
            load_market_data(["SPY"], source="nonexistent")

    def test_synthetic_via_unified(self):
        data = load_market_data(
            ["SPY"], source="synthetic",
            n_months=12, seed=42,
        )
        assert data.source == "synthetic"
        assert data.n_months == 12


class TestEndToEnd:

    def test_yfinance_to_engine(self):
        """실제 데이터 → compile → engine."""
        from aftertaxi.strategies.compile import compile_backtest
        from aftertaxi.core.facade import run_backtest

        data = load_market_data(
            ["SPY"], source="yfinance",
            start="2023-01-01", fx_rate=1300.0,
        )
        config = compile_backtest({
            "strategy": {"type": "spy_bnh"},
            "accounts": [{"type": "TAXABLE", "monthly_contribution": 1000}],
        })
        result = run_backtest(
            config,
            returns=data.returns,
            prices=data.prices,
            fx_rates=data.fx,
        )
        assert result.gross_pv_usd > 0
        assert result.n_months > 0
