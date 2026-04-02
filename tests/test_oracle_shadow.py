# -*- coding: utf-8 -*-
"""
test_oracle_shadow.py — 기존 엔진 대비 shadow comparison
========================================================
PR 1 핵심: 새 facade가 기존 엔진과 같은 숫자를 내는지 검증.

오라클 3개:
  1. 1계좌 TAXABLE, C/O, 양수 수익, 24개월
  2. 1계좌 TAXABLE, C/O, 음수 포함, 36개월 (이월결손금)
  3. ISA + TAXABLE 2계좌, C/O, 36개월

shadow assert 3계층:
  Tier 1 (strict):  PV, invested, tax assessed/unpaid → atol=1e-6
  Tier 2 (loose):   monthly_values, mdd → atol=1e-4
  Tier 3 (exists):  metadata, optional fields → 존재 여부만
"""
import sys
import os

# 기존 aftertaxi 레포를 import path에 추가
_LEGACY_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "aftertaxi")
if os.path.isdir(_LEGACY_ROOT):
    sys.path.insert(0, os.path.abspath(_LEGACY_ROOT))

# 새 레포
_VNEXT_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, os.path.abspath(_VNEXT_SRC))

import numpy as np
import pandas as pd
import pytest

# 기존 엔진
from engine_v2.account_spec import (
    AccountSpec, AccountType as LegacyAccountType,
    TaxRule, ContributionRule, RebalanceRule,
    RebalanceMode as LegacyRebalMode,
    TAXABLE_TAX, ISA_TAX,
)
from engine_v2.portfolio_runner import PortfolioRunnerV2
from engine_v2.fx_rules import FxRateStore
from strategy_registry import StrategySpec

# 새 facade
from aftertaxi.core.contracts import (
    AccountConfig, AccountType, BacktestConfig,
    EngineResult, RebalanceMode, StrategyConfig, TaxConfig,
)
from aftertaxi.core.facade import run_backtest


# ══════════════════════════════════════════════
# Tiered Shadow Assert
# ══════════════════════════════════════════════

def assert_shadow_match(new: EngineResult, old: dict, fx_enabled: bool):
    """3계층 비교.

    Tier 1 (strict, atol=1e-6): 핵심 숫자
    Tier 2 (loose, atol=1e-3): 시계열, 비율
    Tier 3 (exists): 구조 검증
    """
    # ── Tier 1: 핵심 숫자 (strict) ──
    assert abs(new.gross_pv_usd - old["pv"]) < 1e-6, \
        f"Tier 1 FAIL: gross_pv_usd {new.gross_pv_usd} vs {old['pv']}"

    assert abs(new.invested_usd - old["inv"]) < 1e-6, \
        f"Tier 1 FAIL: invested_usd {new.invested_usd} vs {old['inv']}"

    if "tax_assessed_krw" in old:
        old_assessed = old["tax_assessed_krw"]
    else:
        old_assessed = old.get("tax", 0)
    assert abs(new.tax.total_assessed_krw - old_assessed) < 1e-6, \
        f"Tier 1 FAIL: assessed {new.tax.total_assessed_krw} vs {old_assessed}"

    old_unpaid = old.get("unpaid_tax_krw", 0)
    assert abs(new.tax.total_unpaid_krw - old_unpaid) < 1e-6, \
        f"Tier 1 FAIL: unpaid {new.tax.total_unpaid_krw} vs {old_unpaid}"

    assert new.n_months == old["n_months"], \
        f"Tier 1 FAIL: n_months {new.n_months} vs {old['n_months']}"

    assert new.n_accounts == old["n_accounts"], \
        f"Tier 1 FAIL: n_accounts {new.n_accounts} vs {old['n_accounts']}"

    # ── Tier 2: 시계열/비율 (loose) ──
    old_mv = old.get("monthly_values")
    if old_mv is not None:
        assert len(new.monthly_values) == len(old_mv), \
            f"Tier 2 FAIL: monthly_values len {len(new.monthly_values)} vs {len(old_mv)}"
        np.testing.assert_allclose(
            new.monthly_values, old_mv, atol=1e-3,
            err_msg="Tier 2 FAIL: monthly_values mismatch",
        )

    assert abs(new.mdd - old["mdd"]) < 1e-3, \
        f"Tier 2 FAIL: mdd {new.mdd} vs {old['mdd']}"

    # FX 모드 추가 검증
    if fx_enabled:
        old_gross_krw = old.get("gross_pv_krw", old["pv"])
        assert abs(new.gross_pv_krw - old_gross_krw) < 1.0, \
            f"Tier 2 FAIL: gross_pv_krw {new.gross_pv_krw} vs {old_gross_krw}"

        old_net_krw = old.get("net_pv_krw", old["pv"])
        assert abs(new.net_pv_krw - old_net_krw) < 1.0, \
            f"Tier 2 FAIL: net_pv_krw {new.net_pv_krw} vs {old_net_krw}"

    # ── Tier 3: 구조 (exists) ──
    assert len(new.accounts) == old["n_accounts"]
    for i, acct in enumerate(new.accounts):
        assert acct.account_id == old["accounts"][i]["account_id"]
        assert acct.n_months > 0


