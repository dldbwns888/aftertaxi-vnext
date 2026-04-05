# -*- coding: utf-8 -*-
"""
test_engine_steps.py — engine_steps 빌딩 블록 직접 테스트
=========================================================
runner/signal_runner 통합 테스트와 별도로,
개별 step 함수의 경계 조건을 검증.
"""
import numpy as np
import pandas as pd
import pytest

from aftertaxi.core.engine_steps import (
    DUST_PCT,
    create_ledgers,
    build_fx_lookup,
    get_fx_rate,
    snapshot_tax,
    record_tax_delta,
    step_mark_to_market,
    step_record,
    drift_exceeds_threshold,
    execute_contribution_only,
    execute_full_rebalance,
    aggregate,
)
from aftertaxi.core.ledger import AccountLedger, TaxSnapshot, AnnualTaxRecord
from aftertaxi.core.contracts import (
    AccountConfig, AccountType, BacktestConfig, StrategyConfig,
    make_taxable, make_isa,
)
from aftertaxi.core.constants import QTY_EPSILON, AMOUNT_EPSILON_USD


# ══════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════

def _make_ledger(cash=1000.0, account_id="test"):
    """테스트용 간단 ledger 생성."""
    ledger = AccountLedger(account_id=account_id, tax_rate=0.22)
    ledger.cash_usd = cash
    return ledger


def _make_config(monthly=1000.0):
    """테스트용 최소 BacktestConfig."""
    return BacktestConfig(
        accounts=[make_taxable(monthly=monthly)],
        strategy=StrategyConfig("test", {"SPY": 1.0}),
    )


# ══════════════════════════════════════════════
# build_fx_lookup / get_fx_rate
# ══════════════════════════════════════════════

class TestFxLookup:
    def test_exact_match(self):
        dates = pd.date_range("2020-01-01", periods=3, freq="ME")
        fx = pd.Series([1200, 1250, 1300], index=dates)
        lookup = build_fx_lookup(fx)
        assert get_fx_rate(dates[1], lookup) == 1250

    def test_bisect_fallback(self):
        """정확히 일치하지 않는 날짜 → 가장 가까운 이전 날짜."""
        dates = pd.date_range("2020-01-31", periods=2, freq="ME")
        fx = pd.Series([1200, 1300], index=dates)
        lookup = build_fx_lookup(fx)
        # 2020-02-15는 dates 사이 → 1200 (2020-01-31 사용)
        mid = pd.Timestamp("2020-02-15")
        assert get_fx_rate(mid, lookup) == 1200

    def test_before_first_date(self):
        """모든 날짜보다 이전 → 첫 번째 값."""
        dates = pd.date_range("2020-06-01", periods=2, freq="ME")
        fx = pd.Series([1200, 1300], index=dates)
        lookup = build_fx_lookup(fx)
        before = pd.Timestamp("2020-01-01")
        assert get_fx_rate(before, lookup) == 1200


# ══════════════════════════════════════════════
# snapshot_tax / record_tax_delta
# ══════════════════════════════════════════════

class TestTaxSnapshot:
    def test_snapshot_empty_ledgers(self):
        snap = snapshot_tax({})
        assert snap.cgt_krw == 0.0
        assert snap.dividend_tax_krw == 0.0

    def test_snapshot_sums_multiple_ledgers(self):
        l1 = _make_ledger()
        l2 = _make_ledger(account_id="test2")
        l1._capital_gains_tax_assessed_krw = 100
        l2._capital_gains_tax_assessed_krw = 200
        snap = snapshot_tax({"a": l1, "b": l2})
        assert snap.cgt_krw == 300

    def test_diff_returns_annual_tax_record(self):
        before = TaxSnapshot(cgt_krw=100, dividend_tax_krw=10, health_insurance_krw=0)
        after = TaxSnapshot(cgt_krw=300, dividend_tax_krw=15, health_insurance_krw=5)
        rec = after.diff(before, 2024)
        assert isinstance(rec, AnnualTaxRecord)
        assert rec.year == 2024
        assert rec.cgt_krw == 200
        assert rec.total_krw == 210

    def test_record_tax_delta_appends(self):
        history = []
        before = TaxSnapshot(cgt_krw=0)
        after = TaxSnapshot(cgt_krw=100)
        record_tax_delta(history, before, after, 2024)
        assert len(history) == 1
        assert history[0].year == 2024
        assert history[0].cgt_krw == 100

    def test_record_tax_delta_merges_same_year(self):
        history = [AnnualTaxRecord(year=2024, cgt_krw=50, total_krw=50)]
        before = TaxSnapshot(cgt_krw=0)
        after = TaxSnapshot(cgt_krw=100)
        record_tax_delta(history, before, after, 2024)
        assert len(history) == 1  # 새 entry 안 만듦
        assert history[0].cgt_krw == 150  # 합산됨

    def test_record_tax_delta_skips_zero(self):
        history = []
        before = TaxSnapshot(cgt_krw=100)
        after = TaxSnapshot(cgt_krw=100)  # 차이 없음
        record_tax_delta(history, before, after, 2024)
        assert len(history) == 0


# ══════════════════════════════════════════════
# drift_exceeds_threshold
# ══════════════════════════════════════════════

