# -*- coding: utf-8 -*-
"""test_interpret_and_savings.py — 해석 + 절세 시뮬레이터 테스트"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pandas as pd
import pytest

from aftertaxi.core.contracts import (
    AccountConfig, AccountType, BacktestConfig, StrategyConfig,
)
from aftertaxi.core.facade import run_backtest
from aftertaxi.core.attribution import build_attribution


def _sample_data(n=60, seed=42):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-31", periods=n, freq="ME")
    returns = pd.DataFrame({"SPY": rng.normal(0.008, 0.04, n)}, index=idx)
    prices = 100 * (1 + returns).cumprod()
    fx = pd.Series(1300.0, index=idx)
    return returns, prices, fx


def _sample_result(n=60):
    returns, prices, fx = _sample_data(n)
    config = BacktestConfig(
        accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
        strategy=StrategyConfig("test", {"SPY": 1.0}),
    )
    return run_backtest(config, returns=returns, prices=prices, fx_rates=fx)


class TestInterpret:

    def test_basic(self):
        from aftertaxi.workbench.interpret import interpret_result
        r = _sample_result()
        a = build_attribution(r)
        text = interpret_result(r, a)
        assert "적립 결과" in text
        assert "세후" in text
        assert len(text) > 50

    def test_mdd_warning(self):
        from aftertaxi.workbench.interpret import interpret_result
        r = _sample_result(n=120)
        a = build_attribution(r)
        text = interpret_result(r, a)
        # 120개월이면 어떤 MDD 언급이든 있어야 함
        assert "MDD" in text or "drag" in text

    def test_comparison(self):
        from aftertaxi.workbench.interpret import interpret_comparison
        r1 = _sample_result(60)
        returns, prices, fx = _sample_data(60, seed=99)
        config2 = BacktestConfig(
            accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
            strategy=StrategyConfig("t2", {"SPY": 1.0}),
        )
        r2 = run_backtest(config2, returns=returns, prices=prices, fx_rates=fx)
        text = interpret_comparison(r1, r2, "A", "B")
        assert "좋습니다" in text
        assert "안정적" in text


class TestTaxSavings:

    def test_basic(self):
        from aftertaxi.workbench.tax_savings import simulate_tax_savings
        returns, prices, fx = _sample_data(60)
        report = simulate_tax_savings(
            strategy_payload={"type": "spy_bnh"},
            total_monthly=1000,
            isa_ratio=0.3,
            returns=returns, prices=prices, fx_rates=fx,
        )
        assert report.isa_ratio == 0.3
        assert report.taxable_only_mult > 0
        assert report.mixed_mult > 0

    def test_isa_saves_tax(self):
        """ISA 비중 높을수록 세금 줄어야 함."""
        from aftertaxi.workbench.tax_savings import simulate_tax_savings
        returns, prices, fx = _sample_data(120)

        r0 = simulate_tax_savings({"type": "spy_bnh"}, 1000, 0.0,
                                   returns, prices, fx)
        r50 = simulate_tax_savings({"type": "spy_bnh"}, 1000, 0.5,
                                    returns, prices, fx)
        # ISA 50%면 TAXABLE 100%보다 세금 적어야 함
        assert r50.mixed_tax <= r0.taxable_only_tax + 1.0

    def test_summary_text(self):
        from aftertaxi.workbench.tax_savings import simulate_tax_savings
        returns, prices, fx = _sample_data(60)
        report = simulate_tax_savings({"type": "spy_bnh"}, 1000, 0.3,
                                       returns, prices, fx)
        text = report.summary_text()
        assert "절세액" in text
        assert "ISA" in text

    def test_zero_isa(self):
        from aftertaxi.workbench.tax_savings import simulate_tax_savings
        returns, prices, fx = _sample_data(60)
        report = simulate_tax_savings({"type": "spy_bnh"}, 1000, 0.0,
                                       returns, prices, fx)
        # ISA 0%면 두 결과 동일
        assert abs(report.tax_savings_krw) < 1.0
