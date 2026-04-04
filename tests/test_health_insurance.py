# -*- coding: utf-8 -*-
"""
test_health_insurance.py — 건보료 MVP + ISA 배당세 면제 테스트
==============================================================
"""

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
    """직장가입자 보수 외 소득월액보험료 근사 테스트.
    법적 근거: 시행령 제41조 — 양도소득은 소득월액 산정 대상 아님.
    """

    def test_below_threshold(self):
        from aftertaxi.core.tax_engine import compute_health_insurance
        r = compute_health_insurance(dividend_income_krw=15_000_000)
        assert not r.is_subject
        assert r.premium_krw == 0.0

    def test_above_threshold(self):
        from aftertaxi.core.tax_engine import compute_health_insurance
        r = compute_health_insurance(dividend_income_krw=30_000_000)
        assert r.is_subject
        # (30M - 20M) × 6.99% = 699,000
        assert abs(r.premium_krw - 699_000) < 1.0

    def test_cap(self):
        from aftertaxi.core.tax_engine import compute_health_insurance
        r = compute_health_insurance(
            dividend_income_krw=1_000_000_000,
            annual_cap_krw=40_000_000,
        )
        assert r.premium_krw == 40_000_000

    def test_zero_income(self):
        from aftertaxi.core.tax_engine import compute_health_insurance
        r = compute_health_insurance(dividend_income_krw=0)
        assert not r.is_subject
        assert r.premium_krw == 0.0

    def test_capital_gains_only_no_premium(self):
        """양도차익만 있고 배당 없으면 건보료 0.
        시행령 제41조: 양도소득은 소득월액 산정 대상 아님."""
        from aftertaxi.core.tax_engine import compute_health_insurance
        # 양도차익은 파라미터 자체가 없음 — 배당 0이면 건보료 0
        r = compute_health_insurance(dividend_income_krw=0)
        assert r.premium_krw == 0.0


# ══════════════════════════════════════════════
# 통합: 건보료가 결과에 반영되는지
# ══════════════════════════════════════════════

class TestHealthInsuranceIntegration:

    def _make_data_with_dividends(self, n=60, div_yield=0.05):
        """높은 배당수익률 + 큰 납입으로 건보료 기준 초과 유도.
        $100K/월 × 60개월, 5% 배당 → 연간 배당 ~$15K+ → ~20M+ KRW."""
        idx = pd.date_range("2020-01-31", periods=n, freq="ME")
        prices = pd.DataFrame({"SPY": [400] * n}, index=idx)
        fx = pd.Series(1300.0, index=idx)
        returns = prices.pct_change().fillna(0.0)
        div_schedule = DividendSchedule({"SPY": div_yield}, frequency=4)
        return returns, prices, fx, div_schedule

    MONTHLY = 100_000.0  # 큰 납입으로 건보료 기준 초과 보장

    def test_health_insurance_off_no_effect(self):
        """enable_health_insurance=False면 건보료 0."""
        returns, prices, fx, div_sched = self._make_data_with_dividends()
        result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, self.MONTHLY)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
                dividend_schedule=div_sched,
                enable_health_insurance=False,
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )
        assert result.accounts[0].health_insurance_krw == 0.0

    def test_health_insurance_on_drag(self):
        """배당소득이 충분하면 건보료 발생 → PV 감소."""
        returns, prices, fx, div_sched = self._make_data_with_dividends()

        r_off = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, self.MONTHLY)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
                dividend_schedule=div_sched,
                enable_health_insurance=False,
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        r_on = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, self.MONTHLY)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
                dividend_schedule=div_sched,
                enable_health_insurance=True,
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        assert r_on.gross_pv_usd < r_off.gross_pv_usd
        assert r_on.accounts[0].health_insurance_krw > 0

    def test_no_dividend_no_health_insurance(self):
        """배당 없이 양도차익만 있으면 건보료 0 (시행령 제41조)."""
        idx = pd.date_range("2020-01-31", periods=60, freq="ME")
        prices_list = [100.0]
        for _ in range(1, 60):
            prices_list.append(prices_list[-1] * 1.02)
        prices = pd.DataFrame({"SPY": prices_list}, index=idx)
        fx = pd.Series(1300.0, index=idx)
        returns = prices.pct_change().fillna(0.0)

        result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, self.MONTHLY)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
                enable_health_insurance=True,  # 켜져 있어도
                # dividend_schedule 없음 → 배당 0
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        # 양도차익은 있지만 배당이 없으므로 건보료 0
        assert result.accounts[0].health_insurance_krw == 0.0

    def test_health_insurance_in_attribution(self):
        returns, prices, fx, div_sched = self._make_data_with_dividends()
        result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, self.MONTHLY)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
                dividend_schedule=div_sched,
                enable_health_insurance=True,
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        attr = build_attribution(result)
        assert attr.total_health_insurance_krw > 0
        assert attr.total_capital_gains_tax_krw >= 0
        # 둘이 분리되어 있음
        assert attr.total_health_insurance_krw != attr.total_tax_assessed_krw

    def test_health_insurance_journal_event(self):
        returns, prices, fx, div_sched = self._make_data_with_dividends()
        journal = EventJournal()

        run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, self.MONTHLY)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
                dividend_schedule=div_sched,
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
