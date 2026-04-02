# -*- coding: utf-8 -*-
"""
test_contracts.py — typed contract 자체 검증
=============================================
기존 엔진 의존 없이 contracts.py만 테스트.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pytest

from aftertaxi.core.contracts import (
    AccountConfig, AccountSummary, AccountType, BacktestConfig,
    EngineResult, RebalanceMode, StrategyConfig, TaxConfig, TaxSummary,
)


class TestTaxSummaryInvariants:

    def test_valid_summary(self):
        ts = TaxSummary(total_assessed_krw=100_000, total_unpaid_krw=30_000, total_paid_krw=70_000)
        assert ts.total_assessed_krw == 100_000

    def test_invariant_violation_raises(self):
        with pytest.raises(ValueError, match="불변식"):
            TaxSummary(total_assessed_krw=100_000, total_unpaid_krw=30_000, total_paid_krw=50_000)

    def test_zero_tax(self):
        ts = TaxSummary(total_assessed_krw=0, total_unpaid_krw=0, total_paid_krw=0)
        assert ts.total_paid_krw == 0


class TestEngineResultInvariants:

    def _make_result(self, pv=1000.0, inv=500.0, fx=1300.0, assessed=100_000.0, unpaid=0.0):
        gross_krw = pv * fx
        net_krw = gross_krw - unpaid
        return EngineResult(
            gross_pv_usd=pv,
            invested_usd=inv,
            gross_pv_krw=gross_krw,
            net_pv_krw=net_krw,
            reporting_fx_rate=fx,
            mdd=-0.1,
            n_months=24,
            n_accounts=1,
            tax=TaxSummary(
                total_assessed_krw=assessed,
                total_unpaid_krw=unpaid,
                total_paid_krw=assessed - unpaid,
            ),
            accounts=[AccountSummary(
                account_id="test",
                account_type="TAXABLE",
                gross_pv_usd=pv,
                invested_usd=inv,
                tax_assessed_krw=assessed,
                tax_unpaid_krw=unpaid,
                mdd=-0.1,
                n_months=24,
            )],
            monthly_values=np.ones(24) * pv,
        )

    def test_valid_result(self):
        r = self._make_result()
        assert r.mult_pre_tax == 2.0

    def test_mult_after_tax(self):
        r = self._make_result(pv=1000, inv=500, fx=1300, assessed=130_000, unpaid=130_000)
        # net = 1000*1300 - 130_000 = 1_170_000
        # mult_after_tax = (1_170_000 / 1300) / 500 = 1.8
        assert abs(r.mult_after_tax - 1.8) < 1e-6

    def test_tax_drag(self):
        r = self._make_result(pv=1000, inv=500, fx=1300, assessed=130_000, unpaid=130_000)
        # gross_krw = 1_300_000, net = 1_170_000
        # drag = 1 - 1_170_000 / 1_300_000 = 0.1
        assert abs(r.tax_drag - 0.1) < 1e-6

    def test_gross_krw_invariant_violation(self):
        with pytest.raises(ValueError, match="gross_pv_krw"):
            EngineResult(
                gross_pv_usd=1000,
                invested_usd=500,
                gross_pv_krw=999_999,  # should be 1_300_000
                net_pv_krw=999_999,
                reporting_fx_rate=1300,
                mdd=-0.1, n_months=24, n_accounts=1,
                tax=TaxSummary(0, 0, 0),
                accounts=[], monthly_values=np.array([]),
            )

    def test_net_krw_invariant_violation(self):
        with pytest.raises(ValueError, match="net_pv_krw"):
            EngineResult(
                gross_pv_usd=1000,
                invested_usd=500,
                gross_pv_krw=1_300_000,
                net_pv_krw=1_200_000,  # should be 1_300_000 (unpaid=0)
                reporting_fx_rate=1300,
                mdd=-0.1, n_months=24, n_accounts=1,
                tax=TaxSummary(0, 0, 0),
                accounts=[], monthly_values=np.array([]),
            )


class TestAccountConfig:

    def test_defaults(self):
        ac = AccountConfig(
            account_id="test",
            account_type=AccountType.TAXABLE,
            monthly_contribution=1000.0,
        )
        assert ac.rebalance_mode == RebalanceMode.CONTRIBUTION_ONLY
        assert ac.lot_method == "AVGCOST"

    def test_isa(self):
        ac = AccountConfig(
            account_id="isa",
            account_type=AccountType.ISA,
            monthly_contribution=500.0,
            annual_cap=20_000_000.0,
        )
        assert ac.annual_cap == 20_000_000.0


class TestBacktestConfig:

    def test_basic(self):
        config = BacktestConfig(
            accounts=[AccountConfig(
                account_id="t",
                account_type=AccountType.TAXABLE,
                monthly_contribution=1000.0,
            )],
            strategy=StrategyConfig(name="bh", weights={"SPY": 1.0}),
        )
        assert config.n_months is None
        assert config.start_index == 0