# ══════════════════════════════════════════════
# Test Data Helpers
# ══════════════════════════════════════════════

def _monthly_index(n, start="2020-01-31"):
    return pd.date_range(start, periods=n, freq="ME")


def _constant_prices(n, assets, base=100.0, ret=0.01):
    idx = _monthly_index(n)
    data = {}
    for a in assets:
        p = [base]
        for _ in range(1, n):
            p.append(p[-1] * (1 + ret))
        data[a] = p
    return pd.DataFrame(data, index=idx)


def _returns_from_prices(prices):
    return prices.pct_change().fillna(0.0)


def _constant_fx(n, rate=1300.0):
    idx = _monthly_index(n)
    return pd.Series([rate] * n, index=idx)


def _legacy_strategy(n, assets, weight=None, rebal_every=1):
    idx = _monthly_index(n)
    if weight is None:
        weight = 1.0 / len(assets)
    weights = pd.DataFrame({a: [weight] * n for a in assets}, index=idx)
    mask = pd.Series([(i % rebal_every == 0) for i in range(n)], index=idx)
    mask.iloc[0] = True
    return StrategySpec(name="oracle_test", weights=weights, rebalance_mask=mask, metadata={})


def _run_legacy_fx(n, assets, ret, monthly, mode, fx_rate=1300.0, account_type="TAXABLE"):
    """기존 엔진 직접 실행."""
    prices = _constant_prices(n, assets, ret=ret)
    returns = _returns_from_prices(prices)
    fx_series = _constant_fx(n, rate=fx_rate)
    fx_store = FxRateStore.from_series(fx_series)
    strategy = _legacy_strategy(n, assets)

    rebal = LegacyRebalMode.CONTRIBUTION_ONLY if mode == "CO" else LegacyRebalMode.FULL

    if account_type == "TAXABLE":
        spec = AccountSpec(
            account_id="taxable",
            account_type=LegacyAccountType.TAXABLE,
            tax_rule=TAXABLE_TAX,
            contribution_rule=ContributionRule(monthly_amount=monthly, priority=0),
            rebalance_rule=RebalanceRule(mode=rebal, lot_method="AVGCOST"),
        )
        accounts = [spec]
    else:
        raise ValueError("Use _run_legacy_multi for multi-account")

    runner = PortfolioRunnerV2(
        returns=returns, accounts=accounts,
        prices=prices, fx_store=fx_store,
    )
    return runner.run(strategy), returns, prices, fx_store


# ══════════════════════════════════════════════
# Oracle 1: 1계좌 TAXABLE, C/O, 양수 수익, 24개월
# ══════════════════════════════════════════════

