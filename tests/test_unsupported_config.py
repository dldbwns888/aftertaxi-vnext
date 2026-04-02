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
        returns, prices, fx = _make_minimal_data()
        result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )
        assert result.gross_pv_usd > 0


class TestAnnualCap:

    def test_cap_limits_contribution(self):
        """annual_cap이 납입을 제한."""
        returns, prices, fx = _make_minimal_data()

        # cap 없음 → 12개월 × $1000 = $12000
        r_no_cap = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.ISA, 1000.0)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        # cap $5000 → 최대 5개월분만 입금
        r_capped = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.ISA, 1000.0,
                                        annual_cap=5000.0)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        assert r_capped.invested_usd < r_no_cap.invested_usd
        assert r_capped.invested_usd <= 5000.0

    def test_cap_none_means_unlimited(self):
        """annual_cap=None → 제한 없음."""
        returns, prices, fx = _make_minimal_data()
        result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0,
                                        annual_cap=None)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )
        assert result.invested_usd == 12000.0


class TestAllowedAssets:

    def test_filters_to_allowed_only(self):
        """allowed_assets에 없는 자산은 매수하지 않음."""
        idx = pd.date_range("2020-01-31", periods=12, freq="ME")
        prices = pd.DataFrame({"SPY": [100]*12, "QQQ": [200]*12}, index=idx)
        fx = pd.Series(1300.0, index=idx)
        returns = prices.pct_change().fillna(0.0)

        # SPY만 허용 → QQQ 매수 안 함
        result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0,
                                        allowed_assets={"SPY"})],
                strategy=StrategyConfig("test", {"SPY": 0.5, "QQQ": 0.5}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        # QQQ가 계좌에 없어야 함 (SPY만 매수)
        assert result.gross_pv_usd > 0

    def test_allowed_none_means_all(self):
        """allowed_assets=None → 전체 허용."""
        idx = pd.date_range("2020-01-31", periods=12, freq="ME")
        prices = pd.DataFrame({"SPY": [100]*12, "QQQ": [200]*12}, index=idx)
        fx = pd.Series(1300.0, index=idx)
        returns = prices.pct_change().fillna(0.0)

        result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("test", {"SPY": 0.5, "QQQ": 0.5}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )
        assert result.gross_pv_usd > 0
