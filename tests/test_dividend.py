# -*- coding: utf-8 -*-
"""
test_dividend.py — 배당 MVP 테스트
===================================
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pandas as pd
import pytest

from aftertaxi.core.ledger import AccountLedger
from aftertaxi.core.dividend import DividendEvent, DividendSchedule
from aftertaxi.core.event_journal import EventJournal
from aftertaxi.core.contracts import (
    AccountConfig, AccountType, BacktestConfig,
    RebalanceMode, StrategyConfig,
)
from aftertaxi.core.facade import run_backtest


# ══════════════════════════════════════════════
# DividendEvent 단위 테스트
# ══════════════════════════════════════════════

class TestDividendEvent:

    def test_net_per_share(self):
        e = DividendEvent("SPY", gross_per_share_usd=1.0, withholding_rate=0.15)
        assert abs(e.net_per_share_usd - 0.85) < 1e-6

    def test_withholding_per_share(self):
        e = DividendEvent("SPY", gross_per_share_usd=2.0, withholding_rate=0.15)
        assert abs(e.withholding_per_share_usd - 0.30) < 1e-6

    def test_zero_withholding(self):
        e = DividendEvent("SPY", gross_per_share_usd=1.0, withholding_rate=0.0)
        assert abs(e.net_per_share_usd - 1.0) < 1e-6


class TestDividendSchedule:

    def test_quarterly_dividend_months(self):
        s = DividendSchedule({"SPY": 0.02}, frequency=4)
        # 분기 배당: step 2,5,8,11 (3,6,9,12월)
        div_months = [i for i in range(12) if s.is_dividend_month(i)]
        assert len(div_months) == 4

    def test_monthly_dividend(self):
        s = DividendSchedule({"SPY": 0.02}, frequency=12)
        div_months = [i for i in range(12) if s.is_dividend_month(i)]
        assert len(div_months) == 12

    def test_create_event(self):
        s = DividendSchedule({"SPY": 0.02}, frequency=4)
        e = s.create_event("SPY", current_price=400)
        assert e is not None
        # gross = 400 × 0.02 / 4 = 2.0
        assert abs(e.gross_per_share_usd - 2.0) < 1e-6

    def test_no_yield_returns_none(self):
        s = DividendSchedule({"SPY": 0.02})
        e = s.create_event("QQQ", current_price=300)
        assert e is None


# ══════════════════════════════════════════════
# Ledger 배당 처리 테스트
# ══════════════════════════════════════════════

class TestLedgerDividend:

    def test_cash_dividend(self):
        """배당 현금유지: net이 cash에 추가."""
        ledger = AccountLedger("t")
        ledger.cash_usd = 10000
        ledger.buy("SPY", 10, 100, 1300)

        net = ledger.apply_dividend("SPY", gross_per_share=1.0,
                                     withholding_rate=0.15, fx_rate=1300,
                                     reinvest=False)
        # net = 10 × 1.0 × 0.85 = 8.5
        assert abs(net - 8.5) < 0.01
        # cash 증가 확인
        assert ledger.cash_usd > 9000  # 초기 9000 + 8.5

    def test_reinvest_dividend(self):
        """배당 재투자: net으로 같은 자산 매수."""
        ledger = AccountLedger("t")
        ledger.cash_usd = 10000
        ledger.buy("SPY", 10, 100, 1300)
        qty_before = ledger.positions["SPY"].qty

        ledger.apply_dividend("SPY", gross_per_share=2.0,
                              withholding_rate=0.15, fx_rate=1300,
                              reinvest=True, px_usd=100)
        # net = 10 × 2.0 × 0.85 = 17.0 → 0.17주 추가 매수
        assert ledger.positions["SPY"].qty > qty_before

    def test_withholding_tracked(self):
        """원천징수 누적 추적."""
        ledger = AccountLedger("t")
        ledger.cash_usd = 10000
        ledger.buy("SPY", 100, 100, 1300)

        ledger.apply_dividend("SPY", 1.0, 0.15, 1300, reinvest=False)
        # gross = 100, withholding = 15
        assert abs(ledger.annual_dividend_gross_usd - 100) < 0.01
        assert abs(ledger.annual_dividend_withholding_usd - 15) < 0.01
        assert abs(ledger.cumulative_dividend_gross_usd - 100) < 0.01

    def test_no_position_no_dividend(self):
        """보유 없으면 배당 0."""
        ledger = AccountLedger("t")
        net = ledger.apply_dividend("SPY", 1.0, 0.15, 1300, reinvest=False)
        assert net == 0.0

    def test_dividend_journal_event(self):
        """배당 이벤트가 journal에 기록."""
        journal = EventJournal()
        ledger = AccountLedger("t", journal=journal)
        ledger.cash_usd = 10000
        ledger.buy("SPY", 10, 100, 1300)
        ledger.apply_dividend("SPY", 1.0, 0.15, 1300, reinvest=False)

        divs = journal.filter_by_type("dividend")
        assert len(divs) == 1
        assert abs(divs[0].metadata["gross_usd"] - 10.0) < 0.01
        assert abs(divs[0].metadata["withholding_usd"] - 1.5) < 0.01


# ══════════════════════════════════════════════
# 통합: facade 경유 배당
# ══════════════════════════════════════════════

class TestDividendIntegration:

    def _make_data(self, n=24):
        idx = pd.date_range("2020-01-31", periods=n, freq="ME")
        prices = pd.DataFrame({"SPY": [400] * n}, index=idx)  # 가격 고정 (배당 효과만 보기)
        fx = pd.Series(1300.0, index=idx)
        returns = prices.pct_change().fillna(0.0)
        return returns, prices, fx

    def test_dividend_increases_pv(self):
        """배당(재투자) → PV 증가."""
        returns, prices, fx = self._make_data()

        # 배당 없음
        r_no_div = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        # 배당 있음 (연 2%, 분기)
        r_with_div = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
                dividend_schedule=DividendSchedule({"SPY": 0.02}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        # 가격 고정이므로 배당 재투자분만큼 PV 더 높음
        assert r_with_div.gross_pv_usd > r_no_div.gross_pv_usd

    def test_dividend_journal_integration(self):
        """facade 경유 배당 이벤트 기록."""
        returns, prices, fx = self._make_data()
        journal = EventJournal()

        run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
                dividend_schedule=DividendSchedule({"SPY": 0.02}, frequency=4),
            ),
            returns=returns, prices=prices, fx_rates=fx,
            journal=journal,
        )

        # 24개월, 분기 배당 → 8번 (처음 몇 개월은 보유 없을 수 있으나 첫달부터 매수)
        divs = journal.filter_by_type("dividend")
        assert len(divs) >= 6  # 최소 6번 이상 배당
        # 원천징수 기록 확인
        assert all(d.metadata["withholding_rate"] == 0.15 for d in divs)

    def test_no_dividend_schedule_unchanged(self):
        """dividend_schedule=None이면 기존과 동일."""
        returns, prices, fx = self._make_data()

        r = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
                dividend_schedule=None,
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )
        assert r.gross_pv_usd > 0
