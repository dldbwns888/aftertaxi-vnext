# -*- coding: utf-8 -*-
"""test_compare.py — 멀티 전략 비교 리포트 + 통계 검정 테스트"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pandas as pd
import pytest

from aftertaxi.core.contracts import (
    AccountConfig, AccountType, BacktestConfig, StrategyConfig,
)
from aftertaxi.core.facade import run_backtest
from aftertaxi.workbench.compare import (
    compare_strategies, ComparisonReport, StrategyMetrics, PairwiseTest,
)


def _run_two(n=60, seed=42):
    """두 전략(SPY 100% vs 6040) 실행, 결과 반환."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-31", periods=n, freq="ME")
    spy = rng.normal(0.008, 0.04, n)
    tlt = rng.normal(0.003, 0.02, n)
    returns = pd.DataFrame({"SPY": spy, "TLT": tlt}, index=idx)
    prices = 100.0 * (1 + returns).cumprod()
    fx = pd.Series(1300.0, index=idx)

    r_spy = run_backtest(
        BacktestConfig(
            accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
            strategy=StrategyConfig("SPY_BnH", {"SPY": 1.0}),
        ),
        returns=returns, prices=prices, fx_rates=fx,
    )
    r_6040 = run_backtest(
        BacktestConfig(
            accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
            strategy=StrategyConfig("6040", {"SPY": 0.6, "TLT": 0.4}),
        ),
        returns=returns, prices=prices, fx_rates=fx,
    )
    return r_spy, r_6040


class TestCompareStrategies:

    def test_basic(self):
        r_spy, r_6040 = _run_two()
        report = compare_strategies([r_spy, r_6040], ["SPY", "6040"])
        assert isinstance(report, ComparisonReport)
        assert len(report.metrics) == 2
        assert report.winner in ("SPY", "6040")

    def test_rank_table(self):
        r_spy, r_6040 = _run_two()
        report = compare_strategies([r_spy, r_6040], ["SPY", "6040"])
        table = report.rank_table()
        assert len(table) == 2
        assert table[0]["rank"] == 1
        assert table[0]["mult_after_tax"] >= table[1]["mult_after_tax"]

    def test_same_strategy(self):
        """동일 전략 비교 → 차이 0."""
        r, _ = _run_two()
        report = compare_strategies([r, r], ["A", "B"])
        assert abs(report.metrics[0].mult_after_tax - report.metrics[1].mult_after_tax) < 1e-6

    def test_auto_names(self):
        r_spy, r_6040 = _run_two()
        report = compare_strategies([r_spy, r_6040])
        assert report.metrics[0].name == "strategy_0"

    def test_name_length_mismatch(self):
        r, _ = _run_two()
        with pytest.raises(ValueError, match="길이"):
            compare_strategies([r], ["A", "B"])

    def test_summary_text(self):
        r_spy, r_6040 = _run_two()
        report = compare_strategies([r_spy, r_6040], ["SPY", "6040"])
        text = report.summary_text()
        assert "전략 비교" in text
        assert "세후 우승" in text

    def test_three_strategies(self):
        r_spy, r_6040 = _run_two()
        report = compare_strategies([r_spy, r_6040, r_spy], ["SPY", "6040", "SPY2"])
        assert len(report.metrics) == 3
        # 3개면 pairwise: (0,1), (0,2), (1,2) = 3쌍 × 2검정 = 최대6
        assert len(report.pairwise_tests) >= 3


class TestPairwiseTests:

    def test_ttest_exists(self):
        r_spy, r_6040 = _run_two()
        report = compare_strategies([r_spy, r_6040], ["SPY", "6040"])
        ttests = [t for t in report.pairwise_tests if t.test_name == "paired_ttest"]
        assert len(ttests) == 1
        assert 0 <= ttests[0].p_value <= 1

    def test_wilcoxon_exists(self):
        r_spy, r_6040 = _run_two()
        report = compare_strategies([r_spy, r_6040], ["SPY", "6040"])
        wilcoxon = [t for t in report.pairwise_tests if t.test_name == "wilcoxon"]
        assert len(wilcoxon) == 1

    def test_no_tests_when_disabled(self):
        r_spy, r_6040 = _run_two()
        report = compare_strategies([r_spy, r_6040], ["SPY", "6040"], include_tests=False)
        assert len(report.pairwise_tests) == 0


class TestMetrics:

    def test_sharpe_positive_for_uptrend(self):
        r_spy, _ = _run_two()
        report = compare_strategies([r_spy], ["SPY"])
        assert report.metrics[0].sharpe_ratio != 0  # 랜덤이라 0 아님
        assert report.metrics[0].annualized_vol > 0
