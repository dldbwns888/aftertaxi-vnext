# -*- coding: utf-8 -*-
"""
test_lane_d_synthetic.py — Lane D 합성 장기 생존 시뮬레이션 테스트
=================================================================
코어 무관. 합성 경로 생성 + engine 반복 실행 + 생존 통계.

테스트 시간 고려: n_paths=5, path_length=60 (5년) 으로 축소.
"""

import numpy as np
import pandas as pd
import pytest

from aftertaxi.core.contracts import (
    AccountConfig, AccountType, BacktestConfig, StrategyConfig,
)
from aftertaxi.lanes.lane_d.synthetic import (
    SyntheticMarketConfig, generate_synthetic_paths, returns_to_prices,
)
from aftertaxi.lanes.lane_d.run import run_lane_d, SyntheticSurvivalReport


@pytest.fixture(scope="module")
def source_returns():
    """20년 합성 역사 수익률 (경로 생성의 원재료)."""
    rng = np.random.default_rng(99)
    idx = pd.date_range("2000-01-31", periods=240, freq="ME")
    spy = rng.normal(0.007, 0.04, 240)
    qqq = rng.normal(0.009, 0.05, 240)
    return pd.DataFrame({"SPY": spy, "QQQ": qqq}, index=idx)


@pytest.fixture(scope="module")
def small_config():
    """테스트용 작은 config."""
    return SyntheticMarketConfig(n_paths=5, path_length_months=60, seed=42)


@pytest.fixture(scope="module")
def backtest_config():
    return BacktestConfig(
        accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
        strategy=StrategyConfig("test", {"SPY": 0.6, "QQQ": 0.4}),
    )


# ══════════════════════════════════════════════
# 경로 생성 테스트
# ══════════════════════════════════════════════

class TestPathGeneration:

    def test_path_count(self, source_returns, small_config):
        paths = generate_synthetic_paths(source_returns, small_config)
        assert len(paths) == 5

    def test_path_length(self, source_returns, small_config):
        paths = generate_synthetic_paths(source_returns, small_config)
        assert paths[0].shape[0] == 60

    def test_path_columns(self, source_returns, small_config):
        paths = generate_synthetic_paths(source_returns, small_config)
        assert list(paths[0].columns) == ["SPY", "QQQ"]

    def test_magnitude_preserved(self, source_returns):
        """block 내 magnitude는 역사에서 온 값."""
        config = SyntheticMarketConfig(n_paths=1, path_length_months=24, seed=42, block_length=6)
        paths = generate_synthetic_paths(source_returns, config)
        # 절대값이 역사 범위 안에 있어야 함
        hist_max = np.abs(source_returns.values).max()
        synth_max = np.abs(paths[0].values).max()
        assert synth_max <= hist_max + 1e-10

    def test_seed_reproducible(self, source_returns, small_config):
        p1 = generate_synthetic_paths(source_returns, small_config)
        p2 = generate_synthetic_paths(source_returns, small_config)
        np.testing.assert_array_equal(p1[0].values, p2[0].values)

    def test_different_seed(self, source_returns):
        c1 = SyntheticMarketConfig(n_paths=2, path_length_months=60, seed=1)
        c2 = SyntheticMarketConfig(n_paths=2, path_length_months=60, seed=2)
        p1 = generate_synthetic_paths(source_returns, c1)
        p2 = generate_synthetic_paths(source_returns, c2)
        assert not np.array_equal(p1[0].values, p2[0].values)

    def test_longer_than_source(self, source_returns):
        """source보다 긴 경로 생성 가능 (bootstrap)."""
        config = SyntheticMarketConfig(n_paths=1, path_length_months=600, seed=42)
        paths = generate_synthetic_paths(source_returns, config)
        assert paths[0].shape[0] == 600  # source는 240, 경로는 600

    def test_returns_to_prices(self, source_returns, small_config):
        paths = generate_synthetic_paths(source_returns, small_config)
        prices = returns_to_prices(paths[0])
        assert prices.shape == paths[0].shape
        assert (prices > 0).all().all()