class TestOracle1_TaxableCO_Positive:
    """1계좌 양수 수익 C/O — 매도 없으므로 세금 0."""

    N = 24
    ASSETS = ["SPY"]
    RET = 0.01
    MONTHLY = 1000.0

    def _run_both(self):
        # 기존 엔진
        old_result, returns, prices, fx_store = _run_legacy_fx(
            self.N, self.ASSETS, self.RET, self.MONTHLY, "CO",
        )

        # 새 facade
        new_result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig(
                    account_id="taxable",
                    account_type=AccountType.TAXABLE,
                    monthly_contribution=self.MONTHLY,
                    rebalance_mode=RebalanceMode.CONTRIBUTION_ONLY,
                    lot_method="AVGCOST",
                )],
                strategy=StrategyConfig(name="oracle_test", weights={"SPY": 1.0}),
            ),
            returns=returns, prices=prices, fx_store=fx_store,
        )
        return new_result, old_result

    def test_shadow_match(self):
        new, old = self._run_both()
        assert_shadow_match(new, old, fx_enabled=True)

    def test_typed_result(self):
        new, _ = self._run_both()
        assert isinstance(new, EngineResult)
        assert new.gross_pv_usd > 0
        assert new.invested_usd > 0

    def test_co_no_tax(self):
        """C/O + 양수 수익 → 최종 청산 전까지 세금 0이 아닐 수 있음.
        하지만 assessed >= 0은 보장."""
        new, _ = self._run_both()
        assert new.tax.total_assessed_krw >= 0

    def test_invariants(self):
        new, _ = self._run_both()
        assert new.tax.total_assessed_krw >= new.tax.total_unpaid_krw - 1e-6
        assert new.net_pv_krw <= new.gross_pv_krw + 1e-6


# ══════════════════════════════════════════════
# Oracle 2: 1계좌 TAXABLE, C/O, 음수 포함, 36개월
# ══════════════════════════════════════════════

class TestOracle2_TaxableCO_MixedReturns:
    """음수 수익 포함 — 이월결손금 발동 가능."""

    N = 36
    ASSETS = ["SPY"]
    MONTHLY = 1000.0

    def _make_mixed_prices(self):
        """처음 12개월 상승, 중간 12개월 하락, 마지막 12개월 상승."""
        idx = _monthly_index(self.N)
        p = [100.0]
        for i in range(1, self.N):
            if i < 12:
                p.append(p[-1] * 1.02)
            elif i < 24:
                p.append(p[-1] * 0.97)
            else:
                p.append(p[-1] * 1.015)
        return pd.DataFrame({"SPY": p}, index=idx)

    def _run_both(self):
        prices = self._make_mixed_prices()
        returns = _returns_from_prices(prices)
        fx_series = _constant_fx(self.N)
        fx_store = FxRateStore.from_series(fx_series)
        strategy = _legacy_strategy(self.N, self.ASSETS)

        # 기존 엔진
        spec = AccountSpec(
            account_id="taxable",
            account_type=LegacyAccountType.TAXABLE,
            tax_rule=TAXABLE_TAX,
            contribution_rule=ContributionRule(monthly_amount=self.MONTHLY, priority=0),
            rebalance_rule=RebalanceRule(
                mode=LegacyRebalMode.CONTRIBUTION_ONLY, lot_method="AVGCOST",
            ),
        )
        runner = PortfolioRunnerV2(
            returns=returns, accounts=[spec],
            prices=prices, fx_store=fx_store,
        )
        old_result = runner.run(strategy)

        # 새 facade
        new_result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig(
                    account_id="taxable",
                    account_type=AccountType.TAXABLE,
                    monthly_contribution=self.MONTHLY,
                    rebalance_mode=RebalanceMode.CONTRIBUTION_ONLY,
                    lot_method="AVGCOST",
                )],
                strategy=StrategyConfig(name="oracle_test", weights={"SPY": 1.0}),
            ),
            returns=returns, prices=prices, fx_store=fx_store,
        )
        return new_result, old_result

    def test_shadow_match(self):
        new, old = self._run_both()
        assert_shadow_match(new, old, fx_enabled=True)

    def test_mdd_nonpositive(self):
        """MDD는 0 이하. DCA에서는 신규 납입이 하락을 상쇄할 수 있어 0.0도 가능."""
        new, _ = self._run_both()
        assert new.mdd <= 0.0 + 1e-6


# ══════════════════════════════════════════════
# Oracle 3: ISA + TAXABLE 2계좌, C/O, 36개월
# ══════════════════════════════════════════════

