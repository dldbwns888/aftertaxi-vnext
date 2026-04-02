# -*- coding: utf-8 -*-
"""
test_health_insurance.py — 건보료 MVP + ISA 배당세 면제 테스트
==============================================================
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pandas as pd
import pytest

from aftertaxi.core.ledger import AccountLedger
from aftertaxi.core.event_journal import EventJournal
from aftertaxi.core.contracts import (
    AccountConfig, AccountSummary, AccountType, BacktestConfig,
    RebalanceMode, StrategyConfig,
)
from aftertaxi.core.dividend import DividendSchedule
from aftertaxi.core.facade import run_backtest
from aftertaxi.core.attribution import build_attribution


# ══════════════════════════════════════════════
# compute_health_insurance 순수 계산 테스트
# ══════════════════════════════════════════════

class TestComputeHealthInsurance:

    def test_below_threshold(self):
        from aftertaxi.core.tax_engine import compute_health_insurance
        r = compute_health_insurance(
            capital_gains_krw=15_000_000,
            dividend_income_krw=0,
        )
        assert not r.is_subject
        assert r.premium_krw == 0.0

    def test_above_threshold(self):
        from aftertaxi.core.tax_engine import compute_health_insurance
        r = compute_health_insurance(
            capital_gains_krw=30_000_000,  # 3천만 > 2천만 기준
            dividend_income_krw=0,
        )
        assert r.is_subject
        # (30M - 20M) × 6.99% = 699,000
        assert abs(r.premium_krw - 699_000) < 1.0

    def test_with_dividend(self):
        from aftertaxi.core.tax_engine import compute_health_insurance
        r = compute_health_insurance(
            capital_gains_krw=10_000_000,
            dividend_income_krw=15_000_000,
        )
        # 합산 25M > 20M → 부과
        assert r.is_subject
        assert abs(r.premium_krw - 5_000_000 * 0.0699) < 1.0

    def test_cap(self):
        from aftertaxi.core.tax_engine import compute_health_insurance
        r = compute_health_insurance(
            capital_gains_krw=1_000_000_000,  # 10억
            dividend_income_krw=0,
            annual_cap_krw=40_000_000,
        )
        assert r.premium_krw == 40_000_000  # 상한 적용

    def test_zero_income(self):
        from aftertaxi.core.tax_engine import compute_health_insurance
        r = compute_health_insurance(0, 0)
        assert not r.is_subject
        assert r.premium_krw == 0.0


# ══════════════════════════════════════════════
# 통합: 건보료가 결과에 반영되는지
# ══════════════════════════════════════════════

class TestHealthInsuranceIntegration:

    def _make_growth_data(self, n=60, monthly_return=0.02):
        """큰 양도차익이 나는 데이터."""
        idx = pd.date_range("2020-01-31", periods=n, freq="ME")
        prices_list = [100.0]
        for _ in range(1, n):
            prices_list.append(prices_list[-1] * (1 + monthly_return))
        prices = pd.DataFrame({"SPY": prices_list}, index=idx)
        fx = pd.Series(1300.0, index=idx)
        returns = prices.pct_change().fillna(0.0)
        return returns, prices, fx

    def test_health_insurance_off_no_effect(self):
        """enable_health_insurance=False면 건보료 0."""
        returns, prices, fx = self._make_growth_data()
        result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
                enable_health_insurance=False,
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )
        assert result.accounts[0].health_insurance_krw == 0.0

    def test_health_insurance_on_drag(self):
        """enable_health_insurance=True면 PV 감소."""
        returns, prices, fx = self._make_growth_data()

        r_off = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
                enable_health_insurance=False,
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        r_on = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
                enable_health_insurance=True,
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        # 건보료 켜면 PV 감소
        assert r_on.gross_pv_usd < r_off.gross_pv_usd
        # 건보료 버킷에 값이 있음
        assert r_on.accounts[0].health_insurance_krw > 0

    def test_health_insurance_in_attribution(self):
        """attribution에서 건보료 drag가 분리되어 보임."""
        returns, prices, fx = self._make_growth_data()

        result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
                enable_health_insurance=True,
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        attr = build_attribution(result)
        assert attr.total_health_insurance_krw > 0
        assert attr.total_capital_gains_tax_krw > 0
        # 둘이 분리되어 있음
        assert attr.total_health_insurance_krw != attr.total_capital_gains_tax_krw

    def test_health_insurance_journal_event(self):
        """건보료 이벤트가 journal에 기록."""
        returns, prices, fx = self._make_growth_data()
        journal = EventJournal()

        run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
                enable_health_insurance=True,
            ),
            returns=returns, prices=prices, fx_rates=fx,
            journal=journal,
        )

        hi_events = journal.filter_by_type("health_insurance")
        assert len(hi_events) >= 1
        assert hi_events[0].amount_krw > 0


# ══════════════════════════════════════════════
# ISA 배당세 면제 명시 테스트
# ══════════════════════════════════════════════

class TestISADividendTaxExemption:

    def test_isa_no_dividend_tax(self):
        """ISA 계좌는 운용 중 배당세 비과세."""
        idx = pd.date_range("2020-01-31", periods=36, freq="ME")
        prices = pd.DataFrame({"SPY": [400] * 36}, index=idx)
        fx = pd.Series(1300.0, index=idx)
        returns = prices.pct_change().fillna(0.0)
        journal = EventJournal()

        result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("isa", AccountType.ISA, 1000.0)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
                dividend_schedule=DividendSchedule({"SPY": 0.02}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
            journal=journal,
        )

        # ISA는 배당세 이벤트가 없어야
        div_tax_events = journal.filter_by_type("dividend_tax")
        assert len(div_tax_events) == 0

        # 계좌 요약에서 배당세 = 0
        assert result.accounts[0].dividend_tax_krw == 0.0
