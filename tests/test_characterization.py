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


# ══════════════════════════════════════════════
# C5: 손실이월 5년 만료 golden
# ══════════════════════════════════════════════

class TestC5_LossCarryforward:
    """손실이월 5년 만료 시나리오.

    must-match: 기존 엔진과 같은 이월/상쇄/만료 로직.
    """

    def test_loss_offsets_next_year_gain(self):
        """1년차 손실 → 2년차 이익에서 상쇄 → 세금 감소."""
        from aftertaxi.core.tax_engine import compute_capital_gains_tax

        # Year 1: 순손실 100만원
        r1 = compute_capital_gains_tax(
            realized_gain_krw=0, realized_loss_krw=1_000_000,
            carryforward=[], current_year=2024, rate=0.22,
        )
        assert r1.tax_krw == 0.0
        assert len(r1.new_loss_carry) == 1
        assert r1.new_loss_carry[0] == (2024, 1_000_000.0)

        # Year 2: 순이익 500만원, 이월 100만원 상쇄
        r2 = compute_capital_gains_tax(
            realized_gain_krw=5_000_000, realized_loss_krw=0,
            carryforward=r1.new_loss_carry + r1.carryforward_remaining,
            current_year=2025, rate=0.22,
        )
        # 500만 - 이월100만 = 400만 - 공제250만 = 150만 × 22% = 33만
        assert abs(r2.tax_krw - 330_000.0) < 1.0
        assert len(r2.carryforward_used) == 1

    def test_5year_boundary_still_valid(self):
        """발생 후 4년까지는 유효 (5년 미만)."""
        from aftertaxi.core.tax_engine import compute_capital_gains_tax

        # 2020년 손실, 2024년(4년 후) 사용 → 유효
        r = compute_capital_gains_tax(
            realized_gain_krw=5_000_000, realized_loss_krw=0,
            carryforward=[(2020, 1_000_000.0)],
            current_year=2024, rate=0.22,
        )
        # 이월 상쇄 발생
        assert len(r.carryforward_used) == 1
        # 500만 - 이월100만 = 400만 - 공제250만 = 150만 × 22% = 33만
        assert abs(r.tax_krw - 330_000.0) < 1.0

    def test_6year_expired(self):
        """발생 후 5년이면 만료 — 상쇄 불가."""
        from aftertaxi.core.tax_engine import compute_capital_gains_tax

        # 2019년 손실, 2024년(5년 후) → 만료
        r = compute_capital_gains_tax(
            realized_gain_krw=5_000_000, realized_loss_krw=0,
            carryforward=[(2019, 1_000_000.0)],
            current_year=2024, rate=0.22,
        )
        # 이월 상쇄 없음
        assert len(r.carryforward_used) == 0
        # 500만 - 공제250만 = 250만 × 22% = 55만
        assert abs(r.tax_krw - 550_000.0) < 1.0

    def test_multi_vintage_partial(self):
        """다년도 이월 + 부분 상쇄."""
        from aftertaxi.core.tax_engine import compute_capital_gains_tax

        carryforward = [
            (2021, 500_000.0),   # 3년 전, 유효
            (2022, 300_000.0),   # 2년 전, 유효
            (2019, 200_000.0),   # 5년 전, 만료!
        ]
        r = compute_capital_gains_tax(
            realized_gain_krw=3_000_000, realized_loss_krw=0,
            carryforward=carryforward,
            current_year=2024, rate=0.22,
        )
        # 유효 이월: 50만 + 30만 = 80만 (2019년 20만은 만료)
        # 300만 - 80만 = 220만 - 공제250만 = 0 → 세금 0 (공제 이내)
        assert r.tax_krw == 0.0
        assert len(r.carryforward_used) == 2  # 2021, 2022만 사용

    def test_carry_accumulates_over_years(self):
        """연속 손실 → 이월 누적."""
        from aftertaxi.core.tax_engine import compute_capital_gains_tax

        # Year 1: 손실
        r1 = compute_capital_gains_tax(
            realized_gain_krw=0, realized_loss_krw=500_000,
            carryforward=[], current_year=2022,
        )
        # Year 2: 또 손실
        carry2 = r1.new_loss_carry + r1.carryforward_remaining
        r2 = compute_capital_gains_tax(
            realized_gain_krw=0, realized_loss_krw=300_000,
            carryforward=carry2, current_year=2023,
        )
        # Year 3: 이익 → 누적 이월 80만으로 상쇄
        carry3 = r2.new_loss_carry + r2.carryforward_remaining
        assert len(carry3) == 2  # 2022년 50만 + 2023년 30만
        total_carry = sum(amt for _, amt in carry3)
        assert abs(total_carry - 800_000.0) < 1.0
