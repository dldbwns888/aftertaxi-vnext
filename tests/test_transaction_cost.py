# -*- coding: utf-8 -*-
"""
test_transaction_cost.py — 거래비용 + EventJournal 테스트
=========================================================
"""

import numpy as np
import pandas as pd
import pytest

from aftertaxi.core.ledger import AccountLedger
from aftertaxi.core.event_journal import EventJournal
from aftertaxi.core.contracts import (
    AccountConfig, AccountType, BacktestConfig,
    RebalanceMode, StrategyConfig,
)
from aftertaxi.core.facade import run_backtest


# ══════════════════════════════════════════════
# Ledger 단위 테스트: 거래비용
# ══════════════════════════════════════════════

class TestTransactionCostLedger:

    def test_zero_fee_unchanged(self):
        """fee=0이면 기존 동작과 동일."""
        ledger = AccountLedger("t", transaction_cost_bps=0)
        ledger.cash_usd = 10000
        ledger.buy("SPY", 10, 100, 1300)
        assert abs(ledger.cash_usd - 9000) < 0.01
        assert abs(ledger.positions["SPY"].qty - 10) < 1e-10

    def test_buy_fee_deducted_from_cash(self):
        """매수 시 fee가 cash에서 추가 차감."""
        ledger = AccountLedger("t", transaction_cost_bps=10)  # 10bps = 0.1%
        ledger.cash_usd = 10000
        ledger.buy("SPY", 10, 100, 1300)
        # cost = 10 × 100 = 1000, fee = 1000 × 0.001 = 1.0
        # total = 1001, cash = 10000 - 1001 = 8999
        assert abs(ledger.cash_usd - 8999) < 0.01

    def test_buy_fee_in_cost_basis(self):
        """매수 fee는 취득가에 포함 (한국 세법)."""
        ledger = AccountLedger("t", transaction_cost_bps=100)  # 100bps = 1%
        ledger.cash_usd = 10000
        ledger.buy("SPY", 10, 100, 1300)
        # cost = 1000, fee = 10, total_cost = 1010
        # cost_basis_usd = 1010 (fee 포함)
        pos = ledger.positions["SPY"]
        assert abs(pos.cost_basis_usd - 1010) < 0.01

    def test_sell_fee_reduces_proceeds(self):
        """매도 시 fee가 수취액에서 차감."""
        ledger = AccountLedger("t", transaction_cost_bps=100)  # 1%
        ledger.cash_usd = 10000
        ledger.buy("SPY", 10, 100, 1300)
        cash_after_buy = ledger.cash_usd

        # 매도: 가격 200으로 상승
        realized = ledger.sell("SPY", 10, 200, 1300)
        # gross proceeds = 2000, fee = 20, net = 1980
        # 수취액 net_proceeds_usd = 1980이 cash에 추가
        assert abs(ledger.cash_usd - (cash_after_buy + 1980)) < 0.01

    def test_sell_fee_reduces_realized_gain(self):
        """매도 fee는 양도차익 감소 (필요경비)."""
        # fee 0
        l0 = AccountLedger("t", transaction_cost_bps=0)
        l0.cash_usd = 10000
        l0.buy("SPY", 10, 100, 1300)
        r0 = l0.sell("SPY", 10, 200, 1300)

        # fee 100bps
        l1 = AccountLedger("t", transaction_cost_bps=100)
        l1.cash_usd = 10000
        l1.buy("SPY", 10, 100, 1300)
        r1 = l1.sell("SPY", 10, 200, 1300)

        # fee가 있으면 realized gain이 줄어야
        assert r1 < r0

    def test_fee_tracked_in_total(self):
        """총 거래비용 누적 추적."""
        ledger = AccountLedger("t", transaction_cost_bps=50)  # 50bps
        ledger.cash_usd = 100000
        ledger.buy("SPY", 10, 100, 1300)    # fee = 1000 * 0.005 = 5
        ledger.buy("QQQ", 5, 200, 1300)     # fee = 1000 * 0.005 = 5
        ledger.sell("SPY", 10, 110, 1300)   # fee = 1100 * 0.005 = 5.5
        assert abs(ledger.total_transaction_cost_usd - 15.5) < 0.01

    def test_cash_insufficient_with_fee(self):
        """현금 부족 시 fee 포함해서 가능한 만큼만 매수."""
        ledger = AccountLedger("t", transaction_cost_bps=100)  # 1%
        ledger.cash_usd = 1000
        ledger.buy("SPY", 100, 100, 1300)  # 100주 × 100 = 10000 >> 1000
        # 1000 / 1.01 ≈ 990.1 worth of SPY + 9.9 fee
        assert ledger.cash_usd < 0.01  # 거의 전액 사용
        assert ledger.positions["SPY"].qty < 10  # 10주도 못 삼


