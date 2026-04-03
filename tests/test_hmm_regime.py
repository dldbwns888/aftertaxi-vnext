# -*- coding: utf-8 -*-
"""test_hmm_regime.py — HMM 레짐 경로 생성 테스트"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pandas as pd
import pytest

from aftertaxi.lanes.lane_d.synthetic import (
    SyntheticMarketConfig, generate_synthetic_paths, returns_to_prices,
)


@pytest.fixture(scope="module")
def source_returns():
    """20년 합성 역사 (Bull/Bear 패턴 포함)."""
    rng = np.random.default_rng(42)
    n = 240
    idx = pd.date_range("2000-01-31", periods=n, freq="ME")
    # 간단한 레짐 시뮬: 80% bull (+0.8%, 3.5%), 20% bear (-1.5%, 6%)
    regime = rng.choice([0, 1], size=n, p=[0.8, 0.2])
    spy = np.where(regime == 0,
                   rng.normal(0.008, 0.035, n),
                   rng.normal(-0.015, 0.06, n))
    qqq = np.where(regime == 0,
                   rng.normal(0.010, 0.045, n),
                   rng.normal(-0.020, 0.08, n))
    return pd.DataFrame({"SPY": spy, "QQQ": qqq}, index=idx)


class TestHMMPaths:

    def test_basic_generation(self, source_returns):
        config = SyntheticMarketConfig(
            n_paths=3, path_length_months=60,
            seed=42, mode="hmm_regime",
        )
        paths = generate_synthetic_paths(source_returns, config)
        assert len(paths) == 3
        assert paths[0].shape == (60, 2)

    def test_correct_columns(self, source_returns):
        config = SyntheticMarketConfig(
            n_paths=1, path_length_months=24,
            seed=42, mode="hmm_regime",
        )
        paths = generate_synthetic_paths(source_returns, config)
        assert list(paths[0].columns) == ["SPY", "QQQ"]

    def test_seed_reproducible(self, source_returns):
        config = SyntheticMarketConfig(
            n_paths=2, path_length_months=60,
            seed=42, mode="hmm_regime",
        )
        p1 = generate_synthetic_paths(source_returns, config)
        p2 = generate_synthetic_paths(source_returns, config)
        np.testing.assert_array_equal(p1[0].values, p2[0].values)

    def test_different_seed(self, source_returns):
        c1 = SyntheticMarketConfig(n_paths=1, path_length_months=60,
                                    seed=1, mode="hmm_regime")
        c2 = SyntheticMarketConfig(n_paths=1, path_length_months=60,
                                    seed=2, mode="hmm_regime")
        p1 = generate_synthetic_paths(source_returns, c1)
        p2 = generate_synthetic_paths(source_returns, c2)
        assert not np.array_equal(p1[0].values, p2[0].values)

    def test_longer_than_source(self, source_returns):
        """소스(240개월)보다 긴 경로 생성 가능."""
        config = SyntheticMarketConfig(
            n_paths=1, path_length_months=600,
            seed=42, mode="hmm_regime",
        )
        paths = generate_synthetic_paths(source_returns, config)
        assert paths[0].shape[0] == 600

    def test_to_prices(self, source_returns):
        config = SyntheticMarketConfig(
            n_paths=1, path_length_months=60,
            seed=42, mode="hmm_regime",
        )
        paths = generate_synthetic_paths(source_returns, config)
        prices = returns_to_prices(paths[0])
        assert (prices > 0).all().all()


class TestHMMvsSignFlip:

    def test_mode_dispatch(self, source_returns):
        """mode 값에 따라 다른 알고리즘."""
        sf = SyntheticMarketConfig(n_paths=1, path_length_months=60,
                                    seed=42, mode="sign_flip")
        hm = SyntheticMarketConfig(n_paths=1, path_length_months=60,
                                    seed=42, mode="hmm_regime")
        p_sf = generate_synthetic_paths(source_returns, sf)
        p_hm = generate_synthetic_paths(source_returns, hm)
        # 다른 알고리즘이므로 결과가 다름
        assert not np.array_equal(p_sf[0].values, p_hm[0].values)

    def test_sign_flip_still_works(self, source_returns):
        """기존 sign_flip 회귀."""
        config = SyntheticMarketConfig(
            n_paths=2, path_length_months=60,
            seed=42, mode="sign_flip",
        )
        paths = generate_synthetic_paths(source_returns, config)
        assert len(paths) == 2
        assert paths[0].shape == (60, 2)

    def test_default_mode_is_sign_flip(self, source_returns):
        """기본값은 sign_flip."""
        config = SyntheticMarketConfig(n_paths=1, path_length_months=24, seed=42)
        assert config.mode == "sign_flip"


class TestHMMRegimeCharacteristics:

    def test_two_regimes_detected(self, source_returns):
        """2-state HMM fit이 두 개의 다른 레짐을 감지."""
        from hmmlearn.hmm import GaussianHMM
        model = GaussianHMM(n_components=2, covariance_type="full",
                            n_iter=200, random_state=42)
        model.fit(source_returns.values)
        # 두 레짐의 평균이 다름
        means = model.means_[:, 0]  # SPY column
        assert abs(means[0] - means[1]) > 0.005  # 의미있는 차이

    def test_three_regimes(self, source_returns):
        """3-state HMM도 동작."""
        config = SyntheticMarketConfig(
            n_paths=2, path_length_months=60,
            seed=42, mode="hmm_regime", n_regimes=3,
        )
        paths = generate_synthetic_paths(source_returns, config)
        assert len(paths) == 2

    def test_hmm_with_engine(self, source_returns):
        """HMM 경로 → 엔진 실행."""
        from aftertaxi.core.contracts import (
            AccountConfig, AccountType, BacktestConfig, StrategyConfig,
        )
        from aftertaxi.core.facade import run_backtest

        config = SyntheticMarketConfig(
            n_paths=1, path_length_months=60,
            seed=42, mode="hmm_regime",
        )
        paths = generate_synthetic_paths(source_returns, config)
        path_returns = paths[0]
        path_prices = returns_to_prices(path_returns)
        fx = pd.Series(1300.0, index=path_returns.index)

        bt_config = BacktestConfig(
            accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
            strategy=StrategyConfig("test", {"SPY": 0.6, "QQQ": 0.4}),
        )
        result = run_backtest(bt_config, returns=path_returns,
                              prices=path_prices, fx_rates=fx)
        assert result.gross_pv_usd > 0
