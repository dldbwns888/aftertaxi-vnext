# -*- coding: utf-8 -*-
"""test_bug_report.py — 버그 리포트 기반 회귀 테스트"""

import pytest
from aftertaxi.advisor.types import AdvisorInput, SuggestionPatch
from aftertaxi.advisor.rules import run_advisor, _suggest, _diagnose


class TestPatchSemantics:
    """#1 + #4: SuggestionPatch 의미 검증."""

    def test_compare_baseline_is_not_strategy_replace(self):
        """baseline 비교 제안은 strategy replace가 아니라 compare action이어야 함."""
        inp = AdvisorInput(
            mult_after_tax=2.0, mdd=-0.3, tax_drag_pct=10.0, n_months=240,
            has_isa=True, baseline_mult=None,
        )
        report = run_advisor(inp)
        baseline_suggestions = [s for s in report.suggestions if s.kind == "compare_baseline"]
        assert len(baseline_suggestions) > 0
        patch = baseline_suggestions[0].patch
        # strategy replace가 아님
        assert "strategy" not in patch or "_action" in patch
        assert patch.get("_action") == "compare"

    def test_add_isa_patch_has_accounts_list(self):
        """add_isa patch는 accounts 리스트."""
        inp = AdvisorInput(
            mult_after_tax=2.0, mdd=-0.3, tax_drag_pct=20.0, n_months=240,
            has_isa=False,
        )
        report = run_advisor(inp)
        isa_suggestions = [s for s in report.suggestions if s.kind == "add_isa"]
        assert len(isa_suggestions) > 0
        patch = isa_suggestions[0].patch
        assert "accounts" in patch
        assert isinstance(patch["accounts"], list)


class TestMultiAccountAdvisor:
    """#3: multi-account AdvisorInput 정제."""

    def test_has_band_account_true(self):
        """BAND 쓰는 계좌 있으면 has_band_account=True."""
        inp = AdvisorInput(
            mult_after_tax=2.0, mdd=-0.3, tax_drag_pct=30.0, n_months=240,
            has_band_account=True, all_contribution_only=False,
        )
        report = run_advisor(inp)
        # BAND 이미 있으니 use_band 제안이 안 나와야 함
        kinds = [s.kind for s in report.suggestions]
        assert "use_band" not in kinds

    def test_all_contribution_only_gets_band_suggestion(self):
        """전부 C/O면 BAND 제안이 나올 수 있음."""
        inp = AdvisorInput(
            mult_after_tax=2.0, mdd=-0.3, tax_drag_pct=30.0, n_months=240,
            has_band_account=False, all_contribution_only=True,
        )
        report = run_advisor(inp)
        kinds = [s.kind for s in report.suggestions]
        assert "use_band" in kinds

    def test_builder_multi_account(self):
        """builder가 2계좌에서 올바르게 정제."""
        import numpy as np, pandas as pd
        from aftertaxi.core.contracts import (
            AccountConfig, AccountType, BacktestConfig, StrategyConfig, RebalanceMode,
        )
        from aftertaxi.core.facade import run_backtest
        from aftertaxi.core.attribution import build_attribution
        from aftertaxi.advisor.builder import build_advisor_input

        rng = np.random.default_rng(42)
        idx = pd.date_range("2020-01-31", periods=24, freq="ME")
        ret = pd.DataFrame({"SPY": rng.normal(0.008, 0.04, 24)}, index=idx)
        pri = 100 * (1 + ret).cumprod()
        fx = pd.Series(1300.0, index=idx)

        config = BacktestConfig(
            accounts=[
                AccountConfig("isa", AccountType.ISA, 500.0, priority=0),
                AccountConfig("tax", AccountType.TAXABLE, 500.0, priority=1,
                              rebalance_mode=RebalanceMode.BAND),
            ],
            strategy=StrategyConfig("spy", {"SPY": 1.0}),
        )
        result = run_backtest(config, returns=ret, prices=pri, fx_rates=fx)
        attr = build_attribution(result)
        inp = build_advisor_input(result, attr, config)

        assert inp.has_isa is True
        assert inp.has_band_account is True
        assert inp.all_contribution_only is False
        assert inp.n_accounts == 2


class TestSuggestionPriority:
    """제안 priority + dedup."""

    def test_dedup_by_kind(self):
        """같은 kind는 priority 높은 것만 남음."""
        from aftertaxi.advisor.rules import _suggest
        diagnoses_codes = {"HIGH_TAX_DRAG", "NO_ISA", "PROGRESSIVE_NOT_MODELED"}
        inp = AdvisorInput(
            mult_after_tax=1.0, mdd=-0.6, tax_drag_pct=40.0, n_months=240,
            has_isa=False, has_progressive=False, has_band_account=False,
        )
        report = run_advisor(inp)
        kinds = [s.kind for s in report.suggestions]
        # 중복 없음
        assert len(kinds) == len(set(kinds))
        # max 3
        assert len(kinds) <= 3