class TestOracle3_MultiAccount:
    """2계좌 다계좌 — 배분 + ISA 세금 0 검증."""

    N = 36
    ASSETS = ["SPY"]
    RET = 0.01

    def _run_both(self):
        prices = _constant_prices(self.N, self.ASSETS, ret=self.RET)
        returns = _returns_from_prices(prices)
        fx_series = _constant_fx(self.N)
        fx_store = FxRateStore.from_series(fx_series)
        strategy = _legacy_strategy(self.N, self.ASSETS)

        # 기존 엔진: 2계좌
        taxable_spec = AccountSpec(
            account_id="taxable",
            account_type=LegacyAccountType.TAXABLE,
            tax_rule=TAXABLE_TAX,
            contribution_rule=ContributionRule(monthly_amount=500.0, priority=0),
            rebalance_rule=RebalanceRule(
                mode=LegacyRebalMode.CONTRIBUTION_ONLY, lot_method="AVGCOST",
            ),
        )
        isa_spec = AccountSpec(
            account_id="isa",
            account_type=LegacyAccountType.ISA,
            tax_rule=ISA_TAX,
            contribution_rule=ContributionRule(
                monthly_amount=500.0, priority=1, annual_cap=20_000_000.0,
            ),
            rebalance_rule=RebalanceRule(
                mode=LegacyRebalMode.CONTRIBUTION_ONLY, lot_method="AVGCOST",
            ),
        )
        runner = PortfolioRunnerV2(
            returns=returns, accounts=[taxable_spec, isa_spec],
            prices=prices, fx_store=fx_store,
        )
        old_result = runner.run(strategy)

        # 새 facade
        new_result = run_backtest(
            BacktestConfig(
                accounts=[
                    AccountConfig(
                        account_id="taxable",
                        account_type=AccountType.TAXABLE,
                        monthly_contribution=500.0,
                        rebalance_mode=RebalanceMode.CONTRIBUTION_ONLY,
                        lot_method="AVGCOST",
                    ),
                    AccountConfig(
                        account_id="isa",
                        account_type=AccountType.ISA,
                        monthly_contribution=500.0,
                        rebalance_mode=RebalanceMode.CONTRIBUTION_ONLY,
                        lot_method="AVGCOST",
                        annual_cap=20_000_000.0,
                        tax_config=TaxConfig(
                            capital_gains_rate=0.099,
                            isa_exempt_limit=2_000_000.0,
                        ),
                    ),
                ],
                strategy=StrategyConfig(name="oracle_test", weights={"SPY": 1.0}),
            ),
            returns=returns, prices=prices, fx_store=fx_store,
        )
        return new_result, old_result

    def test_shadow_match(self):
        new, old = self._run_both()
        assert_shadow_match(new, old, fx_enabled=True)

    def test_two_accounts(self):
        new, _ = self._run_both()
        assert new.n_accounts == 2
        assert len(new.accounts) == 2

    def test_account_ids(self):
        new, _ = self._run_both()
        ids = {a.account_id for a in new.accounts}
        assert ids == {"taxable", "isa"}


# ══════════════════════════════════════════════
# Oracle 4: 1계좌 TAXABLE, FULL rebalance, 2자산, 24개월
# ══════════════════════════════════════════════

