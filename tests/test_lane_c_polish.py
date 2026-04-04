# -*- coding: utf-8 -*-
"""
test_lane_c_polish.py — LC2 수정 + provenance + 병렬화 테스트
=============================================================
"""

import numpy as np
import pandas as pd
import pytest

from aftertaxi.core.contracts import (
    AccountConfig, AccountType, BacktestConfig,
    RebalanceMode, StrategyConfig,
)
from aftertaxi.core.dividend import DividendSchedule
from aftertaxi.lanes.lane_c.bootstrap import (
    BootstrapConfig, PathProvenance, circular_block_bootstrap,
)
from aftertaxi.lanes.lane_c.run import run_lane_c


def _make_source(n=60, start="2010-01-31"):
    idx = pd.date_range(start, periods=n, freq="ME")
    rng = np.random.default_rng(123)
    returns = pd.DataFrame(
        {"SPY": rng.normal(0.008, 0.04, n)},
        index=idx,
    )
    return returns


def _make_config():
    return BacktestConfig(
        accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
        strategy=StrategyConfig("test", {"SPY": 1.0}),
    )


# ══════════════════════════════════════════════
# LC2 수정: 날짜축이 source에서 추론
# ══════════════════════════════════════════════

class TestLC2DateFix:

    def test_default_base_year_from_source(self):
        """base_year=None이면 source 시작 연도 사용."""
        returns = _make_source(start="2010-01-31")
        cfg = BootstrapConfig(n_paths=2, path_length=24, seed=1)
        paths = circular_block_bootstrap(returns, cfg)

        first_date = paths[0]["returns"].index[0]
        assert first_date.year == 2010

    def test_custom_base_year(self):
        """base_year 직접 지정."""
        returns = _make_source()
        cfg = BootstrapConfig(n_paths=2, path_length=24, seed=1, base_year=2020)
        paths = circular_block_bootstrap(returns, cfg)

        first_date = paths[0]["returns"].index[0]
        assert first_date.year == 2020

    def test_year_boundaries_advance(self):
        """24개월 경로에서 연도가 2번 전환."""
        returns = _make_source()
        cfg = BootstrapConfig(n_paths=1, path_length=24, seed=1, base_year=2020)
        paths = circular_block_bootstrap(returns, cfg)

        years = paths[0]["returns"].index.year.unique()
        assert len(years) >= 2  # 2020, 2021 최소

    def test_all_paths_same_dates(self):
        """같은 config면 모든 경로가 같은 날짜축."""
        returns = _make_source()
        cfg = BootstrapConfig(n_paths=5, path_length=24, seed=1)
        paths = circular_block_bootstrap(returns, cfg)

        idx0 = paths[0]["returns"].index
        for p in paths[1:]:
            assert (p["returns"].index == idx0).all()


# ══════════════════════════════════════════════
# Provenance
# ══════════════════════════════════════════════

class TestProvenance:

    def test_provenance_exists(self):
        """각 경로에 provenance 메타가 있다."""
        returns = _make_source()
        cfg = BootstrapConfig(n_paths=3, path_length=24, seed=42)
        paths = circular_block_bootstrap(returns, cfg)

        for p in paths:
            assert "provenance" in p
            prov = p["provenance"]
            assert isinstance(prov, PathProvenance)

    def test_provenance_fields(self):
        """provenance에 재현 정보가 채워져 있다."""
        returns = _make_source(start="2010-01-31")
        cfg = BootstrapConfig(n_paths=2, path_length=24, block_length=6, seed=99)
        paths = circular_block_bootstrap(returns, cfg)

        prov = paths[0]["provenance"]
        assert prov.seed == 99
        assert prov.block_length == 6
        assert prov.path_length == 24
        assert prov.source_start == "2010-01-31"
        assert prov.source_n_months == 60
        assert prov.base_year == 2010
        assert len(prov.block_starts) > 0

    def test_same_seed_same_provenance(self):
        """같은 seed → 같은 block_starts."""
        returns = _make_source()
        cfg = BootstrapConfig(n_paths=2, path_length=24, seed=42)

        paths1 = circular_block_bootstrap(returns, cfg)
        paths2 = circular_block_bootstrap(returns, cfg)

        assert paths1[0]["provenance"].block_starts == paths2[0]["provenance"].block_starts

    def test_distribution_report_provenance(self):
        """DistributionReport에 provenance 정보가 포함."""
        returns = _make_source(start="2010-01-31")
        cfg = _make_config()
        bcfg = BootstrapConfig(n_paths=5, path_length=24, seed=77)

        report = run_lane_c(returns, None, cfg, bcfg)

        assert report.seed == 77
        assert report.source_start == "2010-01-31"
        assert report.source_n_months == 60
        assert report.base_year == 2010


# ══════════════════════════════════════════════
# 병렬화
# ══════════════════════════════════════════════

class TestParallelization:

    def test_parallel_same_results(self):
        """n_jobs=1과 n_jobs=2가 같은 분포 통계."""
        returns = _make_source()
        cfg = _make_config()
        bcfg = BootstrapConfig(n_paths=10, path_length=24, seed=42)

        r_seq = run_lane_c(returns, None, cfg, bcfg, n_jobs=1)
        r_par = run_lane_c(returns, None, cfg, bcfg, n_jobs=2)

        # 같은 seed → 같은 paths → 같은 결과
        assert abs(r_seq.mult_after_tax_median - r_par.mult_after_tax_median) < 1e-6
        assert abs(r_seq.failure_prob - r_par.failure_prob) < 1e-6

    def test_parallel_all_mults_match(self):
        """병렬 실행의 모든 개별 경로 결과가 순차와 동일."""
        returns = _make_source()
        cfg = _make_config()
        bcfg = BootstrapConfig(n_paths=5, path_length=24, seed=42)

        r_seq = run_lane_c(returns, None, cfg, bcfg, n_jobs=1)
        r_par = run_lane_c(returns, None, cfg, bcfg, n_jobs=2)

        np.testing.assert_array_almost_equal(
            r_seq.all_mult_after_tax, r_par.all_mult_after_tax, decimal=6,
        )


# ══════════════════════════════════════════════
# Config 전달 (dividend_schedule 등)
# ══════════════════════════════════════════════

class TestConfigForwarding:

    def test_dividend_schedule_forwarded(self):
        """Lane C 경로에 dividend_schedule이 전달된다."""
        returns = _make_source()
        cfg = BacktestConfig(
            accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
            strategy=StrategyConfig("test", {"SPY": 1.0}),
            dividend_schedule=DividendSchedule({"SPY": 0.02}),
        )
        bcfg = BootstrapConfig(n_paths=3, path_length=24, seed=42)

        # dividend 있을 때 vs 없을 때 결과가 다름
        r_with = run_lane_c(returns, None, cfg, bcfg)

        cfg_no_div = BacktestConfig(
            accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
            strategy=StrategyConfig("test", {"SPY": 1.0}),
        )
        r_without = run_lane_c(returns, None, cfg_no_div, bcfg)

        # 배당 재투자 효과로 PV 차이
        assert r_with.mult_pre_tax_median != r_without.mult_pre_tax_median
