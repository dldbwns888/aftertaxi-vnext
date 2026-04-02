# -*- coding: utf-8 -*-
"""test_shiller.py — Shiller 152년 데이터 로더 테스트"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
import numpy as np


class TestShillerLoader:

    @pytest.fixture(scope="class")
    def data(self):
        from aftertaxi.loaders.shiller import load_shiller
        return load_shiller()

    def test_has_keys(self, data):
        for key in ["sp_prices", "sp_returns", "gs10_annual", "cpi",
                     "dividend_yield", "n_months", "start_date", "end_date"]:
            assert key in data

    def test_long_history(self, data):
        """최소 150년 = 1800개월."""
        assert data["n_months"] >= 1800

    def test_start_date(self, data):
        assert data["start_date"].year <= 1872

    def test_sp_returns_reasonable(self, data):
        """월간 평균 0.3~0.8% 범위."""
        mean = data["sp_returns"].mean()
        assert 0.003 < mean < 0.008

    def test_gs10_reasonable(self, data):
        """GS10 연율 평균 2~8% 범위."""
        mean = data["gs10_annual"].mean()
        assert 0.02 < mean < 0.08

    def test_no_nan_in_returns(self, data):
        assert data["sp_returns"].isna().sum() == 0

    def test_year_filter(self):
        from aftertaxi.loaders.shiller import load_shiller
        d = load_shiller(start_year=1950, end_year=2000)
        assert d["start_date"].year >= 1950
        assert d["end_date"].year <= 2000
        assert d["n_months"] < 700  # ~50년

    def test_lane_b_compatible(self, data):
        """Lane B synthetic에 필요한 형식과 호환."""
        sp = data["sp_returns_with_gs10"]
        gs = data["gs10_annual"]
        assert len(sp) == len(gs)
        assert len(sp) > 0
