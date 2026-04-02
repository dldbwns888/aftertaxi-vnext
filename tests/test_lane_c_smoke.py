# -*- coding: utf-8 -*-
"""
test_lane_c_smoke.py — Lane C 실데이터 스모크 테스트
====================================================
C(A): Lane A 실ETF 수익률 기반 bootstrap
C(B): Lane B 합성 수익률 기반 bootstrap
둘 다 100 paths로 빠르게 돌려서 구조 검증.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pandas as pd
import pytest

yf = pytest.importorskip("yfinance", reason="yfinance not installed")

from aftertaxi.core.contracts import (
    AccountConfig, AccountType, BacktestConfig,
    RebalanceMode, StrategyConfig,
)
from aftertaxi.lanes.lane_a.loader import load_lane_a
from aftertaxi.lanes.lane_b.run import load_index_data
from aftertaxi.lanes.lane_b.synthetic import SyntheticParams, synthesize_leveraged_returns
from aftertaxi.lanes.lane_c.bootstrap import BootstrapConfig
from aftertaxi.lanes.lane_c.run import DistributionReport, run_lane_c


# Q60S40 C/O config
Q60S40_CONFIG = BacktestConfig(
    accounts=[AccountConfig(
        account_id="taxable",
        account_type=AccountType.TAXABLE,
        monthly_contribution=1000.0,
        rebalance_mode=RebalanceMode.CONTRIBUTION_ONLY,
    )],
    strategy=StrategyConfig(name="Q60S40", weights={"asset_0": 0.6, "asset_1": 0.4}),
)

SMOKE_BOOTSTRAP = BootstrapConfig(
    n_paths=100,
    path_length=240,   # 20년
    block_length=24,
    seed=42,
)


class TestLaneCSmoke_CA:
    """C(A): Lane A 실ETF 기반 bootstrap."""

    def _get_source(self):
        data = load_lane_a(["QQQ", "SSO"], start="2006-07-01", end="2024-12-31")
        returns = data["returns"]
        returns.columns = ["asset_0", "asset_1"]
        fx_returns = data["fx_rates"].pct_change().fillna(0.0)
        return returns, fx_returns

    def test_ca_runs(self):
        returns, fx_ret = self._get_source()
        report = run_lane_c(returns, fx_ret, Q60S40_CONFIG, SMOKE_BOOTSTRAP)
        assert isinstance(report, DistributionReport)
        assert report.n_paths == 100

    def test_ca_percentiles_ordered(self):
        returns, fx_ret = self._get_source()
        report = run_lane_c(returns, fx_ret, Q60S40_CONFIG, SMOKE_BOOTSTRAP)
        assert report.mult_after_tax_p5 <= report.mult_after_tax_median
        assert report.mult_after_tax_median <= report.mult_after_tax_p95

    def test_ca_failure_prob_reasonable(self):
        returns, fx_ret = self._get_source()
        report = run_lane_c(returns, fx_ret, Q60S40_CONFIG, SMOKE_BOOTSTRAP)
        # 20년 DCA면 파산확률 50% 이하는 돼야
        assert report.failure_prob < 0.5

    def test_ca_summary_text(self):
        returns, fx_ret = self._get_source()
        report = run_lane_c(returns, fx_ret, Q60S40_CONFIG, SMOKE_BOOTSTRAP)
        text = report.summary_text()
        assert "Lane C Distribution" in text
        print("\n=== C(A) Summary ===")
        print(text)


class TestLaneCSmoke_CB:
    """C(B): Lane B 합성 수익률 기반 bootstrap."""

    def _get_source(self):
        data = load_index_data("^SP500TR", "^IRX", start="1990-01-01", end="2024-12-31")
        # 합성 QQQ proxy (1.0x NDX는 데이터 한계로 SP500 대체) + 합성 SSO (2x SP500)
        syn_qqq = synthesize_leveraged_returns(
            data["index_returns"], data["tbill_rate"],
            SyntheticParams(leverage=1.0, annual_fee=0.002),
        )
        syn_sso = synthesize_leveraged_returns(
            data["index_returns"], data["tbill_rate"],
            SyntheticParams(leverage=2.0, annual_fee=0.0089),
        )
        returns = pd.DataFrame({"asset_0": syn_qqq, "asset_1": syn_sso}).dropna()
        return returns

    def test_cb_runs(self):
        returns = self._get_source()
        report = run_lane_c(returns, None, Q60S40_CONFIG, SMOKE_BOOTSTRAP)
        assert isinstance(report, DistributionReport)

    def test_cb_percentiles_ordered(self):
        returns = self._get_source()
        report = run_lane_c(returns, None, Q60S40_CONFIG, SMOKE_BOOTSTRAP)
        assert report.mult_after_tax_p5 <= report.mult_after_tax_median
        assert report.mult_after_tax_median <= report.mult_after_tax_p95

    def test_cb_longer_history_helps(self):
        """C(B)의 source가 C(A)보다 길어서 블록 다양성이 높다."""
        returns = self._get_source()
        assert len(returns) > 300  # 25년+ 데이터

    def test_cb_summary_text(self):
        returns = self._get_source()
        report = run_lane_c(returns, None, Q60S40_CONFIG, SMOKE_BOOTSTRAP)
        text = report.summary_text()
        print("\n=== C(B) Summary ===")
        print(text)


class TestCAvsB_Comparison:
    """C(A) vs C(B) 분포 비교."""

    def test_both_produce_results(self):
        # C(A)
        data_a = load_lane_a(["QQQ", "SSO"], start="2006-07-01", end="2024-12-31")
        ret_a = data_a["returns"]
        ret_a.columns = ["asset_0", "asset_1"]
        fx_a = data_a["fx_rates"].pct_change().fillna(0.0)

        # C(B)
        data_b = load_index_data("^SP500TR", "^IRX", start="1990-01-01", end="2024-12-31")
        syn_0 = synthesize_leveraged_returns(
            data_b["index_returns"], data_b["tbill_rate"],
            SyntheticParams(leverage=1.0, annual_fee=0.002),
        )
        syn_1 = synthesize_leveraged_returns(
            data_b["index_returns"], data_b["tbill_rate"],
            SyntheticParams(leverage=2.0, annual_fee=0.0089),
        )
        ret_b = pd.DataFrame({"asset_0": syn_0, "asset_1": syn_1}).dropna()

        bcfg = BootstrapConfig(n_paths=50, path_length=240, block_length=24, seed=42)

        report_a = run_lane_c(ret_a, fx_a, Q60S40_CONFIG, bcfg)
        report_b = run_lane_c(ret_b, None, Q60S40_CONFIG, bcfg)

        print("\n=== C(A) vs C(B) Comparison ===")
        print(f"C(A) median after-tax: {report_a.mult_after_tax_median:.2f}x")
        print(f"C(B) median after-tax: {report_b.mult_after_tax_median:.2f}x")
        print(f"C(A) failure prob: {report_a.failure_prob:.1%}")
        print(f"C(B) failure prob: {report_b.failure_prob:.1%}")
        print(f"C(A) 5th pct: {report_a.mult_after_tax_p5:.2f}x")
        print(f"C(B) 5th pct: {report_b.mult_after_tax_p5:.2f}x")

        # 둘 다 양수 배수
        assert report_a.mult_after_tax_median > 0
        assert report_b.mult_after_tax_median > 0
