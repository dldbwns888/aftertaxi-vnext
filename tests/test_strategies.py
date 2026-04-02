# -*- coding: utf-8 -*-
"""
test_strategies.py — 전략 등록소 테스트
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from aftertaxi.strategies import registry, StrategySpec
from aftertaxi.core.contracts import StrategyConfig


class TestRegistry:

    def test_available(self):
        keys = registry.available()
        assert "q60s40" in keys
        assert "spy_bnh" in keys
        assert "6040" in keys
        assert len(keys) >= 7

    def test_build_q60s40(self):
        spec = registry.build("q60s40")
        assert isinstance(spec, StrategySpec)
        assert spec.weights == {"QQQ": 0.6, "SSO": 0.4}
        assert spec.family == "static_allocation"

    def test_build_with_name(self):
        spec = registry.build("spy_bnh", name="my_spy")
        assert spec.name == "my_spy"

    def test_build_unknown_raises(self):
        with pytest.raises(KeyError, match="Unknown strategy"):
            registry.build("nonexistent_strategy")

    def test_to_config(self):
        spec = registry.build("q60s40")
        config = spec.to_config()
        assert isinstance(config, StrategyConfig)
        assert config.name == "Q60S40_CO"
        assert config.weights == {"QQQ": 0.6, "SSO": 0.4}

    def test_build_from_dict(self):
        spec = registry.build_from_dict({
            "type": "6040",
            "name": "my_6040",
            "params": {"stock": "VOO", "bond": "AGG"},
        })
        assert spec.name == "my_6040"
        assert spec.weights == {"VOO": 0.6, "AGG": 0.4}
        assert spec.source == "json"

    def test_build_many(self):
        specs = registry.build_many([
            {"type": "q60s40"},
            {"type": "spy_bnh"},
            {"type": "6040"},
        ])
        assert len(specs) == 3
        assert specs[0].name == "Q60S40_CO"
        assert specs[1].weights == {"SPY": 1.0}


class TestBuilders:

    def test_q60s40(self):
        spec = registry.build("q60s40")
        assert "QQQ" in spec.weights
        assert "SSO" in spec.weights
        assert abs(sum(spec.weights.values()) - 1.0) < 0.01

    def test_6040_custom_assets(self):
        spec = registry.build("6040", stock="VOO", bond="SGOV")
        assert spec.weights == {"VOO": 0.6, "SGOV": 0.4}

    def test_equal_weight(self):
        spec = registry.build("equal_weight", assets=["A", "B", "C"])
        assert len(spec.weights) == 3
        assert abs(spec.weights["A"] - 1/3) < 0.01

    def test_custom(self):
        spec = registry.build("custom", weights={"SPY": 0.7, "QQQ": 0.3})
        assert spec.weights == {"SPY": 0.7, "QQQ": 0.3}

    def test_qqq_14x(self):
        spec = registry.build("qqq_1.4x")
        assert "QLD" in spec.weights
        assert "QQQ" in spec.weights

    def test_summary(self):
        spec = registry.build("q60s40")
        s = spec.summary()
        assert "Q60S40" in s
        assert "QQQ" in s


class TestEndToEnd:

    def test_registry_to_engine(self):
        """registry → spec → config → engine."""
        import pandas as pd
        from aftertaxi.core.contracts import AccountConfig, AccountType, BacktestConfig
        from aftertaxi.core.facade import run_backtest

        spec = registry.build("spy_bnh")
        config = spec.to_config()

        idx = pd.date_range("2024-01-31", periods=12, freq="ME")
        prices = pd.DataFrame({"SPY": [100 + i*2 for i in range(12)]}, index=idx)
        fx = pd.Series(1300.0, index=idx)
        returns = prices.pct_change().fillna(0.0)

        result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=config,
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )
        assert result.gross_pv_usd > 0
        assert result.n_months == 12