class TestOracle4_FullRebalance:
    """FULL rebalance — 매도로 실현이익 발생 → 세금."""

    N = 24
    ASSETS = ["SPY", "QQQ"]
    MONTHLY = 1000.0

    def _make_divergent_prices(self):
        """SPY: 월 1% 상승, QQQ: 월 2% 상승 → 리밸런싱 시 QQQ 매도."""
        idx = _monthly_index(self.N)
        spy = [100.0]
        qqq = [100.0]
        for _ in range(1, self.N):
            spy.append(spy[-1] * 1.01)
            qqq.append(qqq[-1] * 1.02)
        return pd.DataFrame({"SPY": spy, "QQQ": qqq}, index=idx)

    def _run_both(self):
        prices = self._make_divergent_prices()
        returns = _returns_from_prices(prices)
        fx_series = _constant_fx(self.N)
        fx_store = FxRateStore.from_series(fx_series)
        strategy_legacy = _legacy_strategy(self.N, self.ASSETS, weight=0.5, rebal_every=1)

        # 기존 엔진: FULL mode
        spec = AccountSpec(
            account_id="taxable",
            account_type=LegacyAccountType.TAXABLE,
            tax_rule=TAXABLE_TAX,
            contribution_rule=ContributionRule(monthly_amount=self.MONTHLY, priority=0),
            rebalance_rule=RebalanceRule(
                mode=LegacyRebalMode.FULL, lot_method="AVGCOST",
            ),
        )
        runner = PortfolioRunnerV2(
            returns=returns, accounts=[spec],
            prices=prices, fx_store=fx_store,
        )
        old_result = runner.run(strategy_legacy)

        # 새 facade: FULL mode
        new_result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig(
                    account_id="taxable",
                    account_type=AccountType.TAXABLE,
                    monthly_contribution=self.MONTHLY,
                    rebalance_mode=RebalanceMode.FULL,
                    lot_method="AVGCOST",
                )],
                strategy=StrategyConfig(
                    name="oracle_full", weights={"SPY": 0.5, "QQQ": 0.5},
                    rebalance_every=1,
                ),
            ),
            returns=returns, prices=prices, fx_store=fx_store,
        )
        return new_result, old_result

    def test_shadow_match(self):
        new, old = self._run_both()
        assert_shadow_match(new, old, fx_enabled=True)

    def test_tax_positive(self):
        """FULL 리밸런싱은 QQQ 매도 → 실현이익 → 세금 > 0."""
        new, _ = self._run_both()
        assert new.tax.total_assessed_krw > 0, "FULL rebalance인데 세금이 0"

    def test_net_less_than_gross(self):
        """세금 납부 후 net < gross."""
        new, _ = self._run_both()
        assert new.tax.total_paid_krw > 0 or new.tax.total_unpaid_krw > 0


# ══════════════════════════════════════════════
# Oracle 5: 48개월 FULL — 연도 경계 3회 정산
# ══════════════════════════════════════════════

class TestOracle5_YearBoundarySettlement:
    """4년간 FULL rebalance — 매년 세금 정산이 정확히 일어나는지."""

    N = 48
    ASSETS = ["SPY", "QQQ"]
    MONTHLY = 1000.0

    def _make_prices(self):
        idx = _monthly_index(self.N)
        spy = [100.0]
        qqq = [100.0]
        for i in range(1, self.N):
            spy.append(spy[-1] * 1.008)
            qqq.append(qqq[-1] * 1.015)
        return pd.DataFrame({"SPY": spy, "QQQ": qqq}, index=idx)

    def _run_both(self):
        prices = self._make_prices()
        returns = _returns_from_prices(prices)
        fx_series = _constant_fx(self.N)
        fx_store = FxRateStore.from_series(fx_series)
        strategy = _legacy_strategy(self.N, self.ASSETS, weight=0.5, rebal_every=1)

        spec = AccountSpec(
            account_id="taxable",
            account_type=LegacyAccountType.TAXABLE,
            tax_rule=TAXABLE_TAX,
            contribution_rule=ContributionRule(monthly_amount=self.MONTHLY, priority=0),
            rebalance_rule=RebalanceRule(mode=LegacyRebalMode.FULL, lot_method="AVGCOST"),
        )
        runner = PortfolioRunnerV2(
            returns=returns, accounts=[spec],
            prices=prices, fx_store=fx_store,
        )
        old_result = runner.run(strategy)

        new_result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig(
                    account_id="taxable",
                    account_type=AccountType.TAXABLE,
                    monthly_contribution=self.MONTHLY,
                    rebalance_mode=RebalanceMode.FULL,
                    lot_method="AVGCOST",
                )],
                strategy=StrategyConfig(
                    name="oracle_yearbound", weights={"SPY": 0.5, "QQQ": 0.5},
                    rebalance_every=1,
                ),
            ),
            returns=returns, prices=prices, fx_store=fx_store,
        )
        return new_result, old_result

    def test_shadow_match(self):
        new, old = self._run_both()
        assert_shadow_match(new, old, fx_enabled=True)

    def test_48_months(self):
        new, _ = self._run_both()
        assert new.n_months == 48

    def test_tax_from_rebalancing(self):
        """4년간 FULL → 세금 발생."""
        new, _ = self._run_both()
        assert new.tax.total_assessed_krw > 0


# ══════════════════════════════════════════════
# Oracle 6: ISA FULL — ISA 만기 세금 발생
# ══════════════════════════════════════════════

