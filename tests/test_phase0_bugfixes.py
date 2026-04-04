# -*- coding: utf-8 -*-
"""
test_phase0_bugfixes.py — L1, L2, R2 버그 수정 검증
=====================================================
Phase 0: 이월결손금 연도추적 + weight 정규화 통일.
"""

import numpy as np
import pytest

from aftertaxi.core.ledger import AccountLedger


# ══════════════════════════════════════════════
# L1: 이월결손금 부분상쇄 시 원래 연도 유지
# ══════════════════════════════════════════════

class TestL1_CarryforwardYearPreservation:

    def _make_ledger(self):
        return AccountLedger(
            account_id="test", account_type="TAXABLE",
            tax_rate=0.22, annual_exemption=0,  # 공제 0으로 단순화
        )

    def test_partial_offset_keeps_original_year(self):
        """2020년 손실 100만 중 60만만 상쇄 → 남은 40만은 2020년 유지."""
        ledger = self._make_ledger()
        ledger.loss_carryforward_krw = [(2020, 1_000_000)]

        # 2022년에 60만 이익 실현
        ledger.annual_realized_gain_krw = 600_000
        ledger.settle_annual_tax(current_year=2022)

        # 남은 이월결손금: 40만, 연도=2020 (2022가 아님!)
        assert len(ledger.loss_carryforward_krw) == 1
        yr, amt = ledger.loss_carryforward_krw[0]
        assert yr == 2020, f"연도가 {yr}로 리셋됨 (expected 2020)"
        assert abs(amt - 400_000) < 1.0

    def test_full_offset_removes_carry(self):
        """이익이 이월결손금보다 크면 carry 전부 소진."""
        ledger = self._make_ledger()
        ledger.loss_carryforward_krw = [(2020, 500_000)]

        ledger.annual_realized_gain_krw = 800_000
        ledger.settle_annual_tax(current_year=2022)

        # carry 전부 소진, 남은 이익 30만에 과세
        assert len(ledger.loss_carryforward_krw) == 0
        expected_tax = 300_000 * 0.22
        assert abs(ledger._total_tax_assessed_krw - expected_tax) < 1.0

    def test_multi_year_carry_preserves_each_year(self):
        """여러 연도 이월결손금 — 부분상쇄 시 각 연도 유지."""
        ledger = self._make_ledger()
        ledger.loss_carryforward_krw = [
            (2019, 200_000),
            (2021, 300_000),
        ]

        # 2023년에 250_000 이익 → 2019년 200k 전소, 2021년 50k 소진
        ledger.annual_realized_gain_krw = 250_000
        ledger.settle_annual_tax(current_year=2023)

        assert len(ledger.loss_carryforward_krw) == 1
        yr, amt = ledger.loss_carryforward_krw[0]
        assert yr == 2021, f"연도가 {yr}로 리셋됨 (expected 2021)"
        assert abs(amt - 250_000) < 1.0

    def test_5year_expiry(self):
        """5년 지난 이월결손금은 만료."""
        ledger = self._make_ledger()
        ledger.loss_carryforward_krw = [
            (2017, 500_000),  # 2023 - 2017 = 6 → 만료
            (2019, 300_000),  # 2023 - 2019 = 4 → 유효
        ]

        ledger.annual_realized_gain_krw = 100_000
        ledger.settle_annual_tax(current_year=2023)

        # 2017년 만료, 2019년에서 100k 상쇄 → 200k 남음
        assert len(ledger.loss_carryforward_krw) == 1
        yr, amt = ledger.loss_carryforward_krw[0]
        assert yr == 2019
        assert abs(amt - 200_000) < 1.0

    def test_5year_boundary_exact(self):
        """정확히 5년 = 만료."""
        ledger = self._make_ledger()
        ledger.loss_carryforward_krw = [(2018, 100_000)]  # 2023 - 2018 = 5 → 만료

        ledger.annual_realized_gain_krw = 50_000
        ledger.settle_annual_tax(current_year=2023)

        # 2018년 만료 → 상쇄 불가, 50k에 과세
        assert len(ledger.loss_carryforward_krw) == 0
        expected_tax = 50_000 * 0.22
        assert abs(ledger._total_tax_assessed_krw - expected_tax) < 1.0


