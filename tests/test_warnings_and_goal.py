# -*- coding: utf-8 -*-
"""test_warnings_and_goal.py — 경고 + 목표 역산 테스트"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pandas as pd
import pytest

from aftertaxi.apps.gui.draft_models import (
    StrategyDraft, AccountDraft, BacktestDraft,
)


def _sample_data(n=60, seed=42):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-31", periods=n, freq="ME")
    returns = pd.DataFrame({"SPY": rng.normal(0.008, 0.04, n)}, index=idx)
    prices = 100 * (1 + returns).cumprod()
    fx = pd.Series(1300.0, index=idx)
    return returns, prices, fx


class TestDraftWarnings:

    def test_no_warnings_normal(self):
        d = BacktestDraft(
            strategy=StrategyDraft(type="spy_bnh"),
            accounts=[AccountDraft(type="TAXABLE", monthly=1000)],
            n_months=120,
        )
        assert d.warn() == []

    def test_isa_cap_warning(self):
        d = BacktestDraft(
            strategy=StrategyDraft(type="spy_bnh"),
            accounts=[AccountDraft(type="ISA", monthly=3000)],
        )
        warnings = d.warn()
        assert any("ISA" in w and "한도" in w for w in warnings)

    def test_leveraged_vol_warning(self):
        d = BacktestDraft(
            strategy=StrategyDraft(type="q60s40"),  # SSO 포함
            accounts=[AccountDraft(type="TAXABLE", monthly=1000)],
            n_months=240,
        )
        warnings = d.warn()
        assert any("레버리지" in w for w in warnings)

    def test_high_contribution_progressive_warning(self):
        d = BacktestDraft(
            strategy=StrategyDraft(type="spy_bnh"),
            accounts=[AccountDraft(type="TAXABLE", monthly=3000)],
            n_months=240,
        )
        warnings = d.warn()
        assert any("누진" in w for w in warnings)


class TestGoalCalc:

    def test_basic(self):
        from aftertaxi.workbench.goal_calc import find_monthly_for_goal
        returns, prices, fx = _sample_data(120)

        result = find_monthly_for_goal(
            target_krw=200_000_000,
            strategy_payload={"type": "spy_bnh"},
            returns=returns, prices=prices, fx_rates=fx,
        )
        assert result.monthly_usd > 0
        assert abs(result.achieved_krw - result.target_krw) / result.target_krw < 0.05

    def test_higher_goal_needs_more(self):
        from aftertaxi.workbench.goal_calc import find_monthly_for_goal
        returns, prices, fx = _sample_data(120)

        r_low = find_monthly_for_goal(
            target_krw=100_000_000,
            strategy_payload={"type": "spy_bnh"},
            returns=returns, prices=prices, fx_rates=fx,
        )
        r_high = find_monthly_for_goal(
            target_krw=300_000_000,
            strategy_payload={"type": "spy_bnh"},
            returns=returns, prices=prices, fx_rates=fx,
        )
        assert r_high.monthly_usd > r_low.monthly_usd

    def test_summary_text(self):
        from aftertaxi.workbench.goal_calc import find_monthly_for_goal
        returns, prices, fx = _sample_data(60)
        result = find_monthly_for_goal(
            target_krw=100_000_000,
            strategy_payload={"type": "spy_bnh"},
            returns=returns, prices=prices, fx_rates=fx,
        )
        text = result.summary_text()
        assert "목표" in text
        assert "필요 월 납입" in text
