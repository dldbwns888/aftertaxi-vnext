# -*- coding: utf-8 -*-
"""
test_stress.py — 랜덤 시장 생존 테스트
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pandas as pd
import pytest

from aftertaxi.core.contracts import (
    AccountConfig, AccountType, BacktestConfig, StrategyConfig,
)
from aftertaxi.core.facade import run_backtest
from aftertaxi.validation.stress import (
    RandomScenarioConfig, RandomScenarioReport,
    generate_vector_sign_flip, generate_bootstrap_sign_flip,
    run_random_market_survival,
)
from aftertaxi.validation.reports import Grade


def _make_data(n=60, seed=42):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-31", periods=n, freq="ME")
    r = rng.normal(0.008, 0.04, n)
    returns = pd.DataFrame({"SPY": r}, index=idx)
    prices = pd.DataFrame({"SPY": 100 * np.cumprod(1 + r)}, index=idx)
    fx = pd.Series(1300.0, index=idx)
    return returns, prices, fx


def _make_config():
    return BacktestConfig(
        accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
        strategy=StrategyConfig("test", {"SPY": 1.0}),
    )


class TestPathGeneration:

    def test_sign_flip_shape(self):
        returns, _, _ = _make_data()
        paths = generate_vector_sign_flip(returns, n_paths=10)
        assert len(paths) == 10
        assert paths[0].shape == returns.shape
        assert list(paths[0].columns) == list(returns.columns)

    def test_sign_flip_magnitude_preserved(self):
        """크기는 유지, 방향만 다름."""
        returns, _, _ = _make_data()
        paths = generate_vector_sign_flip(returns, n_paths=5)
        for p in paths:
            np.testing.assert_allclose(np.abs(p.values), np.abs(returns.values))

    def test_sign_flip_directions_vary(self):
        """경로마다 방향이 다름."""
        returns, _, _ = _make_data(n=100)
        paths = generate_vector_sign_flip(returns, n_paths=10)
        signs = [np.sign(p.values[:, 0]).sum() for p in paths]
        assert len(set(signs)) > 1  # 전부 같지는 않아야

    def test_sign_flip_reproducible(self):
        returns, _, _ = _make_data()
        p1 = generate_vector_sign_flip(returns, 5, seed=42)
        p2 = generate_vector_sign_flip(returns, 5, seed=42)
        np.testing.assert_array_equal(p1[0].values, p2[0].values)

    def test_bootstrap_sign_flip_shape(self):
        returns, _, _ = _make_data()
        paths = generate_bootstrap_sign_flip(returns, n_paths=5, block_length=6)
        assert len(paths) == 5
        assert paths[0].shape == returns.shape


class TestRunRandomSurvival:

    def test_basic_run(self):
        returns, prices, fx = _make_data()
        config = _make_config()
        report = run_random_market_survival(
            returns, fx, config,
            RandomScenarioConfig(n_paths=20, seed=42),
            prices=prices,
        )
        assert isinstance(report, RandomScenarioReport)
        assert report.n_paths == 20
        assert 0 <= report.survival_rate <= 1
        assert len(report.all_mults) == 20

    def test_with_actual(self):
        """actual_result 있으면 percentile 계산."""
        returns, prices, fx = _make_data()
        config = _make_config()
        actual = run_backtest(config, returns=returns, prices=prices, fx_rates=fx)

        report = run_random_market_survival(
            returns, fx, config,
            RandomScenarioConfig(n_paths=30, seed=42),
            actual_result=actual,
        )
        assert report.actual_percentile is not None
        assert 0 <= report.actual_percentile <= 100

    def test_to_check_result(self):
        returns, prices, fx = _make_data()
        config = _make_config()
        actual = run_backtest(config, returns=returns, prices=prices, fx_rates=fx)

        report = run_random_market_survival(
            returns, fx, config,
            RandomScenarioConfig(n_paths=20, seed=42),
            actual_result=actual,
        )
        cr = report.to_check_result()
        assert cr.name == "random_market_survival"
        assert cr.grade in (Grade.PASS, Grade.WARN, Grade.FAIL)

    def test_bootstrap_mode(self):
        returns, prices, fx = _make_data()
        config = _make_config()
        report = run_random_market_survival(
            returns, fx, config,
            RandomScenarioConfig(n_paths=10, mode="bootstrap_sign_flip", seed=42),
        )
        assert report.n_paths == 10
