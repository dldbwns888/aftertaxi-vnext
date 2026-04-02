# -*- coding: utf-8 -*-
"""
test_unsupported_config.py — 미구현 설정이 silently ignored 되지 않는지 검증
============================================================================
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pandas as pd
import pytest

from aftertaxi.core.contracts import (
    AccountConfig, AccountType, BacktestConfig,
    RebalanceMode, StrategyConfig,
)
from aftertaxi.core.facade import run_backtest


def _make_minimal_data():
    idx = pd.date_range("2020-01-31", periods=12, freq="ME")
    prices = pd.DataFrame({"SPY": [100]*12}, index=idx)
    fx = pd.Series(1300.0, index=idx)
    returns = prices.pct_change().fillna(0.0)
    return returns, prices, fx


class TestUnsupportedConfigRaises:

    def test_annual_cap_raises(self):
        returns, prices, fx = _make_minimal_data()
        with pytest.raises(NotImplementedError, match="annual_cap"):
            run_backtest(
                BacktestConfig(
                    accounts=[AccountConfig("t", AccountType.ISA, 1000.0,
                                            annual_cap=20_000_000)],
                    strategy=StrategyConfig("test", {"SPY": 1.0}),
                ),
                returns=returns, prices=prices, fx_rates=fx,
            )

    def test_allowed_assets_raises(self):
        returns, prices, fx = _make_minimal_data()
        with pytest.raises(NotImplementedError, match="allowed_assets"):
            run_backtest(
                BacktestConfig(
                    accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0,
                                            allowed_assets={"SPY", "QQQ"})],
                    strategy=StrategyConfig("test", {"SPY": 1.0}),
                ),
                returns=returns, prices=prices, fx_rates=fx,
            )

    def test_budget_mode_raises(self):
        returns, prices, fx = _make_minimal_data()
        with pytest.raises(NotImplementedError, match="BUDGET"):
            run_backtest(
                BacktestConfig(
                    accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0,
                                            rebalance_mode=RebalanceMode.BUDGET)],
                    strategy=StrategyConfig("test", {"SPY": 1.0}),
                ),
                returns=returns, prices=prices, fx_rates=fx,
            )

    def test_fifo_lot_method_raises(self):
        returns, prices, fx = _make_minimal_data()
        with pytest.raises(NotImplementedError, match="lot_method"):
            run_backtest(
                BacktestConfig(
                    accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0,
                                            lot_method="FIFO")],
                    strategy=StrategyConfig("test", {"SPY": 1.0}),
                ),
                returns=returns, prices=prices, fx_rates=fx,
            )

    def test_supported_config_passes(self):
        """지원되는 설정은 정상 실행."""
        returns, prices, fx = _make_minimal_data()
        result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )
        assert result.gross_pv_usd > 0
