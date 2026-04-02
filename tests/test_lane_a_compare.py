# -*- coding: utf-8 -*-
"""
test_lane_a_compare.py — adjusted vs explicit 비교 harness 테스트
=================================================================
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pandas as pd
import pytest
from pathlib import Path
import tempfile

yf = pytest.importorskip("yfinance")

from aftertaxi.lanes.lane_a.compare import compare_price_modes, ComparisonResult

AV_KEY = "1F77HAKH3TOIU5DZ"
FRED_KEY = "f8808fc62203cc8e92829766b2fde343"


@pytest.fixture
def tmp_cache():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture(scope="module")
def comparison():
    """모듈 스코프: 비교 결과 1회 계산."""
    return compare_price_modes(
        ["SPY"], start="2020-01-01", end="2024-12-31",
        av_key=AV_KEY, fred_key=FRED_KEY,
    )


class TestComparisonHarness:

    def test_returns_comparison_result(self, comparison):
        assert isinstance(comparison, ComparisonResult)

    def test_both_paths_run(self, comparison):
        assert comparison.adj_result.gross_pv_usd > 0
        assert comparison.exp_result.gross_pv_usd > 0

    def test_explicit_has_dividends(self, comparison):
        """explicit path에서 배당이 보임."""
        assert comparison.exp_attribution.total_dividend_gross_usd > 0
        assert comparison.adj_attribution.total_dividend_gross_usd == 0

    def test_delta_table_structure(self, comparison):
        table = comparison.delta_table()
        assert len(table) >= 10
        for row in table:
            assert "항목" in row
            assert "adjusted" in row
            assert "explicit" in row

    def test_summary_text(self, comparison):
        text = comparison.summary_text()
        assert "Lane A Price Mode Comparison" in text
        assert "해석" in text

    def test_same_invested(self, comparison):
        """참고: adjusted(yfinance FX)와 explicit(FRED FX)의 공통 기간이 다를 수 있음.
        투자금은 n_months에 비례하므로, 월당 투자금이 같은지 확인."""
        adj_per_month = comparison.adj_result.invested_usd / comparison.adj_result.n_months
        exp_per_month = comparison.exp_result.invested_usd / comparison.exp_result.n_months
        assert abs(adj_per_month - exp_per_month) < 1.0

    def test_explicit_prices_higher(self, comparison):
        """explicit path의 PV가 합리적 범위."""
        assert comparison.exp_result.gross_pv_usd > 0
        assert comparison.exp_result.mult_pre_tax > 0.5

    def test_with_transaction_cost(self, tmp_cache):
        cr = compare_price_modes(
            ["SPY"], start="2023-01-01", end="2024-01-01",
            transaction_cost_bps=10, cache_dir=tmp_cache,
            av_key=AV_KEY, fred_key=FRED_KEY,
        )
        assert cr.adj_attribution.total_transaction_cost_usd > 0
        assert cr.exp_attribution.total_transaction_cost_usd > 0
