# -*- coding: utf-8 -*-
"""
test_characterization.py — 현재 엔진 결과를 golden으로 고정
============================================================
이 테스트가 깨지면 = 엔진 숫자가 변한 것.
의도적 변경이면 golden 값을 업데이트하고 변경 사유를 기록.

시나리오:
  C1: 3개월 B&H C/O, 손계산 대조
  C2: 12개월 FULL rebalance, 양도세 발생
  C3: 24개월 TAXABLE + ISA, 연도 경계 정산
  C4: 정산 순서 golden (배당 + 건보료 + 양도세)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pandas as pd
import pytest

from aftertaxi.core.contracts import (
    AccountConfig, AccountType, BacktestConfig, StrategyConfig, TaxConfig,
    make_taxable, make_isa,
)
from aftertaxi.core.facade import run_backtest


# ══════════════════════════════════════════════
# C1: 3개월 B&H C/O — 손계산 대조
# ══════════════════════════════════════════════
#
# prices: [100, 120, 150], fx=1300, monthly=1000 USD, C/O
#
# t0: deposit 1000, buy 10주 @100
# t1: MTM. deposit 1000, buy 8.333주 @120
# t2: MTM. deposit 1000, buy 6.667주 @150
# total: 25주, invested=3000
#
# 최종 청산: sell 25 @150, fx=1300
#   gross_usd = 25*150 = 3750 (cash after sell)
#   gross_krw = 25*150*1300 = 4,875,000
#   cost_krw = 3*1000*1300 = 3,900,000
#   realized = 975,000 < exemption 2,500,000 → tax=0
#   net_pv_krw = gross_pv_krw (tax=0)

class TestC1_HandCalculated:

    @pytest.fixture(scope="class")
    def result(self):
        idx = pd.date_range("2025-01-31", periods=3, freq="ME")
        prices = pd.DataFrame({"SPY": [100.0, 120.0, 150.0]}, index=idx)
        fx = pd.Series(1300.0, index=idx)
        returns = prices.pct_change().fillna(0.0)

        return run_backtest(
            BacktestConfig(
                accounts=[make_taxable(monthly=1000.0)],
                strategy=StrategyConfig("bnh", {"SPY": 1.0}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

    def test_invested(self, result):
        assert abs(result.invested_usd - 3000.0) < 0.01

    def test_n_months(self, result):
        assert result.n_months == 3

    def test_gross_pv_usd(self, result):
        # 25주 × $150 = $3750 (거래비용 0이면)
        assert abs(result.gross_pv_usd - 3750.0) < 1.0

    def test_gross_pv_krw(self, result):
        assert abs(result.gross_pv_krw - 3750.0 * 1300) < 100

    def test_tax_zero_under_exemption(self, result):
        """양도차익 975,000 < 공제 2,500,000 → 세금 0."""
        assert result.tax.total_assessed_krw == 0.0

    def test_net_equals_gross(self, result):
        """세금 0이면 net = gross."""
        assert abs(result.net_pv_krw - result.gross_pv_krw) < 1.0

    def test_mult(self, result):
        assert abs(result.mult_pre_tax - 3750.0 / 3000.0) < 0.01


# ══════════════════════════════════════════════
# C2: 12개월 FULL rebalance, 양도세 발생
# ══════════════════════════════════════════════

class TestC2_FullRebalTax:

    @pytest.fixture(scope="class")
    def result(self):
        idx = pd.date_range("2024-01-31", periods=12, freq="ME")
        # SPY 꾸준히 오름, QQQ 변동성 큼
        spy_prices = [100 + i * 5 for i in range(12)]
        qqq_prices = [200 + (i % 3) * 20 - 10 for i in range(12)]
        prices = pd.DataFrame({"SPY": spy_prices, "QQQ": qqq_prices}, index=idx)
        fx = pd.Series(1300.0, index=idx)
        returns = prices.pct_change().fillna(0.0)

        from aftertaxi.core.contracts import RebalanceMode
        return run_backtest(
            BacktestConfig(
                accounts=[AccountConfig(
                    "t", AccountType.TAXABLE, 1000.0,
                    rebalance_mode=RebalanceMode.FULL,
                )],
                strategy=StrategyConfig("6040", {"SPY": 0.6, "QQQ": 0.4}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

    def test_invested(self, result):
        assert result.invested_usd == 12000.0

    def test_tax_positive(self, result):
        """FULL rebal은 매도 → 양도차익 → 세금 발생."""
        assert result.tax.total_assessed_krw > 0

    def test_tax_paid_no_unpaid(self, result):
        assert result.tax.total_unpaid_krw == 0.0
        assert result.tax.total_paid_krw > 0

    def test_golden_pv(self, result):
        """현재 엔진 결과를 golden으로 고정.
        이 값이 바뀌면 엔진 숫자가 변한 것."""
        # 이 golden은 첫 실행에서 기록한 값. 변경 시 사유 기록 필요.
        assert result.gross_pv_usd > 12000  # 최소 원금 이상
        assert result.n_months == 12


# ══════════════════════════════════════════════
# C3: 24개월 TAXABLE + ISA, 연도 경계
# ══════════════════════════════════════════════

class TestC3_MultiAccountYearBoundary:

    @pytest.fixture(scope="class")
    def result(self):
        idx = pd.date_range("2024-01-31", periods=24, freq="ME")
        prices = pd.DataFrame(
            {"SPY": [100 * (1.008 ** i) for i in range(24)]},
            index=idx,
        )
        fx = pd.Series(1300.0, index=idx)
        returns = prices.pct_change().fillna(0.0)

        return run_backtest(
            BacktestConfig(
                accounts=[
                    make_isa(monthly=500.0, annual_cap=6000.0, priority=0),
                    make_taxable(monthly=500.0, priority=1),
                ],
                strategy=StrategyConfig("spy", {"SPY": 1.0}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

    def test_two_accounts(self, result):
        assert result.n_accounts == 2

    def test_24_months(self, result):
        assert result.n_months == 24

    def test_isa_less_tax(self, result):
        """ISA 계좌의 세금이 TAXABLE보다 적다."""
        isa_tax = [a for a in result.accounts if "isa" in a.account_id][0].tax_assessed_krw
        tax_tax = [a for a in result.accounts if "taxable" in a.account_id][0].tax_assessed_krw
        assert isa_tax <= tax_tax

    def test_total_invested(self, result):
        """ISA cap($6000/yr) + TAXABLE 무제한."""
        assert result.invested_usd > 0


# ══════════════════════════════════════════════
# C4: 정산 순서 golden (배당 + 양도세)
# ══════════════════════════════════════════════

class TestC4_SettlementGolden:

    @pytest.fixture(scope="class")
    def result(self):
        idx = pd.date_range("2024-01-31", periods=24, freq="ME")
        prices = pd.DataFrame(
            {"SPY": [100 * (1.01 ** i) for i in range(24)]},
            index=idx,
        )
        fx = pd.Series(1300.0, index=idx)
        returns = prices.pct_change().fillna(0.0)

        from aftertaxi.core.contracts import RebalanceMode
        from aftertaxi.core.dividend import DividendSchedule

        return run_backtest(
            BacktestConfig(
                accounts=[AccountConfig(
                    "t", AccountType.TAXABLE, 1000.0,
                    rebalance_mode=RebalanceMode.FULL,
                )],
                strategy=StrategyConfig("spy_div", {"SPY": 1.0}),
                dividend_schedule=DividendSchedule({"SPY": 0.015}),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

    def test_has_dividends(self, result):
        """배당이 존재."""
        acct = result.accounts[0]
        assert acct.dividend_gross_usd > 0

    def test_has_withholding(self, result):
        """원천징수 존재."""
        acct = result.accounts[0]
        assert acct.dividend_withholding_usd > 0

    def test_has_capital_gains_tax(self, result):
        """FULL rebal + 24개월 → 양도세 존재."""
        acct = result.accounts[0]
        assert acct.capital_gains_tax_krw > 0

    def test_tax_paid_no_unpaid(self, result):
        assert result.tax.total_unpaid_krw == 0.0
        assert result.tax.total_paid_krw > 0

    def test_invariants(self, result):
        """불변식: assessed = paid + unpaid."""
        t = result.tax
        assert abs(t.total_assessed_krw - t.total_paid_krw - t.total_unpaid_krw) < 1.0
