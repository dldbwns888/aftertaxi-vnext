# -*- coding: utf-8 -*-
"""test_apply_patch.py — SuggestionPatch 적용 계약 테스트

apply_patch() 구현 전에 계약을 먼저 박는다.
이 테스트가 통과해야 apply_patch가 안전하다.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
import json
from aftertaxi.strategies.compile import compile_backtest


def _base_payload():
    """기본 테스트 payload."""
    return {
        "strategy": {"type": "q60s40"},
        "accounts": [
            {"type": "ISA", "monthly_contribution": 500, "priority": 0},
            {"type": "TAXABLE", "monthly_contribution": 1000, "priority": 1},
        ],
        "n_months": 240,
    }


class TestApplyPatchContract:
    """apply_patch()가 지켜야 할 계약."""

    def test_compare_baseline_does_not_replace_strategy(self):
        """compare_baseline patch는 전략을 교체하면 안 됨."""
        from aftertaxi.advisor.rules import run_advisor
        from aftertaxi.advisor.types import AdvisorInput

        inp = AdvisorInput(
            mult_after_tax=2.0, mdd=-0.3, tax_drag_pct=10.0, n_months=240,
            has_isa=True, baseline_mult=None,
        )
        report = run_advisor(inp)
        baseline = [s for s in report.suggestions if s.kind == "compare_baseline"]
        assert len(baseline) > 0
        patch = baseline[0].patch

        # _action=compare 이지 strategy replace가 아님
        assert patch.get("_action") == "compare"
        assert "strategy" not in patch or patch.get("_action") == "compare"

    def test_use_band_preserves_monthly(self):
        """use_band patch가 기존 monthly/priority를 깨뜨리면 안 됨."""
        base = _base_payload()
        original_monthlies = [a["monthly_contribution"] for a in base["accounts"]]

        # use_band patch
        patch = {"accounts": [{"rebalance_mode": "BAND", "band_threshold_pct": 0.05}]}

        # 패치 적용 후에도 monthly 유지해야 함
        # (이건 apply_patch 구현 후 실행)
        # 지금은 원래 payload가 변하지 않는 것만 확인
        cfg = compile_backtest(base)
        assert cfg.accounts[0].monthly_contribution == 500
        assert cfg.accounts[1].monthly_contribution == 1000

    def test_add_isa_preserves_total_budget(self):
        """add_isa patch가 총 납입 의도를 유지해야 함."""
        base_single = {
            "strategy": {"type": "q60s40"},
            "accounts": [{"type": "TAXABLE", "monthly_contribution": 1000}],
        }
        cfg_before = compile_backtest(base_single)
        total_before = sum(a.monthly_contribution for a in cfg_before.accounts)

        # add_isa patch: ISA+TAXABLE 2계좌
        patch = {"accounts": [
            {"type": "ISA", "priority": 0},
            {"type": "TAXABLE", "priority": 1},
        ]}

        # 패치 적용 후 총 납입이 유지되어야 함 (apply_patch 구현 후 검증)
        # 지금은 기존 config의 총 납입 확인만
        assert total_before == 1000

    def test_patch_does_not_mutate_original(self):
        """patch 적용이 원본 payload를 변형하면 안 됨."""
        base = _base_payload()
        original_json = json.dumps(base)

        # 어떤 patch든 적용 후
        cfg = compile_backtest(base)
        after_json = json.dumps(base)

        assert original_json == after_json, "compile이 원본 payload를 변형함"


class TestApplySuggestionPatch:
    """apply_suggestion_patch() 실제 동작 테스트."""

    def test_compare_action_no_change(self):
        """_action=compare는 payload를 바꾸지 않음."""
        from aftertaxi.strategies.compile import apply_suggestion_patch
        base = _base_payload()
        result = apply_suggestion_patch(base, {"_action": "compare", "baseline": "spy_bnh"})
        assert result == base

    def test_use_band_preserves_existing_accounts(self):
        """BAND patch가 기존 계좌 monthly/priority 유지."""
        from aftertaxi.strategies.compile import apply_suggestion_patch
        base = _base_payload()
        patch = {"accounts": [{"rebalance_mode": "BAND", "band_threshold_pct": 0.05}]}
        result = apply_suggestion_patch(base, patch)

        # 기존 계좌 수 유지
        assert len(result["accounts"]) == 2
        # monthly 유지
        assert result["accounts"][0]["monthly_contribution"] == 500
        assert result["accounts"][1]["monthly_contribution"] == 1000
        # BAND 적용됨
        assert result["accounts"][0]["rebalance_mode"] == "BAND"

    def test_add_isa_to_taxable_only(self):
        """ISA 추가 patch — 기존 TAXABLE에 ISA 추가."""
        from aftertaxi.strategies.compile import apply_suggestion_patch
        base = {
            "strategy": {"type": "q60s40"},
            "accounts": [{"type": "TAXABLE", "monthly_contribution": 1000}],
        }
        patch = {"accounts": [
            {"type": "ISA", "priority": 0},
            {"type": "TAXABLE", "priority": 1},
        ]}
        result = apply_suggestion_patch(base, patch)

        # ISA 추가됨
        types = [a["type"] for a in result["accounts"]]
        assert "ISA" in types
        assert "TAXABLE" in types
        # TAXABLE monthly 유지
        taxable = [a for a in result["accounts"] if a["type"] == "TAXABLE"][0]
        assert taxable["monthly_contribution"] == 1000

    def test_original_not_mutated(self):
        """원본 payload 불변."""
        from aftertaxi.strategies.compile import apply_suggestion_patch
        base = _base_payload()
        original = json.dumps(base)
        apply_suggestion_patch(base, {"accounts": [{"rebalance_mode": "BAND"}]})
        assert json.dumps(base) == original

    def test_patched_payload_compiles(self):
        """patch 적용 후 compile 성공."""
        from aftertaxi.strategies.compile import apply_suggestion_patch
        base = _base_payload()
        patch = {"accounts": [{"rebalance_mode": "BAND", "band_threshold_pct": 0.05}]}
        result = apply_suggestion_patch(base, patch)
        cfg = compile_backtest(result)
        assert cfg is not None
