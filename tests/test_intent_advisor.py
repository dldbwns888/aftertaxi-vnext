# -*- coding: utf-8 -*-
"""test_intent_advisor.py — Intent 타입 + Advisor 규칙 테스트"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from aftertaxi.intent.types import FullIntent, StrategyIntent, AccountIntent, ResearchIntent
from aftertaxi.intent.plan import AnalysisPlan, CompileTrace, CompileDecision
from aftertaxi.advisor.types import AdvisorInput, Diagnosis, SuggestionPatch, AdvisorReport
from aftertaxi.advisor.rules import run_advisor, _diagnose, _suggest


class TestIntentTypes:

    def test_default_intent(self):
        """기본값으로 생성 가능."""
        intent = FullIntent()
        assert intent.strategy.leverage_ok is True
        assert intent.account.isa_first is True
        assert intent.research.compare_baseline is True

    def test_intent_is_frozen(self):
        """Intent는 불변."""
        intent = StrategyIntent(description="test")
        with pytest.raises(AttributeError):
            intent.description = "changed"

    def test_fuzzy_weights(self):
        """weights_hint는 str도 dict도 None도 됨 — 이게 Intent의 핵심."""
        s1 = StrategyIntent(weights_hint="6:4")
        s2 = StrategyIntent(weights_hint={"QQQ": 0.6, "SSO": 0.4})
        s3 = StrategyIntent(weights_hint=None)
        assert isinstance(s1.weights_hint, str)
        assert isinstance(s2.weights_hint, dict)
        assert s3.weights_hint is None


class TestAnalysisPlan:

    def test_default_plan(self):
        plan = AnalysisPlan()
        assert plan.run_backtest is True
        assert plan.run_advisor is False
        assert plan.compare_baselines == []

    def test_plan_is_frozen(self):
        plan = AnalysisPlan()
        with pytest.raises(AttributeError):
            plan.run_backtest = False


class TestCompileTrace:

    def test_trace_summary(self):
        trace = CompileTrace(
            input_intent_summary="QQQ SSO 6:4, ISA 먼저",
            decisions=[
                CompileDecision("rebalance_mode", "BAND 5%", "rebalance_hint='drift_only'"),
                CompileDecision("isa_priority", "0", "isa_first=True"),
            ],
        )
        text = trace.summary_text()
        assert "BAND" in text
        assert "isa_first" in text


class TestAdvisorInput:

    def test_frozen(self):
        inp = AdvisorInput(mult_after_tax=2.0, mdd=-0.3, tax_drag_pct=15.0, n_months=120)
        with pytest.raises(AttributeError):
            inp.mdd = -0.5

    def test_no_raw_data_fields(self):
        """AdvisorInput에 monthly_values, positions, journal 필드가 없음."""
        fields = {f.name for f in AdvisorInput.__dataclass_fields__.values()}
        assert "monthly_values" not in fields
        assert "positions" not in fields
        assert "journal" not in fields
        assert "returns" not in fields


class TestAdvisorRules:

    def test_healthy_no_critical(self):
        """건강한 전략 → critical 0."""
        inp = AdvisorInput(
            mult_after_tax=3.0, mdd=-0.25, tax_drag_pct=12.0, n_months=240,
            has_isa=True, has_progressive=True,
        )
        report = run_advisor(inp)
        assert report.n_critical == 0

    def test_high_tax_drag(self):
        inp = AdvisorInput(
            mult_after_tax=2.0, mdd=-0.3, tax_drag_pct=35.0, n_months=240,
        )
        report = run_advisor(inp)
        codes = [d.code for d in report.diagnoses]
        assert "HIGH_TAX_DRAG" in codes

    def test_no_isa_triggers(self):
        inp = AdvisorInput(
            mult_after_tax=2.0, mdd=-0.3, tax_drag_pct=20.0, n_months=240,
            has_isa=False,
        )
        report = run_advisor(inp)
        codes = [d.code for d in report.diagnoses]
        assert "NO_ISA" in codes

    def test_extreme_mdd(self):
        inp = AdvisorInput(
            mult_after_tax=2.0, mdd=-0.65, tax_drag_pct=10.0, n_months=240,
        )
        report = run_advisor(inp)
        codes = [d.code for d in report.diagnoses]
        assert "EXTREME_MDD" in codes

    def test_progressive_not_modeled(self):
        inp = AdvisorInput(
            mult_after_tax=2.0, mdd=-0.3, tax_drag_pct=20.0, n_months=240,
            has_progressive=False,
        )
        report = run_advisor(inp)
        codes = [d.code for d in report.diagnoses]
        assert "PROGRESSIVE_NOT_MODELED" in codes

    def test_low_survival(self):
        inp = AdvisorInput(
            mult_after_tax=0.5, mdd=-0.7, tax_drag_pct=5.0, n_months=600,
            lane_d_survival=0.30,
        )
        report = run_advisor(inp)
        codes = [d.code for d in report.diagnoses]
        assert "LOW_SURVIVAL" in codes

    def test_max_3_suggestions(self):
        """제안은 최대 3개."""
        inp = AdvisorInput(
            mult_after_tax=1.0, mdd=-0.6, tax_drag_pct=35.0, n_months=240,
            has_isa=False, has_progressive=False,
            lane_d_survival=0.2,
        )
        report = run_advisor(inp)
        assert len(report.suggestions) <= 3

    def test_suggestion_is_patch(self):
        """제안은 항상 patch 형태."""
        inp = AdvisorInput(
            mult_after_tax=2.0, mdd=-0.3, tax_drag_pct=25.0, n_months=240,
            has_isa=False,
        )
        report = run_advisor(inp)
        for s in report.suggestions:
            assert isinstance(s.patch, dict)
            assert isinstance(s.rationale_codes, list)

    def test_summary_text(self):
        inp = AdvisorInput(
            mult_after_tax=2.0, mdd=-0.6, tax_drag_pct=30.0, n_months=240,
        )
        report = run_advisor(inp)
        assert len(report.summary) > 0


class TestAdvisorBuilder:

    def test_build_from_engine_result(self):
        """E2E: EngineResult → AdvisorInput → AdvisorReport."""
        import numpy as np
        import pandas as pd
        from aftertaxi.core.contracts import (
            AccountConfig, AccountType, BacktestConfig, StrategyConfig,
        )
        from aftertaxi.core.facade import run_backtest
        from aftertaxi.core.attribution import build_attribution
        from aftertaxi.advisor.builder import build_advisor_input

        rng = np.random.default_rng(42)
        idx = pd.date_range("2020-01-31", periods=60, freq="ME")
        ret = pd.DataFrame({"SPY": rng.normal(0.008, 0.04, 60)}, index=idx)
        pri = 100 * (1 + ret).cumprod()
        fx = pd.Series(1300.0, index=idx)

        config = BacktestConfig(
            accounts=[AccountConfig("t", AccountType.TAXABLE, 1000.0)],
            strategy=StrategyConfig("spy", {"SPY": 1.0}),
        )
        result = run_backtest(config, returns=ret, prices=pri, fx_rates=fx)
        attr = build_attribution(result)

        # builder로 정제
        inp = build_advisor_input(result, attr, config)

        # Advisor 실행
        report = run_advisor(inp)

        assert isinstance(report, AdvisorReport)
        assert report.summary != ""
        # 60개월 짧은 기간이라 drag 작을 수 있음 → 최소한 에러 없이 동작 확인
        # baseline 비교 제안은 거의 항상 나옴
        suggestion_kinds = [s.kind for s in report.suggestions]
        assert "compare_baseline" in suggestion_kinds