# ══════════════════════════════════════════════
# 실행 + 리포트 테스트
# ══════════════════════════════════════════════

class TestRunLaneD:

    def test_basic_run(self, source_returns, small_config, backtest_config):
        report = run_lane_d(source_returns, backtest_config, small_config)
        assert isinstance(report, SyntheticSurvivalReport)
        assert report.n_paths == 5
        assert report.path_length_months == 60

    def test_survival_rate_range(self, source_returns, small_config, backtest_config):
        report = run_lane_d(source_returns, backtest_config, small_config)
        assert 0 <= report.survival_rate <= 1

    def test_failure_prob_range(self, source_returns, small_config, backtest_config):
        report = run_lane_d(source_returns, backtest_config, small_config)
        assert 0 <= report.failure_prob <= 1

    def test_median_computed(self, source_returns, small_config, backtest_config):
        report = run_lane_d(source_returns, backtest_config, small_config)
        assert report.median_mult_after_tax > 0
        assert report.median_mdd <= 0  # MDD is negative or zero

    def test_raw_arrays(self, source_returns, small_config, backtest_config):
        report = run_lane_d(source_returns, backtest_config, small_config)
        assert len(report.all_mult_after_tax) == 5
        assert len(report.all_mdd) == 5

    def test_with_actual(self, source_returns, small_config, backtest_config):
        """actual_result 주면 percentile 계산."""
        from aftertaxi.core.facade import run_backtest
        idx = pd.date_range("2020-01-31", periods=60, freq="ME")
        rng = np.random.default_rng(42)
        returns = pd.DataFrame({"SPY": rng.normal(0.008, 0.04, 60),
                                 "QQQ": rng.normal(0.01, 0.05, 60)}, index=idx)
        prices = returns_to_prices(returns)
        fx = pd.Series(1300.0, index=idx)
        actual = run_backtest(backtest_config, returns=returns, prices=prices, fx_rates=fx)

        report = run_lane_d(source_returns, backtest_config, small_config,
                            actual_result=actual)
        assert report.actual_percentile is not None
        assert 0 <= report.actual_percentile <= 100

    def test_summary_text(self, source_returns, small_config, backtest_config):
        report = run_lane_d(source_returns, backtest_config, small_config)
        text = report.summary_text()
        assert "Lane D" in text
        assert "생존률" in text
        assert "세후 배수" in text

    def test_p5_le_median_le_p95(self, source_returns, small_config, backtest_config):
        report = run_lane_d(source_returns, backtest_config, small_config)
        assert report.p5_mult_after_tax <= report.median_mult_after_tax
        assert report.median_mult_after_tax <= report.p95_mult_after_tax


# ══════════════════════════════════════════════
# 병렬화 테스트
# ══════════════════════════════════════════════

class TestParallel:

    def test_sequential_equals_parallel(self, source_returns, small_config, backtest_config):
        """n_jobs=1과 n_jobs=2 결과 동일."""
        r1 = run_lane_d(source_returns, backtest_config, small_config, n_jobs=1)
        r2 = run_lane_d(source_returns, backtest_config, small_config, n_jobs=2)
        np.testing.assert_allclose(
            r1.all_mult_after_tax, r2.all_mult_after_tax, rtol=1e-10,
        )

    def test_parallel_same_stats(self, source_returns, small_config, backtest_config):
        """병렬 실행도 같은 통계."""
        r1 = run_lane_d(source_returns, backtest_config, small_config, n_jobs=1)
        r2 = run_lane_d(source_returns, backtest_config, small_config, n_jobs=2)
        assert r1.survival_rate == r2.survival_rate
        assert abs(r1.median_mult_after_tax - r2.median_mult_after_tax) < 1e-10