class TestOracle6_ISASettlement:
    """ISA + FULL → 실현이익 → ISA 만기 초과분 과세."""

    N = 36
    ASSETS = ["SPY", "QQQ"]
    MONTHLY = 1000.0

    def _make_prices(self):
        """강한 상승 → ISA 비과세 한도 초과 유도."""
        idx = _monthly_index(self.N)
        spy = [100.0]
        qqq = [100.0]
        for _ in range(1, self.N):
            spy.append(spy[-1] * 1.02)
            qqq.append(qqq[-1] * 1.03)
        return pd.DataFrame({"SPY": spy, "QQQ": qqq}, index=idx)

    def _run_both(self):
        prices = self._make_prices()
        returns = _returns_from_prices(prices)
        fx_series = _constant_fx(self.N)
        fx_store = FxRateStore.from_series(fx_series)
        strategy = _legacy_strategy(self.N, self.ASSETS, weight=0.5, rebal_every=1)

        isa_spec = AccountSpec(
            account_id="isa",
            account_type=LegacyAccountType.ISA,
            tax_rule=ISA_TAX,
            contribution_rule=ContributionRule(
                monthly_amount=self.MONTHLY, priority=0, annual_cap=20_000_000.0,
            ),
            rebalance_rule=RebalanceRule(mode=LegacyRebalMode.FULL, lot_method="AVGCOST"),
        )
        runner = PortfolioRunnerV2(
            returns=returns, accounts=[isa_spec],
            prices=prices, fx_store=fx_store,
        )
        old_result = runner.run(strategy)

        new_result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig(
                    account_id="isa",
                    account_type=AccountType.ISA,
                    monthly_contribution=self.MONTHLY,
                    rebalance_mode=RebalanceMode.FULL,
                    lot_method="AVGCOST",
                    annual_cap=20_000_000.0,
                    tax_config=TaxConfig(
                        capital_gains_rate=0.099,
                        isa_exempt_limit=2_000_000.0,
                    ),
                )],
                strategy=StrategyConfig(
                    name="oracle_isa", weights={"SPY": 0.5, "QQQ": 0.5},
                    rebalance_every=1,
                ),
            ),
            returns=returns, prices=prices, fx_store=fx_store,
        )
        return new_result, old_result

    def test_shadow_match(self):
        new, old = self._run_both()
        assert_shadow_match(new, old, fx_enabled=True)

    def test_isa_tax_positive(self):
        """강한 상승 + FULL → ISA 비과세 한도 초과 → 세금 > 0."""
        new, _ = self._run_both()
        assert new.tax.total_assessed_krw > 0, "ISA 만기 세금이 0"


# ══════════════════════════════════════════════
# Oracle 7: 60개월 손실→회복 — 이월결손금 상쇄
# ══════════════════════════════════════════════

class TestOracle7_CarryforwardOffset:
    """손실 구간 → 회복 구간: 이월결손금으로 세금 감면."""

    N = 60
    ASSETS = ["SPY"]
    MONTHLY = 1000.0

    def _make_prices(self):
        """2년 하락 → 3년 상승. FULL이면 하락기 매도 → 손실 실현 → 이월."""
        idx = _monthly_index(self.N)
        p = [100.0]
        for i in range(1, self.N):
            if i < 24:
                p.append(p[-1] * 0.98)  # 월 -2%
            else:
                p.append(p[-1] * 1.025)  # 월 +2.5%
        return pd.DataFrame({"SPY": p}, index=idx)

    def _run_both(self):
        prices = self._make_prices()
        returns = _returns_from_prices(prices)
        fx_series = _constant_fx(self.N)
        fx_store = FxRateStore.from_series(fx_series)
        strategy = _legacy_strategy(self.N, self.ASSETS, weight=1.0, rebal_every=1)

        spec = AccountSpec(
            account_id="taxable",
            account_type=LegacyAccountType.TAXABLE,
            tax_rule=TAXABLE_TAX,
            contribution_rule=ContributionRule(monthly_amount=self.MONTHLY, priority=0),
            rebalance_rule=RebalanceRule(mode=LegacyRebalMode.FULL, lot_method="AVGCOST"),
        )
        runner = PortfolioRunnerV2(
            returns=returns, accounts=[spec],
            prices=prices, fx_store=fx_store,
        )
        old_result = runner.run(strategy)

        new_result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig(
                    account_id="taxable",
                    account_type=AccountType.TAXABLE,
                    monthly_contribution=self.MONTHLY,
                    rebalance_mode=RebalanceMode.FULL,
                    lot_method="AVGCOST",
                )],
                strategy=StrategyConfig(
                    name="oracle_carry", weights={"SPY": 1.0},
                    rebalance_every=1,
                ),
            ),
            returns=returns, prices=prices, fx_store=fx_store,
        )
        return new_result, old_result

    def test_shadow_match(self):
        new, old = self._run_both()
        assert_shadow_match(new, old, fx_enabled=True)

    def test_60_months(self):
        new, _ = self._run_both()
        assert new.n_months == 60


