# -*- coding: utf-8 -*-
"""
test_lane_b.py — Lane B 합성 + A/B overlap calibration 테스트
=============================================================
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pandas as pd
import pytest

from aftertaxi.core.contracts import EngineResult, PersonSummary
from aftertaxi.lanes.lane_b.synthetic import (
    SyntheticParams, synthesize_leveraged_returns, returns_to_prices,
)
from aftertaxi.lanes.lane_b.run import OverlapCalibration, calibrate_overlap


# ══════════════════════════════════════════════
# 합성 수익률 생성기 (네트워크 불필요)
# ══════════════════════════════════════════════

class TestSyntheticReturns:
    """합성 레버리지 수익률 단위 테스트."""

    def _make_data(self, n=60, ret=0.01, tbill=0.05):
        idx = pd.date_range("2020-01-31", periods=n, freq="ME")
        index_ret = pd.Series([ret] * n, index=idx)
        tbill_rate = pd.Series([tbill] * n, index=idx)
        return index_ret, tbill_rate

    def test_1x_leverage_no_drag(self):
        """1x = 지수 수익률 - fee."""
        index_ret, tbill = self._make_data()
        params = SyntheticParams(leverage=1.0, annual_fee=0.0, vol_lookback=12)
        syn = synthesize_leveraged_returns(index_ret, tbill, params)
        # 1x: financing=0, vol_drag=0 (since L²-L=0 for L=1)
        # syn ≈ index_ret
        np.testing.assert_allclose(syn.values, index_ret.values, atol=1e-6)

    def test_2x_higher_than_1x_in_uptrend(self):
        """상승장에서 2x > 1x (drag에도 불구)."""
        index_ret, tbill = self._make_data(ret=0.02, tbill=0.03)
        syn_1x = synthesize_leveraged_returns(
            index_ret, tbill, SyntheticParams(leverage=1.0, annual_fee=0),
        )
        syn_2x = synthesize_leveraged_returns(
            index_ret, tbill, SyntheticParams(leverage=2.0, annual_fee=0.0089),
        )
        # 누적 수익률 비교
        cum_1x = (1 + syn_1x).prod()
        cum_2x = (1 + syn_2x).prod()
        assert cum_2x > cum_1x, "2x should outperform 1x in strong uptrend"

    def test_vol_drag_reduces_returns(self):
        """vol drag는 수익률을 깎는다."""
        index_ret, tbill = self._make_data(ret=0.01, tbill=0.05)
        params = SyntheticParams(leverage=2.0, annual_fee=0, vol_lookback=12)
        syn = synthesize_leveraged_returns(index_ret, tbill, params)
        # constant returns → variance ≈ 0 → vol_drag ≈ 0
        # 2x: 기대 ≈ 2*0.01 - (0.05/12)*1 = 0.02 - 0.00417 ≈ 0.01583
        financing = (0.05 / 12) * 1.0
        expected = 2 * 0.01 - financing
        # constant returns이면 vol_drag ≈ 0이므로 근사
        np.testing.assert_allclose(syn.iloc[-1], expected, atol=1e-3)

    def test_output_length_matches_input(self):
        index_ret, tbill = self._make_data(n=100)
        syn = synthesize_leveraged_returns(index_ret, tbill)
        assert len(syn) == len(index_ret)

    def test_returns_to_prices(self):
        ret = pd.Series([0.1, -0.05, 0.03])
        prices = returns_to_prices(ret, base=100)
        assert abs(prices.iloc[0] - 110.0) < 1e-6
        assert abs(prices.iloc[1] - 104.5) < 1e-6


class TestOverlapCalibration:
    """A/B overlap calibration 단위 테스트."""

    def _make_mock_result(self, pv=2000, inv=1000, mdd=-0.1):
        from aftertaxi.core.contracts import (
            AccountSummary, PersonSummary, TaxSummary,
        )
        return EngineResult(
            gross_pv_usd=pv, invested_usd=inv,
            gross_pv_krw=pv * 1300, net_pv_krw=pv * 1300,
            reporting_fx_rate=1300, mdd=mdd,
            n_months=24, n_accounts=1,
            tax=TaxSummary(0, 0, 0),
            accounts=[AccountSummary("t", "TAXABLE", pv, inv, 0, 0, mdd, 24)],
            person=PersonSummary(),
            monthly_values=np.ones(24) * pv,
        )

    def test_identical_results(self):
        a = self._make_mock_result(pv=2000, inv=1000)
        b = self._make_mock_result(pv=2000, inv=1000)
        cal = calibrate_overlap(a, b)
        assert abs(cal.gap_pct) < 1e-6
        assert abs(cal.haircut_factor - 1.0) < 1e-6

    def test_b_optimistic(self):
        """B가 A보다 높으면 haircut < 1."""
        a = self._make_mock_result(pv=1800, inv=1000)
        b = self._make_mock_result(pv=2000, inv=1000)
        cal = calibrate_overlap(a, b)
        assert cal.gap_pct > 0  # B > A
        assert cal.haircut_factor < 1.0

    def test_b_conservative(self):
        """B가 A보다 낮으면 haircut > 1."""
        a = self._make_mock_result(pv=2000, inv=1000)
        b = self._make_mock_result(pv=1800, inv=1000)
        cal = calibrate_overlap(a, b)
        assert cal.gap_pct < 0
        assert cal.haircut_factor > 1.0


# ══════════════════════════════════════════════
# 실데이터 테스트 (yfinance 필요)
# ══════════════════════════════════════════════

yf = pytest.importorskip("yfinance", reason="yfinance not installed")


class TestLaneBLive:
    """실데이터로 Lane B 실행."""

    def test_run_lane_b_sp500(self):
        from aftertaxi.lanes.lane_b.run import run_lane_b
        result = run_lane_b(
            weights={"sp500_1x": 0.6, "sp500_2x": 0.4},
            synthetic_map={
                "sp500_1x": SyntheticParams(leverage=1.0, annual_fee=0.0003),
                "sp500_2x": SyntheticParams(leverage=2.0, annual_fee=0.0089),
            },
            monthly_usd=1000.0,
            start="2000-01-01",
            end="2023-12-31",
        )
        assert isinstance(result, EngineResult)
        assert result.n_months >= 200
        assert result.mult_pre_tax > 1.0

    def test_overlap_calibration_live(self):
        """Lane A(실제 SPY) vs Lane B(합성 1x SPY) 겹침 비교."""
        from aftertaxi.lanes.lane_a.run import run_lane_a
        from aftertaxi.lanes.lane_b.run import run_lane_b, calibrate_overlap

        # Lane A: 실제 SPY
        a = run_lane_a(
            tickers=["SPY"], weights={"SPY": 1.0},
            monthly_usd=1000.0, start="2010-01-01", end="2022-12-31",
        )

        # Lane B: 합성 1x (SPY 프록시)
        b = run_lane_b(
            weights={"sp500_1x": 1.0},
            synthetic_map={"sp500_1x": SyntheticParams(leverage=1.0, annual_fee=0.0003)},
            monthly_usd=1000.0, start="2010-01-01", end="2022-12-31",
        )

        cal = calibrate_overlap(a, b)
        # 1x 합성 vs 실제 SPY: 괴리가 ±20% 이내여야 합리적
        assert abs(cal.gap_pct) < 20.0, f"A/B gap too large: {cal.gap_pct:.1f}%"
        assert cal.overlap_months >= 100