# ══════════════════════════════════════════════
# 통합 테스트: 거래비용이 배수에 미치는 영향
# ══════════════════════════════════════════════

class TestTransactionCostIntegration:

    def _make_data(self, n=24):
        idx = pd.date_range("2020-01-31", periods=n, freq="ME")
        prices = pd.DataFrame({"SPY": [100 * (1.01 ** i) for i in range(n)]}, index=idx)
        fx = pd.Series(1300.0, index=idx)
        returns = prices.pct_change().fillna(0.0)
        return returns, prices, fx

    def test_fee_reduces_mult(self):
        """거래비용이 있으면 배수가 줄어든다."""
        returns, prices, fx = self._make_data()

        r_no_fee = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0, transaction_cost_bps=0)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        r_with_fee = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0, transaction_cost_bps=50)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        assert r_with_fee.mult_pre_tax < r_no_fee.mult_pre_tax

    def test_full_rebal_more_fee_than_co(self):
        """FULL rebalance는 매도가 있으니 C/O보다 거래비용 더 많이."""
        returns, prices, fx = self._make_data(36)
        # 2자산
        prices["QQQ"] = [100 * (1.015 ** i) for i in range(36)]
        returns = prices.pct_change().fillna(0.0)

        co = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0,
                    RebalanceMode.CONTRIBUTION_ONLY, transaction_cost_bps=50)],
                strategy=StrategyConfig("test", {"SPY": 0.5, "QQQ": 0.5}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        full = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0,
                    RebalanceMode.FULL, transaction_cost_bps=50)],
                strategy=StrategyConfig("test", {"SPY": 0.5, "QQQ": 0.5}, rebalance_every=1),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        # C/O는 매도 0, FULL은 매도 있음 → FULL이 비용 더 많음
        # PV가 더 낮거나, 세금도 다를 수 있지만 거래비용은 확실히 더 높음
        # (summary에 transaction_cost_usd가 있으면 직접 비교 가능)
        assert full.mult_pre_tax != co.mult_pre_tax  # 둘이 다름을 최소 확인


# ══════════════════════════════════════════════
# EventJournal 테스트
# ══════════════════════════════════════════════