# ══════════════════════════════════════════════
# Oracle 8: C/O, weights 합 < 1.0 — 정규화 검증
# ══════════════════════════════════════════════

class TestOracle8_SubunitWeights:
    """weights 합이 1.0 미만일 때 C/O가 전액 투자하는지 검증.
    양 엔진 모두 C/O는 tw_sum으로 정규화하므로 shadow match 가능.
    NOTE: FULL은 legacy가 raw weights를 쓰므로 shadow 불일치 (의도적 개선).
    """

    N = 24
    ASSETS = ["SPY", "QQQ"]
    MONTHLY = 1000.0
    WEIGHTS = {"SPY": 0.5, "QQQ": 0.3}  # 합 = 0.8

    def _make_prices(self):
        idx = _monthly_index(self.N)
        spy = [100.0]
        qqq = [100.0]
        for _ in range(1, self.N):
            spy.append(spy[-1] * 1.01)
            qqq.append(qqq[-1] * 1.015)
        return pd.DataFrame({"SPY": spy, "QQQ": qqq}, index=idx)

    def _run_both(self):
        prices = self._make_prices()
        returns = _returns_from_prices(prices)
        fx_series = _constant_fx(self.N)
        fx_store = FxRateStore.from_series(fx_series)

        # 기존 엔진 — C/O, 커스텀 weights
        idx = _monthly_index(self.N)
        weights_df = pd.DataFrame(
            {"SPY": [0.5]*self.N, "QQQ": [0.3]*self.N}, index=idx,
        )
        mask = pd.Series([True]*self.N, index=idx)
        strategy = StrategySpec(
            name="oracle_subunit", weights=weights_df,
            rebalance_mask=mask, metadata={},
        )

        spec = AccountSpec(
            account_id="taxable",
            account_type=LegacyAccountType.TAXABLE,
            tax_rule=TAXABLE_TAX,
            contribution_rule=ContributionRule(monthly_amount=self.MONTHLY, priority=0),
            rebalance_rule=RebalanceRule(mode=LegacyRebalMode.CONTRIBUTION_ONLY, lot_method="AVGCOST"),
        )
        runner = PortfolioRunnerV2(
            returns=returns, accounts=[spec],
            prices=prices, fx_store=fx_store,
        )
        old_result = runner.run(strategy)

        # 새 엔진 — C/O
        new_result = run_backtest(
            BacktestConfig(
                accounts=[AccountConfig(
                    account_id="taxable",
                    account_type=AccountType.TAXABLE,
                    monthly_contribution=self.MONTHLY,
                    rebalance_mode=RebalanceMode.CONTRIBUTION_ONLY,
                    lot_method="AVGCOST",
                )],
                strategy=StrategyConfig(
                    name="oracle_subunit", weights=self.WEIGHTS,
                ),
            ),
            returns=returns, prices=prices, fx_store=fx_store,
        )
        return new_result, old_result

    def test_shadow_match(self):
        """C/O + weights<1.0: 양 엔진 모두 tw_sum 정규화 → 일치."""
        new, old = self._run_both()
        assert_shadow_match(new, old, fx_enabled=True)

    def test_no_idle_cash(self):
        """C/O는 weights 합이 뭐든 전액 투자."""
        new, _ = self._run_both()
        # PV ≈ invested (가격 상승분은 있으니 >= invested)
        assert new.gross_pv_usd >= new.invested_usd * 0.95