class TestDriftExceedsThreshold:
    def test_empty_portfolio(self):
        """포지션 없고 cash도 없으면 False (total_value=0)."""
        ledger = _make_ledger(cash=0)
        assert not drift_exceeds_threshold(ledger, {"SPY": 1.0}, {"SPY": 100}, 0.05)

    def test_cash_only_has_drift(self):
        """cash만 있고 포지션 없으면 drift 100% → True."""
        ledger = _make_ledger(cash=1000)
        assert drift_exceeds_threshold(ledger, {"SPY": 1.0}, {"SPY": 100}, 0.05)

    def test_within_threshold(self):
        ledger = _make_ledger()
        ledger.buy("SPY", 10, 100, 1300)
        # SPY 100% 목표, 현재도 100% → 괴리 0%
        assert not drift_exceeds_threshold(
            ledger, {"SPY": 1.0}, {"SPY": 100}, 0.05)

    def test_exceeds_threshold(self):
        ledger = _make_ledger(cash=10000)
        ledger.buy("SPY", 60, 100, 1300)
        ledger.buy("QQQ", 40, 100, 1300)
        # SPY 60%, QQQ 40% 보유. 목표: SPY 50%, QQQ 50%
        # SPY 괴리 = |0.6 - 0.5| = 0.1 > 0.05
        assert drift_exceeds_threshold(
            ledger, {"SPY": 0.5, "QQQ": 0.5}, {"SPY": 100, "QQQ": 100}, 0.05)


# ══════════════════════════════════════════════
# execute_contribution_only / execute_full_rebalance
# ══════════════════════════════════════════════

class TestExecutionPolicies:
    def test_contribution_only_no_cash(self):
        """현금 $0 → 매수 없음."""
        ledger = _make_ledger(cash=0)
        execute_contribution_only(ledger, {"SPY": 1.0}, {"SPY": 100}, 1300)
        assert len(ledger.positions) == 0

    def test_contribution_only_buys(self):
        ledger = _make_ledger(cash=1000)
        execute_contribution_only(ledger, {"SPY": 1.0}, {"SPY": 100}, 1300)
        assert "SPY" in ledger.positions
        assert ledger.positions["SPY"].qty > 0

    def test_contribution_only_zero_price(self):
        """가격 0인 자산 → 건너뜀."""
        ledger = _make_ledger(cash=1000)
        execute_contribution_only(ledger, {"SPY": 1.0}, {"SPY": 0.0}, 1300)
        assert len(ledger.positions) == 0

    def test_full_rebalance_sells_and_buys(self):
        ledger = _make_ledger(cash=10000)
        # SPY, QQQ 각각 매수 후 불균형 상태 만들기
        ledger.buy("SPY", 80, 100, 1300)
        ledger.buy("QQQ", 20, 100, 1300)
        # 현재: SPY 80%, QQQ 20%. 목표: 50/50 → 리밸런싱
        execute_full_rebalance(
            ledger, {"SPY": 0.5, "QQQ": 0.5},
            {"SPY": 100, "QQQ": 100}, 1300)
        # SPY가 줄고 QQQ가 늘어야 함
        assert ledger.positions["QQQ"].qty > 20


# ══════════════════════════════════════════════
# aggregate
# ══════════════════════════════════════════════

class TestAggregate:
    def test_single_account(self):
        ledger = _make_ledger(cash=1000)
        ledger.deposit(1000, 1300)
        ledger.buy("SPY", 10, 100, 1300)
        ledger.record_month()
        result = aggregate({"a": ledger}, 1300.0)
        assert result.n_accounts == 1
        assert result.invested_usd > 0
        assert result.n_months == 1

    def test_empty_ledgers(self):
        result = aggregate({}, 1300.0)
        assert result.n_accounts == 0
        assert result.gross_pv_usd == 0

    def test_annual_tax_history_typed(self):
        """annual_tax_history에 AnnualTaxRecord 전달 가능."""
        ledger = _make_ledger(cash=1000)
        ledger.deposit(1000, 1300)
        ledger.record_month()
        history = [AnnualTaxRecord(year=2024, cgt_krw=100, total_krw=100)]
        result = aggregate({"a": ledger}, 1300.0, annual_tax_history=history)
        assert len(result.annual_tax_history) == 1
        assert result.annual_tax_history[0].year == 2024


# ══════════════════════════════════════════════
# create_ledgers
# ══════════════════════════════════════════════

class TestCreateLedgers:
    def test_creates_from_config(self):
        config = _make_config()
        ledgers = create_ledgers(config)
        assert len(ledgers) == 1
        assert "taxable" in ledgers

    def test_isa_account(self):
        config = BacktestConfig(
            accounts=[make_isa(monthly=500)],
            strategy=StrategyConfig("test", {"SPY": 1.0}),
        )
        ledgers = create_ledgers(config)
        ledger = list(ledgers.values())[0]
        assert ledger.tax_rate == 0.0
        assert ledger.isa_exempt_limit > 0

    def test_multiple_accounts(self):
        config = BacktestConfig(
            accounts=[make_taxable(), make_isa()],
            strategy=StrategyConfig("test", {"SPY": 1.0}),
        )
        ledgers = create_ledgers(config)
        assert len(ledgers) == 2


# ══════════════════════════════════════════════
# Constants
# ══════════════════════════════════════════════

class TestConstants:
    def test_qty_epsilon_is_tiny(self):
        assert QTY_EPSILON < 1e-10

    def test_amount_epsilon_is_tiny(self):
        assert AMOUNT_EPSILON_USD < 1e-6

    def test_dust_pct_is_small(self):
        assert 0 < DUST_PCT < 0.01
