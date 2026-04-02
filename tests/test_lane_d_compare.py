# -*- coding: utf-8 -*-
"""
test_lane_d_compare.py — DCA vs Lump Sum 비교 테스트
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pandas as pd
import pytest

from aftertaxi.core.contracts import (
    AccountConfig, AccountType, BacktestConfig, StrategyConfig,
)
from aftertaxi.lanes.lane_d.synthetic import SyntheticMarketConfig
from aftertaxi.lanes.lane_d.compare import (
    LaneDComparisonReport, run_lane_d_comparison, _compute_lump_sum,
)


@pytest.fixture(scope="module")
def source_returns():
    rng = np.random.default_rng(99)
    idx = pd.date_range("2000-01-31", periods=240, freq="ME")
    return pd.DataFrame({
        "SPY": rng.normal(0.007, 0.04, 240),
        "QQQ": rng.normal(0.009, 0.05, 240),
    }, index=idx)


@pytest.fixture(scope="module")
def small_config():
    return SyntheticMarketConfig(n_paths=5, path_length_months=60, seed=42)


@pytest.fixture(scope="module")
def backtest_config():
    return BacktestConfig(
        accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
        strategy=StrategyConfig("test", {"SPY": 0.6, "QQQ": 0.4}),
    )


# ══════════════════════════════════════════════
# Lump Sum 단위 테스트
# ══════════════════════════════════════════════

class TestLumpSum:

    def test_positive_returns_mult_above_1(self):
        """양의 수익률 경로 → mult > 1."""
        idx = pd.date_range("2020-01-31", periods=60, freq="ME")
        r = pd.DataFrame({"SPY": [0.01] * 60}, index=idx)
        result = _compute_lump_sum(r, {"SPY": 1.0})
        assert result.final_mult > 1.0

    def test_negative_returns_mult_below_1(self):
        """음의 수익률 경로 → mult < 1."""
        idx = pd.date_range("2020-01-31", periods=60, freq="ME")
        r = pd.DataFrame({"SPY": [-0.01] * 60}, index=idx)
        result = _compute_lump_sum(r, {"SPY": 1.0})
        assert result.final_mult < 1.0

    def test_zero_returns_mult_1(self):
        """수익률 0 → mult = 1."""
        idx = pd.date_range("2020-01-31", periods=60, freq="ME")
        r = pd.DataFrame({"SPY": [0.0] * 60}, index=idx)
        result = _compute_lump_sum(r, {"SPY": 1.0})
        assert abs(result.final_mult - 1.0) < 1e-10

    def test_mdd_negative(self):
        """변동 있으면 MDD < 0."""
        rng = np.random.default_rng(42)
        idx = pd.date_range("2020-01-31", periods=120, freq="ME")
        r = pd.DataFrame({"SPY": rng.normal(0.0, 0.05, 120)}, index=idx)
        result = _compute_lump_sum(r, {"SPY": 1.0})
        assert result.mdd < 0

    def test_multi_asset_weighting(self):
        """멀티자산 가중 계산."""
        idx = pd.date_range("2020-01-31", periods=12, freq="ME")
        r = pd.DataFrame({
            "A": [0.10] * 12,
            "B": [0.0] * 12,
        }, index=idx)
        # A에 50% → 가중 수익률 = 0.05
        result = _compute_lump_sum(r, {"A": 0.5, "B": 0.5})
        expected = (1.05 ** 12)
        assert abs(result.final_mult - expected) < 0.01


# ══════════════════════════════════════════════
# 비교 리포트 테스트
# ══════════════════════════════════════════════

class TestComparison:

    def test_report_structure(self, source_returns, small_config, backtest_config):
        report = run_lane_d_comparison(
            source_returns, backtest_config, small_config)
        assert isinstance(report, LaneDComparisonReport)
        assert report.n_paths == 5
        assert report.path_length_months == 60

    def test_dca_report_present(self, source_returns, small_config, backtest_config):
        report = run_lane_d_comparison(
            source_returns, backtest_config, small_config)
        assert report.dca_report is not None
        assert report.dca_report.n_paths == 5

    def test_survival_rates_valid(self, source_returns, small_config, backtest_config):
        report = run_lane_d_comparison(
            source_returns, backtest_config, small_config)
        assert 0 <= report.dca_report.survival_rate <= 1
        assert 0 <= report.ls_survival_rate <= 1

    def test_delta_calculated(self, source_returns, small_config, backtest_config):
        report = run_lane_d_comparison(
            source_returns, backtest_config, small_config)
        expected_delta = report.dca_report.survival_rate - report.ls_survival_rate
        assert abs(report.survival_delta - expected_delta) < 1e-10

    def test_raw_arrays(self, source_returns, small_config, backtest_config):
        report = run_lane_d_comparison(
            source_returns, backtest_config, small_config)
        assert len(report.ls_all_mults) == 5
        assert len(report.ls_all_mdds) == 5

    def test_same_paths_used(self, source_returns, backtest_config):
        """같은 seed → 같은 결과."""
        c = SyntheticMarketConfig(n_paths=3, path_length_months=36, seed=77)
        r1 = run_lane_d_comparison(source_returns, backtest_config, c)
        r2 = run_lane_d_comparison(source_returns, backtest_config, c)
        np.testing.assert_array_equal(r1.ls_all_mults, r2.ls_all_mults)
        np.testing.assert_array_equal(
            r1.dca_report.all_mult_after_tax,
            r2.dca_report.all_mult_after_tax,
        )

    def test_summary_text(self, source_returns, small_config, backtest_config):
        report = run_lane_d_comparison(
            source_returns, backtest_config, small_config)
        text = report.summary_text()
        assert "DCA" in text
        assert "Lump Sum" in text
        assert "Delta" in text

    def test_interpretation_present(self, source_returns, small_config, backtest_config):
        report = run_lane_d_comparison(
            source_returns, backtest_config, small_config)
        text = report.summary_text()
        # 해석 문장이 있어야 함
        assert any(kw in text for kw in ["DCA 효과", "Lump Sum이 더", "납입 방식"])

    def test_parallel(self, source_returns, small_config, backtest_config):
        r1 = run_lane_d_comparison(
            source_returns, backtest_config, small_config, n_jobs=1)
        r2 = run_lane_d_comparison(
            source_returns, backtest_config, small_config, n_jobs=2)
        np.testing.assert_allclose(
            r1.dca_report.all_mult_after_tax,
            r2.dca_report.all_mult_after_tax,
            rtol=1e-10,
        )
