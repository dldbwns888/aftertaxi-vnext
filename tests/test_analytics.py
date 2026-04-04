# -*- coding: utf-8 -*-
"""test_analytics.py — analytics MVP 테스트"""

import numpy as np
import pandas as pd
import pytest
from aftertaxi.workbench.analytics import (
    build_asset_contribution, build_underwater, AssetContribution, UnderwaterData,
)


class TestAssetContribution:

    def test_single_asset(self):
        prices = pd.DataFrame({"SPY": [100, 110, 120]},
                               index=pd.date_range("2020-01", periods=3, freq="ME"))
        result = build_asset_contribution({"SPY": 1.0}, prices, invested_usd=10000)
        assert len(result) == 1
        assert result[0].asset == "SPY"
        assert abs(result[0].target_weight - 1.0) < 0.01
        assert abs(result[0].cumulative_return - 0.20) < 0.01
        assert abs(result[0].contribution_pct - 100.0) < 0.1

    def test_two_assets(self):
        prices = pd.DataFrame({
            "SPY": [100, 120, 150],  # +50%
            "TLT": [100, 95, 90],    # -10%
        }, index=pd.date_range("2020-01", periods=3, freq="ME"))
        result = build_asset_contribution({"SPY": 0.6, "TLT": 0.4}, prices)
        # SPY: 0.6 × 0.5 = 0.30
        # TLT: 0.4 × -0.1 = -0.04
        # total = 0.26
        spy = [r for r in result if r.asset == "SPY"][0]
        tlt = [r for r in result if r.asset == "TLT"][0]
        assert spy.contribution_pct > 100  # SPY 기여 > 100% (TLT가 깎으니)
        assert tlt.contribution_pct < 0    # TLT 기여 음수

    def test_missing_asset(self):
        prices = pd.DataFrame({"SPY": [100, 120]},
                               index=pd.date_range("2020-01", periods=2, freq="ME"))
        result = build_asset_contribution({"SPY": 0.6, "QQQ": 0.4}, prices)
        assert len(result) == 1  # QQQ 없으면 skip


class TestUnderwater:

    def test_no_drawdown(self):
        mv = np.array([100, 110, 120, 130])
        uw = build_underwater(mv)
        assert abs(uw.max_drawdown) < 0.001
        assert uw.max_recovery_months == 0

    def test_simple_drawdown(self):
        mv = np.array([100, 120, 90, 95, 130])
        uw = build_underwater(mv)
        assert uw.max_drawdown < -0.20  # 120→90 = -25%
        assert uw.max_recovery_months >= 2  # 90→130 회복

    def test_empty(self):
        uw = build_underwater(np.array([]))
        assert uw.max_drawdown == 0.0
        assert uw.max_recovery_months == 0
