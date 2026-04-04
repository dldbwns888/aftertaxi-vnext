# -*- coding: utf-8 -*-
"""test_isa_optimizer.py — ISA 최적화 엔진 테스트"""

import numpy as np
import pandas as pd
import pytest
from aftertaxi.analysis.isa_optimizer import optimize_isa


@pytest.fixture
def market():
    rng = np.random.default_rng(42)
    idx = pd.date_range("2020-01-31", periods=60, freq="ME")
    ret = pd.DataFrame({"SPY": rng.normal(0.01, 0.04, 60)}, index=idx)
    pri = 100 * (1 + ret).cumprod()
    fx = pd.Series(1300.0, index=idx)
    return ret, pri, fx


class TestISAOptimizer:

    def test_isa_100_beats_taxable_100(self, market):
        """ISA 100%는 TAXABLE 100%보다 항상 세후 유리."""
        ret, pri, fx = market
        result = optimize_isa(
            {"type": "spy_bnh"}, 1000, ret, pri, fx,
            isa_pct_range=[0, 1.0],
        )
        assert result.best_isa_pct == 1.0
        assert result.tax_savings_krw > 0

    def test_monotonic_improvement(self, market):
        """ISA 비중 올릴수록 세후 결과 개선 (단일 전략)."""
        ret, pri, fx = market
        result = optimize_isa(
            {"type": "spy_bnh"}, 1000, ret, pri, fx,
            isa_pct_range=[0, 0.5, 1.0],
        )
        nets = [p.net_pv_krw for p in result.points]
        assert nets == sorted(nets), f"ISA 비중 올릴수록 세후 개선 아님: {nets}"

    def test_summary_format(self, market):
        ret, pri, fx = market
        result = optimize_isa(
            {"type": "spy_bnh"}, 1000, ret, pri, fx,
            isa_pct_range=[0, 1.0],
        )
        s = result.summary()
        assert "최적 ISA 비중" in s
        assert "절세" in s
