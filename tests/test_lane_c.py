# -*- coding: utf-8 -*-
"""
test_lane_c.py — Lane C Bootstrap Distribution 테스트
=====================================================
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pandas as pd
import pytest

from aftertaxi.core.contracts import (
    AccountConfig, AccountType, BacktestConfig,
    EngineResult, RebalanceMode, StrategyConfig,
)
from aftertaxi.lanes.lane_c.bootstrap import (
    BootstrapConfig, circular_block_bootstrap,
)
from aftertaxi.lanes.lane_c.run import (
    DistributionReport, run_lane_c,
)


# ══════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════

def _make_source_returns(n=120, n_assets=2, seed=123):
    """120개월 (10년) 합성 수익률."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2010-01-31", periods=n, freq="ME")
    data = rng.normal(0.008, 0.04, size=(n, n_assets))
    assets = [f"A{i}" for i in range(n_assets)]
    return pd.DataFrame(data, index=idx, columns=assets)


def _make_fx_returns(n=120, seed=456):
    idx = pd.date_range("2010-01-31", periods=n, freq="ME")
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(0.001, 0.02, size=n), index=idx, name="fx")


def _simple_config():
    return BacktestConfig(
        accounts=[AccountConfig(
            account_id="taxable",
            account_type=AccountType.TAXABLE,
            monthly_contribution=1000.0,
            rebalance_mode=RebalanceMode.CONTRIBUTION_ONLY,
        )],
        strategy=StrategyConfig(name="test", weights={"A0": 0.6, "A1": 0.4}),
    )


# ══════════════════════════════════════════════
# Bootstrap Sampler 테스트
# ══════════════════════════════════════════════

class TestCircularBlockBootstrap:

    def test_path_count(self):
        ret = _make_source_returns()
        cfg = BootstrapConfig(n_paths=10, path_length=60, block_length=12)
        paths = circular_block_bootstrap(ret, cfg)
        assert len(paths) == 10

    def test_path_length(self):
        ret = _make_source_returns()
        cfg = BootstrapConfig(n_paths=5, path_length=240, block_length=24)
        paths = circular_block_bootstrap(ret, cfg)
        for p in paths:
            assert len(p["returns"]) == 240

    def test_columns_preserved(self):
        ret = _make_source_returns(n_assets=3)
        cfg = BootstrapConfig(n_paths=3, path_length=60, block_length=12)
        paths = circular_block_bootstrap(ret, cfg)
        for p in paths:
            assert list(p["returns"].columns) == ["A0", "A1", "A2"]

    def test_fx_included_when_provided(self):
        ret = _make_source_returns()
        fx = _make_fx_returns()
        cfg = BootstrapConfig(n_paths=3, path_length=60, block_length=12)
        paths = circular_block_bootstrap(ret, cfg, fx_returns=fx)
        for p in paths:
            assert p["fx_returns"] is not None
            assert len(p["fx_returns"]) == 60

    def test_fx_none_when_not_provided(self):
        ret = _make_source_returns()
        cfg = BootstrapConfig(n_paths=3, path_length=60, block_length=12)
        paths = circular_block_bootstrap(ret, cfg)
        for p in paths:
            assert p["fx_returns"] is None

    def test_reproducibility(self):
        """같은 seed → 같은 경로."""
        ret = _make_source_returns()
        cfg = BootstrapConfig(n_paths=5, path_length=60, block_length=12, seed=999)
        paths1 = circular_block_bootstrap(ret, cfg)
        paths2 = circular_block_bootstrap(ret, cfg)
        for p1, p2 in zip(paths1, paths2):
            np.testing.assert_array_equal(p1["returns"].values, p2["returns"].values)

    def test_different_seed_different_paths(self):
        ret = _make_source_returns()
        cfg1 = BootstrapConfig(n_paths=3, path_length=60, block_length=12, seed=1)
        cfg2 = BootstrapConfig(n_paths=3, path_length=60, block_length=12, seed=2)
        paths1 = circular_block_bootstrap(ret, cfg1)
        paths2 = circular_block_bootstrap(ret, cfg2)
        assert not np.array_equal(paths1[0]["returns"].values, paths2[0]["returns"].values)

    def test_circular_wrapping(self):
        """블록이 데이터 끝을 넘어가면 처음으로 순환."""
        ret = _make_source_returns(n=24)  # 짧은 데이터
        cfg = BootstrapConfig(n_paths=1, path_length=60, block_length=12, seed=42)
        paths = circular_block_bootstrap(ret, cfg)
        # 60개월 경로가 24개월 데이터에서 생성됨 → circular 필수
        assert len(paths[0]["returns"]) == 60
        assert not paths[0]["returns"].isna().any().any()


# ══════════════════════════════════════════════
# Distribution Report 테스트
# ══════════════════════════════════════════════

class TestDistributionReport:

    def test_small_scale_run(self):
        """50 paths, 60개월 — 빠른 스모크 테스트."""
        ret = _make_source_returns(n=120)
        cfg = _simple_config()
        bcfg = BootstrapConfig(n_paths=50, path_length=60, block_length=12, seed=42)

        report = run_lane_c(ret, None, cfg, bcfg)

        assert isinstance(report, DistributionReport)
        assert report.n_paths == 50
        assert report.path_length_months == 60

    def test_percentile_ordering(self):
        """p5 <= p25 <= median <= p75 <= p95."""
        ret = _make_source_returns(n=120)
        cfg = _simple_config()
        bcfg = BootstrapConfig(n_paths=100, path_length=60, block_length=12, seed=42)

        report = run_lane_c(ret, None, cfg, bcfg)

        assert report.mult_after_tax_p5 <= report.mult_after_tax_p25
        assert report.mult_after_tax_p25 <= report.mult_after_tax_median
        assert report.mult_after_tax_median <= report.mult_after_tax_p75
        assert report.mult_after_tax_p75 <= report.mult_after_tax_p95

    def test_failure_prob_range(self):
        ret = _make_source_returns(n=120)
        cfg = _simple_config()
        bcfg = BootstrapConfig(n_paths=50, path_length=60, block_length=12, seed=42)

        report = run_lane_c(ret, None, cfg, bcfg)
        assert 0.0 <= report.failure_prob <= 1.0

    def test_reproducibility(self):
        """같은 seed → 같은 분포."""
        ret = _make_source_returns(n=120)
        cfg = _simple_config()
        bcfg = BootstrapConfig(n_paths=30, path_length=60, block_length=12, seed=777)

        r1 = run_lane_c(ret, None, cfg, bcfg)
        r2 = run_lane_c(ret, None, cfg, bcfg)

        assert r1.mult_after_tax_median == r2.mult_after_tax_median
        assert r1.failure_prob == r2.failure_prob

    def test_with_fx_returns(self):
        """FX 포함 경로."""
        ret = _make_source_returns(n=120)
        fx = _make_fx_returns(n=120)
        cfg = _simple_config()
        bcfg = BootstrapConfig(n_paths=30, path_length=60, block_length=12, seed=42)

        report = run_lane_c(ret, fx, cfg, bcfg, base_fx_rate=1300.0)
        assert report.n_paths == 30
        assert report.mult_after_tax_median > 0

    def test_summary_text(self):
        ret = _make_source_returns(n=120)
        cfg = _simple_config()
        bcfg = BootstrapConfig(n_paths=30, path_length=60, block_length=12, seed=42)

        report = run_lane_c(ret, None, cfg, bcfg)
        text = report.summary_text()
        assert "Lane C Distribution" in text
        assert "Failure prob" in text
