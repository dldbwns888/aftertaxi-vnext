# -*- coding: utf-8 -*-
"""
test_compile.py — 입력 컴파일러 테스트
"""

import numpy as np
import pandas as pd
import pytest

from aftertaxi.core.contracts import (
    AccountConfig, AccountType, BacktestConfig, RebalanceMode, StrategyConfig,
)
from aftertaxi.strategies.compile import (
    compile_strategy, compile_account, compile_accounts, compile_backtest,
)


# ══════════════════════════════════════════════
# compile_strategy
# ══════════════════════════════════════════════

class TestCompileStrategy:

    def test_registry_type(self):
        config = compile_strategy({"type": "q60s40"})
        assert isinstance(config, StrategyConfig)
        assert config.weights == {"QQQ": 0.6, "SSO": 0.4}

    def test_registry_with_params(self):
        config = compile_strategy({
            "type": "6040",
            "params": {"stock": "VOO", "bond": "SGOV"},
        })
        assert config.weights == {"VOO": 0.6, "SGOV": 0.4}

    def test_direct_weights(self):
        config = compile_strategy({
            "weights": {"SPY": 0.7, "QQQ": 0.3},
            "rebalance_every": 12,
        })
        assert config.weights == {"SPY": 0.7, "QQQ": 0.3}
        assert config.rebalance_every == 12

    def test_unknown_type_raises(self):
        with pytest.raises(KeyError, match="Unknown strategy"):
            compile_strategy({"type": "nonexistent"})

    def test_no_type_no_weights_raises(self):
        with pytest.raises(ValueError, match="type.*weights"):
            compile_strategy({"name": "oops"})


# ══════════════════════════════════════════════
# compile_account
# ══════════════════════════════════════════════

class TestCompileAccount:

    def test_taxable_defaults(self):
        acc = compile_account({"type": "TAXABLE"})
        assert acc.account_type == AccountType.TAXABLE
        assert acc.tax_config.capital_gains_rate == 0.22
        assert acc.priority == 1

    def test_isa_defaults(self):
        acc = compile_account({"type": "ISA"})
        assert acc.account_type == AccountType.ISA
        assert acc.annual_cap == 20_000_000.0
        assert acc.priority == 0

    def test_override_monthly(self):
        acc = compile_account({"type": "TAXABLE", "monthly_contribution": 500})
        assert acc.monthly_contribution == 500.0

    def test_override_priority(self):
        acc = compile_account({"type": "ISA", "priority": 5})
        assert acc.priority == 5

    def test_allowed_assets(self):
        acc = compile_account({"type": "TAXABLE", "allowed_assets": ["SPY", "QQQ"]})
        assert acc.allowed_assets == {"SPY", "QQQ"}

    def test_rebalance_mode_string(self):
        acc = compile_account({"type": "TAXABLE", "rebalance_mode": "FULL"})
        assert acc.rebalance_mode == RebalanceMode.FULL

    def test_pension_raises(self):
        with pytest.raises(NotImplementedError, match="PENSION"):
            compile_account({"type": "PENSION"})

    def test_budget_mode_raises(self):
        """BUDGET은 facade에서 차단되지만, compile에서도 string→enum은 허용.
        실제 차단은 facade._validate_config()."""
        # BUDGET은 enum에 있으니 compile은 통과
        acc = compile_account({"type": "TAXABLE", "rebalance_mode": "BUDGET"})
        assert acc.rebalance_mode == RebalanceMode.BUDGET

    def test_auto_account_id(self):
        acc = compile_account({"type": "TAXABLE"}, index=3)
        assert acc.account_id == "taxable_3"


# ══════════════════════════════════════════════
# compile_backtest (full payload)
# ══════════════════════════════════════════════

class TestCompileBacktest:

    def test_minimal(self):
        config = compile_backtest({
            "strategy": {"type": "spy_bnh"},
        })
        assert isinstance(config, BacktestConfig)
        assert config.strategy.weights == {"SPY": 1.0}
        assert len(config.accounts) == 1  # 기본 TAXABLE

    def test_full_payload(self):
        config = compile_backtest({
            "strategy": {"type": "q60s40"},
            "accounts": [
                {"type": "ISA", "monthly_contribution": 300, "priority": 0},
                {"type": "TAXABLE", "monthly_contribution": 700, "priority": 1},
            ],
            "n_months": 240,
            "enable_health_insurance": True,
            "dividend_yields": {"QQQ": 0.005, "SSO": 0.01},
        })
        assert len(config.accounts) == 2
        assert config.n_months == 240
        assert config.enable_health_insurance is True
        assert config.dividend_schedule is not None
        assert config.strategy.name == "Q60S40_CO"

    def test_no_strategy_raises(self):
        with pytest.raises(ValueError, match="strategy"):
            compile_backtest({"accounts": [{"type": "TAXABLE"}]})

    def test_isa_before_taxable(self):
        """ISA priority < TAXABLE priority."""
        config = compile_backtest({
            "strategy": {"type": "spy_bnh"},
            "accounts": [
                {"type": "TAXABLE"},
                {"type": "ISA"},
            ],
        })
        isa = [a for a in config.accounts if a.account_type == AccountType.ISA][0]
        tax = [a for a in config.accounts if a.account_type == AccountType.TAXABLE][0]
        assert isa.priority < tax.priority


class TestEndToEnd:

    def test_compile_to_engine(self):
        """compile → run_backtest → EngineResult."""
        from aftertaxi.core.facade import run_backtest

        config = compile_backtest({
            "strategy": {"type": "spy_bnh"},
            "accounts": [
                {"type": "ISA", "monthly_contribution": 500},
                {"type": "TAXABLE", "monthly_contribution": 500},
            ],
            "n_months": 24,
        })

        idx = pd.date_range("2024-01-31", periods=24, freq="ME")
        prices = pd.DataFrame({"SPY": [100 + i for i in range(24)]}, index=idx)
        fx = pd.Series(1300.0, index=idx)
        returns = prices.pct_change().fillna(0.0)

        result = run_backtest(config, returns=returns, prices=prices, fx_rates=fx)
        assert result.gross_pv_usd > 0
        assert result.n_accounts == 2
        assert result.n_months == 24
