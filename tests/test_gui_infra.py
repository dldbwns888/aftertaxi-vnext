# -*- coding: utf-8 -*-
"""
test_gui_infra.py — GUI 인프라 테스트
=====================================
metadata + draft models + compile 파이프라인.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import json
import pytest

from aftertaxi.strategies.metadata import (
    get_metadata, list_metadata, list_by_category, categories,
    StrategyMetadata, ParamSchema,
)
from aftertaxi.apps.gui.draft_models import (
    StrategyDraft, AccountDraft, BacktestDraft,
)


# ══════════════════════════════════════════════
# Metadata
# ══════════════════════════════════════════════

class TestMetadata:

    def test_all_strategies_have_metadata(self):
        from aftertaxi.strategies import registry
        for key in registry.available():
            meta = get_metadata(key)
            assert meta.key == key
            assert meta.label  # 빈 문자열 아님

    def test_q60s40_metadata(self):
        meta = get_metadata("q60s40")
        assert meta.label == "Q60S40"
        assert meta.category == "static_allocation"
        assert "core" in meta.tags
        assert meta.default_weights == {"QQQ": 0.6, "SSO": 0.4}

    def test_6040_has_params(self):
        meta = get_metadata("6040")
        param_names = [p.name for p in meta.params]
        assert "stock" in param_names
        assert "bond" in param_names

    def test_categories(self):
        cats = categories()
        assert "static_allocation" in cats
        assert "benchmark" in cats

    def test_list_by_category(self):
        benchmarks = list_by_category("benchmark")
        assert len(benchmarks) >= 2
        assert all(m.category == "benchmark" for m in benchmarks)

    def test_unknown_raises(self):
        with pytest.raises(KeyError, match="Unknown"):
            get_metadata("nonexistent")

    def test_param_schema(self):
        meta = get_metadata("6040")
        stock_param = [p for p in meta.params if p.name == "stock"][0]
        assert stock_param.type == "str"
        assert stock_param.default == "SPY"
        assert stock_param.choices is not None


# ══════════════════════════════════════════════
# Draft Models
# ══════════════════════════════════════════════

class TestStrategyDraft:

    def test_valid(self):
        d = StrategyDraft(type="q60s40")
        assert d.validate() == []

    def test_empty_invalid(self):
        d = StrategyDraft()
        errors = d.validate()
        assert len(errors) > 0

    def test_weights_sum_check(self):
        d = StrategyDraft(weights={"SPY": 0.5, "QQQ": 0.3})  # sum=0.8
        errors = d.validate()
        assert any("비중 합" in e for e in errors)

    def test_to_dict_type(self):
        d = StrategyDraft(type="spy_bnh")
        assert d.to_dict() == {"type": "spy_bnh"}

    def test_to_dict_weights(self):
        d = StrategyDraft(weights={"A": 0.5, "B": 0.5})
        assert d.to_dict()["weights"] == {"A": 0.5, "B": 0.5}


class TestAccountDraft:

    def test_valid_taxable(self):
        d = AccountDraft(type="TAXABLE", monthly=1000)
        assert d.validate() == []

    def test_invalid_type(self):
        d = AccountDraft(type="PENSION")
        assert len(d.validate()) > 0

    def test_negative_monthly(self):
        d = AccountDraft(monthly=-100)
        assert len(d.validate()) > 0

    def test_cap_is_krw_no_validation(self):
        """cap(KRW)과 monthly(USD)는 단위 달라 직접 비교 안 함."""
        d = AccountDraft(monthly=1000, annual_cap=500)
        assert len(d.validate()) == 0  # 에러 아님

    def test_to_dict(self):
        d = AccountDraft(type="ISA", monthly=500, priority=0)
        result = d.to_dict()
        assert result["type"] == "ISA"
        assert result["monthly_contribution"] == 500
        assert result["priority"] == 0


class TestBacktestDraft:

    def test_valid_full(self):
        d = BacktestDraft(
            strategy=StrategyDraft(type="q60s40"),
            accounts=[AccountDraft(type="TAXABLE", monthly=1000)],
            n_months=120,
        )
        assert d.validate() == []

    def test_no_accounts(self):
        d = BacktestDraft(strategy=StrategyDraft(type="spy_bnh"))
        errors = d.validate()
        assert any("계좌" in e for e in errors)

    def test_to_dict_roundtrip(self):
        original = BacktestDraft(
            strategy=StrategyDraft(type="q60s40"),
            accounts=[
                AccountDraft(type="ISA", monthly=300),
                AccountDraft(type="TAXABLE", monthly=700),
            ],
            n_months=240,
        )
        d = original.to_dict()
        restored = BacktestDraft.from_dict(d)
        assert restored.strategy.type == "q60s40"
        assert len(restored.accounts) == 2
        assert restored.n_months == 240

    def test_to_json(self):
        d = BacktestDraft(
            strategy=StrategyDraft(type="spy_bnh"),
            accounts=[AccountDraft(type="TAXABLE", monthly=1000)],
        )
        j = d.to_json()
        parsed = json.loads(j)
        assert parsed["strategy"]["type"] == "spy_bnh"

    def test_from_dict(self):
        data = {
            "strategy": {"type": "6040", "params": {"stock": "VOO"}},
            "accounts": [{"type": "ISA", "monthly_contribution": 500}],
            "n_months": 60,
        }
        d = BacktestDraft.from_dict(data)
        assert d.strategy.type == "6040"
        assert d.strategy.params == {"stock": "VOO"}
        assert d.accounts[0].monthly == 500


# ══════════════════════════════════════════════
# E2E: Draft → compile → engine
# ══════════════════════════════════════════════

class TestDraftToEngine:

    def test_full_pipeline(self):
        """Draft → validate → to_dict → compile → run_backtest."""
        import numpy as np
        import pandas as pd
        from aftertaxi.strategies.compile import compile_backtest
        from aftertaxi.core.facade import run_backtest

        draft = BacktestDraft(
            strategy=StrategyDraft(type="spy_bnh"),
            accounts=[AccountDraft(type="TAXABLE", monthly=1000)],
            n_months=24,
        )
        assert draft.validate() == []

        config = compile_backtest(draft.to_dict())

        idx = pd.date_range("2024-01-31", periods=24, freq="ME")
        prices = pd.DataFrame({"SPY": [100 + i for i in range(24)]}, index=idx)
        fx = pd.Series(1300.0, index=idx)
        returns = prices.pct_change().fillna(0.0)

        result = run_backtest(config, returns=returns, prices=prices, fx_rates=fx)
        assert result.gross_pv_usd > 0
        assert result.n_months == 24

    def test_metadata_to_draft_to_engine(self):
        """Metadata → Draft 생성 → engine."""
        import numpy as np
        import pandas as pd
        from aftertaxi.strategies.compile import compile_backtest
        from aftertaxi.core.facade import run_backtest

        meta = get_metadata("q60s40")
        draft = BacktestDraft(
            strategy=StrategyDraft(type=meta.key),
            accounts=[AccountDraft(type="TAXABLE", monthly=500)],
            n_months=12,
        )

        config = compile_backtest(draft.to_dict())
        assert config.strategy.weights == meta.default_weights

        idx = pd.date_range("2024-01-31", periods=12, freq="ME")
        prices = pd.DataFrame({
            "QQQ": [300 + i * 3 for i in range(12)],
            "SSO": [50 + i for i in range(12)],
        }, index=idx)
        fx = pd.Series(1300.0, index=idx)
        returns = prices.pct_change().fillna(0.0)

        result = run_backtest(config, returns=returns, prices=prices, fx_rates=fx)
        assert result.n_accounts == 1