# ══════════════════════════════════════════════
# L2: 순손실 시 기존 이월결손금 보존
# ══════════════════════════════════════════════

class TestL2_CarryforwardPreservationOnLoss:

    def _make_ledger(self):
        return AccountLedger(
            account_id="test", account_type="TAXABLE",
            tax_rate=0.22, annual_exemption=0,
        )

    def test_net_loss_preserves_old_carry(self):
        """올해 순손실 → 기존 이월결손금 + 올해 손실 모두 보존."""
        ledger = self._make_ledger()
        ledger.loss_carryforward_krw = [(2020, 500_000)]

        # 2022년에 순손실 200k
        ledger.annual_realized_loss_krw = 200_000
        ledger.settle_annual_tax(current_year=2022)

        # 기존 500k(2020) + 올해 200k(2022) = 2건
        assert len(ledger.loss_carryforward_krw) == 2

        years = {yr for yr, _ in ledger.loss_carryforward_krw}
        assert 2020 in years, "기존 2020년 이월결손금이 사라짐"
        assert 2022 in years, "올해 2022년 손실이 안 들어감"

        total = sum(amt for _, amt in ledger.loss_carryforward_krw)
        assert abs(total - 700_000) < 1.0

    def test_net_loss_no_tax(self):
        """순손실이면 세금 0."""
        ledger = self._make_ledger()
        ledger.loss_carryforward_krw = [(2020, 100_000)]
        ledger.annual_realized_loss_krw = 50_000
        ledger.settle_annual_tax(current_year=2022)

        assert ledger._total_tax_assessed_krw == 0.0

    def test_zero_net_no_carry_duplication(self):
        """이익=손실=0이면 carry 불필요."""
        ledger = self._make_ledger()
        ledger.loss_carryforward_krw = [(2020, 100_000)]
        ledger.settle_annual_tax(current_year=2022)

        # 기존 carry만 유지, 올해 0 손실은 추가 안 함
        assert len(ledger.loss_carryforward_krw) == 1
        assert ledger.loss_carryforward_krw[0] == (2020, 100_000)


# ══════════════════════════════════════════════
# R2: C/O vs FULL weight 정규화 통일
# ══════════════════════════════════════════════

class TestR2_WeightNormalization:

    def test_co_and_full_same_total_investment(self):
        """weights 합 < 1일 때 C/O와 FULL이 같은 비율로 투자."""
        import pandas as pd
        from aftertaxi.core.contracts import (
            AccountConfig, AccountType, BacktestConfig,
            RebalanceMode, StrategyConfig,
        )
        from aftertaxi.core.facade import run_backtest

        # weights 합 = 0.8 (의도적으로 1 미만)
        weights = {"A": 0.5, "B": 0.3}

        idx = pd.date_range("2020-01-31", periods=12, freq="ME")
        prices = pd.DataFrame({"A": [100]*12, "B": [100]*12}, index=idx)
        fx = pd.Series(1300.0, index=idx)
        returns = prices.pct_change().fillna(0.0)

        # C/O 실행
        co_result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0, RebalanceMode.CONTRIBUTION_ONLY)],
                strategy=StrategyConfig("test", weights),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        # FULL 실행
        full_result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0, RebalanceMode.FULL)],
                strategy=StrategyConfig("test", weights, rebalance_every=1),
            ),
            returns=returns, prices=prices, fx_rates=fx,
        )

        # 가격 변동 없으므로 둘 다 invested_usd와 거의 같아야 함
        # 핵심: FULL이 현금을 20% 남기지 않음
        co_cash_ratio = 1.0 - co_result.gross_pv_usd / co_result.invested_usd
        full_cash_ratio = 1.0 - full_result.gross_pv_usd / full_result.invested_usd

        # 둘 다 현금 비율이 비슷해야 (정규화 통일)
        assert abs(co_cash_ratio - full_cash_ratio) < 0.05, \
            f"C/O cash ratio {co_cash_ratio:.3f} vs FULL {full_cash_ratio:.3f}"
