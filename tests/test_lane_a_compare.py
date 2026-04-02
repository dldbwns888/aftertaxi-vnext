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


@pytest.fixture
def tmp_cache():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


class TestComparisonHarness:

    def test_returns_comparison_result(self, tmp_cache):
        """비교 결과가 ComparisonResult."""
        cr = compare_price_modes(
            ["SPY"], start="2023-01-01", end="2024-01-01",
            cache_dir=tmp_cache,
        )
        assert isinstance(cr, ComparisonResult)

    def test_both_paths_run(self, tmp_cache):
        """adjusted와 explicit 모두 양수 PV."""
        cr = compare_price_modes(
            ["SPY"], start="2023-01-01", end="2024-01-01",
            cache_dir=tmp_cache,
        )
        assert cr.adj_result.gross_pv_usd > 0
        assert cr.exp_result.gross_pv_usd > 0

    def test_explicit_has_dividends(self, tmp_cache):
        """explicit path에서 배당이 보임."""
        cr = compare_price_modes(
            ["SPY"], start="2023-01-01", end="2024-01-01",
            cache_dir=tmp_cache,
        )
        assert cr.exp_attribution.total_dividend_gross_usd > 0
        # adjusted path에서는 배당 schedule 없으므로 0
        assert cr.adj_attribution.total_dividend_gross_usd == 0

    def test_delta_table_structure(self, tmp_cache):
        """delta table이 올바른 구조."""
        cr = compare_price_modes(
            ["SPY"], start="2023-01-01", end="2024-01-01",
            cache_dir=tmp_cache,
        )
        table = cr.delta_table()
        assert len(table) >= 10
        for row in table:
            assert "항목" in row
            assert "adjusted" in row
            assert "explicit" in row
            assert "차이" in row
            assert "차이%" in row

    def test_summary_text(self, tmp_cache):
        """summary_text가 읽을 수 있는 형태."""
        cr = compare_price_modes(
            ["SPY"], start="2023-01-01", end="2024-01-01",
            cache_dir=tmp_cache,
        )
        text = cr.summary_text()
        assert "Lane A Price Mode Comparison" in text
        assert "adjusted" in text
        assert "explicit" in text
        assert "해석" in text

    def test_same_invested(self, tmp_cache):
        """두 경로의 투자금이 동일."""
        cr = compare_price_modes(
            ["SPY"], start="2023-01-01", end="2024-01-01",
            monthly_contribution=1000.0,
            cache_dir=tmp_cache,
        )
        assert abs(cr.adj_result.invested_usd - cr.exp_result.invested_usd) < 1.0

    def test_pv_difference_reasonable(self, tmp_cache):
        """두 경로의 PV 차이가 합리적 범위 (±20%)."""
        cr = compare_price_modes(
            ["SPY"], start="2023-01-01", end="2024-01-01",
            cache_dir=tmp_cache,
        )
        ratio = cr.exp_result.gross_pv_usd / cr.adj_result.gross_pv_usd
        assert 0.80 < ratio < 1.20, f"PV ratio {ratio:.3f} out of range"

    def test_with_transaction_cost(self, tmp_cache):
        """거래비용 추가해도 비교 정상."""
        cr = compare_price_modes(
            ["SPY"], start="2023-01-01", end="2024-01-01",
            transaction_cost_bps=10,
            cache_dir=tmp_cache,
        )
        assert cr.adj_attribution.total_transaction_cost_usd > 0
        assert cr.exp_attribution.total_transaction_cost_usd > 0