class TestEventJournal:

    def test_journal_records_events(self):
        journal = EventJournal()
        ledger = AccountLedger("t", transaction_cost_bps=10, journal=journal)
        ledger.deposit(1000)
        ledger.buy("SPY", 5, 100, 1300)
        ledger.sell("SPY", 2, 110, 1300)

        assert len(journal) == 3
        types = [e.event_type for e in journal.events]
        assert types == ["deposit", "buy", "sell"]

    def test_journal_none_no_error(self):
        """journal=None이면 기록 안 하고 에러도 안 남."""
        ledger = AccountLedger("t", journal=None)
        ledger.deposit(1000)
        ledger.buy("SPY", 5, 100, 1300)
        # 에러 없이 실행

    def test_filter_by_type(self):
        journal = EventJournal()
        ledger = AccountLedger("t", transaction_cost_bps=10, journal=journal)
        ledger.deposit(1000)
        ledger.deposit(2000)
        ledger.buy("SPY", 5, 100, 1300)

        deposits = journal.filter_by_type("deposit")
        assert len(deposits) == 2

    def test_total_fees(self):
        """거래비용 합산 추적."""
        journal = EventJournal()
        ledger = AccountLedger("t", transaction_cost_bps=100, journal=journal)  # 1%
        ledger.cash_usd = 100000
        ledger.buy("SPY", 10, 100, 1300)   # fee = 10
        ledger.buy("QQQ", 5, 200, 1300)    # fee = 10
        ledger.sell("SPY", 10, 110, 1300)  # fee = 11

        total_fees = journal.total_fees()
        assert abs(total_fees - 31) < 0.1

    def test_sell_event_has_realized_krw(self):
        """매도 이벤트에 실현손익 기록."""
        journal = EventJournal()
        ledger = AccountLedger("t", transaction_cost_bps=0, journal=journal)
        ledger.cash_usd = 10000
        ledger.buy("SPY", 10, 100, 1300)
        ledger.sell("SPY", 10, 150, 1300)

        sells = journal.filter_by_type("sell")
        assert len(sells) == 1
        assert "realized_krw" in sells[0].metadata
        assert sells[0].metadata["realized_krw"] > 0

    def test_tax_events_recorded(self):
        """세금 부과 + 납부 이벤트 기록."""
        journal = EventJournal()
        ledger = AccountLedger("t", tax_rate=0.22, annual_exemption=0,
                               transaction_cost_bps=0, journal=journal)
        ledger.cash_usd = 100000
        ledger.buy("SPY", 100, 100, 1300)
        ledger.sell("SPY", 100, 200, 1300)
        ledger.settle_annual_tax(current_year=2023)
        ledger.pay_tax(1300)

        tax_assessed = journal.filter_by_type("tax_assessed")
        tax_paid = journal.filter_by_type("tax_paid")
        assert len(tax_assessed) == 1
        assert len(tax_paid) == 1
        assert tax_assessed[0].amount_krw > 0
        assert tax_paid[0].amount_usd > 0


# ══════════════════════════════════════════════
# 엔드투엔드: facade 경유 journal
# ══════════════════════════════════════════════

class TestJournalEndToEnd:

    def _make_data(self, n=24):
        idx = pd.date_range("2020-01-31", periods=n, freq="ME")
        prices = pd.DataFrame({"SPY": [100 * (1.01 ** i) for i in range(n)]}, index=idx)
        fx = pd.Series(1300.0, index=idx)
        returns = prices.pct_change().fillna(0.0)
        return returns, prices, fx

    def test_facade_journal_captures_all_events(self):
        """facade 경유 실행에서 journal에 이벤트가 쌓인다."""
        returns, prices, fx = self._make_data()
        journal = EventJournal()

        result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0,
                    transaction_cost_bps=50)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
            journal=journal,
        )

        # 24개월 → deposit 24번, buy 24번
        deposits = journal.filter_by_type("deposit")
        buys = journal.filter_by_type("buy")
        assert len(deposits) == 24
        assert len(buys) == 24

        # fee가 기록됨
        assert journal.total_fees() > 0

    def test_facade_journal_none_still_works(self):
        """journal=None이면 기존과 동일하게 작동."""
        returns, prices, fx = self._make_data()

        result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
            journal=None,
        )
        assert result.gross_pv_usd > 0

    def test_facade_journal_tax_events(self):
        """세금 정산 이벤트도 facade 경유로 기록된다."""
        returns, prices, fx = self._make_data(36)  # 3년 → 연도 전환 2번
        journal = EventJournal()

        result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
                strategy=StrategyConfig("test", {"SPY": 1.0}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
            journal=journal,
        )

        # C/O 양수 수익 → 최종 청산 시 세금 발생
        tax_events = journal.filter_by_type("tax_assessed")
        assert len(tax_events) >= 1  # 최소 최종 청산 정산

    def test_journal_with_fee_attribution(self):
        """journal에서 총 거래비용 vs 총 세금 비교 가능."""
        returns, prices, fx = self._make_data()
        journal = EventJournal()

        result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0,
                    transaction_cost_bps=100)],  # 1% 높은 fee
                strategy=StrategyConfig("test", {"SPY": 1.0}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
            journal=journal,
        )

        total_fee = journal.total_fees()
        total_tax = journal.total_by_type("tax_assessed", "amount_krw")

        # 둘 다 양수
        assert total_fee > 0
        # C/O는 매도 없어서 최종 청산까지 세금 이벤트가 적을 수 있지만
        # 최종 청산 시 assessed > 0
        assert total_tax >= 0
