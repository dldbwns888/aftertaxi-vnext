# -*- coding: utf-8 -*-
"""
test_attribution.py — ResultAttribution 테스트
===============================================
"""

import numpy as np
import pandas as pd
import pytest

from aftertaxi.core.contracts import (
    AccountConfig, AccountSummary, AccountType, BacktestConfig,
    EngineResult, PersonSummary, RebalanceMode, StrategyConfig, TaxSummary,
)
from aftertaxi.core.dividend import DividendSchedule
from aftertaxi.core.event_journal import EventJournal
from aftertaxi.core.facade import run_backtest
from aftertaxi.core.attribution import (
    AccountAttribution, ResultAttribution, build_attribution,
)


# ══════════════════════════════════════════════
# AccountSummary 필드 존재 검증
# ══════════════════════════════════════════════

class TestAccountSummaryFields:

    def test_attribution_fields_default_zero(self):
        """새 필드는 기본값 0 → 기존 코드 하위호환."""
        s = AccountSummary(
            account_id="t", account_type="TAXABLE",
            gross_pv_usd=2000, invested_usd=1000,
            tax_assessed_krw=0, tax_unpaid_krw=0,
            mdd=-0.1, n_months=12,
        )
        assert s.transaction_cost_usd == 0.0
        assert s.dividend_gross_usd == 0.0
        assert s.dividend_withholding_usd == 0.0
        assert s.dividend_net_usd == 0.0

    def test_attribution_fields_set(self):
        s = AccountSummary(
            account_id="t", account_type="TAXABLE",
            gross_pv_usd=2000, invested_usd=1000,
            tax_assessed_krw=100000, tax_unpaid_krw=0,
            mdd=-0.1, n_months=12,
            transaction_cost_usd=50,
            dividend_gross_usd=200,
            dividend_withholding_usd=30,
        )
        assert s.transaction_cost_usd == 50
        assert s.dividend_gross_usd == 200
        assert abs(s.dividend_net_usd - 170) < 0.01

    def test_fields_preserved_in_aggregate(self):
        """facade 실행 후 AccountSummary에 attribution 필드가 있다."""
        idx = pd.date_range("2020-01-31", periods=12, freq="ME")
        prices = pd.DataFrame({"SPY": [100 * (1.01**i) for i in range(12)]}, index=idx)
        fx = pd.Series(1300.0, index=idx)
        returns = prices.pct_change().fillna(0.0)

        result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0,
                    transaction_cost_bps=50)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        a = result.accounts[0]
        # fee > 0인 실행이니 transaction_cost > 0
        assert a.transaction_cost_usd > 0
        # 배당 schedule 없으니 배당 0
        assert a.dividend_gross_usd == 0.0

    def test_dividend_fields_populated(self):
        """배당 schedule 있으면 dividend 필드에 값이 채워진다."""
        idx = pd.date_range("2020-01-31", periods=24, freq="ME")
        prices = pd.DataFrame({"SPY": [400] * 24}, index=idx)
        fx = pd.Series(1300.0, index=idx)
        returns = prices.pct_change().fillna(0.0)

        result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
                dividend_schedule=DividendSchedule({"SPY": 0.02}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        a = result.accounts[0]
        assert a.dividend_gross_usd > 0
        assert a.dividend_withholding_usd > 0
        assert a.dividend_net_usd > 0
        assert abs(a.dividend_net_usd - (a.dividend_gross_usd - a.dividend_withholding_usd)) < 0.01


# ══════════════════════════════════════════════
# build_attribution 단위 테스트
# ══════════════════════════════════════════════

class TestBuildAttribution:

    def _mock_result(self, cost=10, div_gross=100, div_wh=15, tax=200000):
        return EngineResult(
            gross_pv_usd=25000, invested_usd=24000,
            gross_pv_krw=25000*1300, net_pv_krw=25000*1300 - 0,
            reporting_fx_rate=1300, mdd=-0.05,
            n_months=24, n_accounts=1,
            tax=TaxSummary(tax, 0, tax),
            accounts=[AccountSummary(
                "t", "TAXABLE", 25000, 24000, tax, 0, -0.05, 24,
                transaction_cost_usd=cost,
                dividend_gross_usd=div_gross,
                dividend_withholding_usd=div_wh,
            )],
            person=PersonSummary(),
            monthly_values=np.ones(24) * 25000,
        )

    def test_basic_attribution(self):
        result = self._mock_result()
        attr = build_attribution(result)
        assert isinstance(attr, ResultAttribution)
        assert attr.invested_usd == 24000
        assert attr.total_transaction_cost_usd == 10
        assert attr.total_dividend_gross_usd == 100
        assert attr.total_dividend_withholding_usd == 15
        assert abs(attr.total_dividend_net_usd - 85) < 0.01

    def test_account_breakdown(self):
        result = self._mock_result()
        attr = build_attribution(result)
        assert len(attr.account_attributions) == 1
        aa = attr.account_attributions[0]
        assert aa.account_id == "t"
        assert aa.transaction_cost_usd == 10
        assert aa.dividend_net_usd == 85

    def test_drag_percentages(self):
        result = self._mock_result(cost=240, tax=2_600_000)
        attr = build_attribution(result)
        # cost: 240/24000 = 1%
        assert abs(attr.cost_drag_pct - 1.0) < 0.01
        # tax: 2600000 / (25000*1300) = 0.08 = 8%
        assert abs(attr.tax_drag_pct - 8.0) < 0.1

    def test_zero_investment(self):
        """invested=0이면 drag % = 0 (div by zero 방지)."""
        result = EngineResult(
            gross_pv_usd=0, invested_usd=0,
            gross_pv_krw=0, net_pv_krw=0,
            reporting_fx_rate=1300, mdd=0,
            n_months=0, n_accounts=0,
            tax=TaxSummary(0, 0, 0),
            accounts=[], person=PersonSummary(), monthly_values=np.array([]),
        )
        attr = build_attribution(result)
        assert attr.cost_drag_pct == 0.0
        assert attr.tax_drag_pct == 0.0
        assert attr.mult_pre_tax == 0.0

    def test_summary_text(self):
        result = self._mock_result()
        attr = build_attribution(result)
        text = attr.summary_text()
        assert "ResultAttribution" in text
        assert "거래비용" in text
        assert "배당" in text

    def test_matches_engine_result(self):
        """attribution의 합산이 EngineResult와 일치."""
        result = self._mock_result(cost=50, div_gross=300, div_wh=45, tax=500000)
        attr = build_attribution(result)
        assert attr.invested_usd == result.invested_usd
        assert attr.gross_pv_usd == result.gross_pv_usd
        assert attr.total_tax_assessed_krw == result.tax.total_assessed_krw


# ══════════════════════════════════════════════
# 통합: facade 실행 → attribution
# ══════════════════════════════════════════════

class TestAttributionIntegration:

    def _make_data(self, n=24):
        idx = pd.date_range("2020-01-31", periods=n, freq="ME")
        prices = pd.DataFrame(
            {"SPY": [100 * (1.01**i) for i in range(n)]}, index=idx,
        )
        fx = pd.Series(1300.0, index=idx)
        returns = prices.pct_change().fillna(0.0)
        return returns, prices, fx

    def test_attribution_with_cost_and_dividend(self):
        """거래비용 + 배당 → attribution에 둘 다 반영."""
        returns, prices, fx = self._make_data()

        result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0,
                    transaction_cost_bps=50)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
                dividend_schedule=DividendSchedule({"SPY": 0.015}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        attr = build_attribution(result)
        assert attr.total_transaction_cost_usd > 0
        assert attr.total_dividend_gross_usd > 0
        assert attr.total_dividend_withholding_usd > 0
        assert attr.cost_drag_pct > 0
        assert attr.withholding_drag_pct > 0

    def test_attribution_no_cost_no_dividend(self):
        """비용 0 + 배당 0 → drag 전부 0."""
        returns, prices, fx = self._make_data()

        result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0,
                    transaction_cost_bps=0)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        attr = build_attribution(result)
        assert attr.total_transaction_cost_usd == 0.0
        assert attr.total_dividend_gross_usd == 0.0
        assert attr.cost_drag_pct == 0.0
        assert attr.withholding_drag_pct == 0.0

    def test_attribution_matches_journal(self):
        """attribution의 거래비용이 journal의 fee 합계와 일치."""
        returns, prices, fx = self._make_data()
        journal = EventJournal()

        result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0,
                    transaction_cost_bps=100)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
            journal=journal,
        )

        attr = build_attribution(result)
        journal_fees = journal.total_fees()

        # attribution의 거래비용 == journal의 fee 합계
        assert abs(attr.total_transaction_cost_usd - journal_fees) < 0.01
