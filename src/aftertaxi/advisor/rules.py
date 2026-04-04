# -*- coding: utf-8 -*-
"""
advisor/rules.py — 규칙 기반 진단 + 제안 (MVP)
===============================================
Advisor의 핵심. AdvisorInput만 받고, raw data 접근 없음.

MVP 규칙 5개:
  1. HIGH_TAX_DRAG      — drag > 25%
  2. NO_ISA             — ISA 없고 drag > 10%
  3. EXTREME_MDD        — MDD < -50%
  4. PROGRESSIVE_NOT_MODELED — 누진 미반영, drag > 15%
  5. ALWAYS_COMPARE_BASELINE — 항상
"""
from __future__ import annotations

from typing import List

from aftertaxi.advisor.types import (
    AdvisorInput, Diagnosis, SuggestionPatch, AdvisorReport,
)


# ══════════════════════════════════════════════
# 진단 규칙 (증상)
# ══════════════════════════════════════════════

def _diagnose(inp: AdvisorInput) -> List[Diagnosis]:
    dx = []

    # 1. HIGH_TAX_DRAG
    if inp.tax_drag_pct > 25:
        dx.append(Diagnosis(
            "HIGH_TAX_DRAG", "critical",
            f"세금 drag {inp.tax_drag_pct:.0f}%로 수익의 1/4 이상이 세금.",
            inp.tax_drag_pct, 25,
        ))
    elif inp.tax_drag_pct > 15:
        dx.append(Diagnosis(
            "MODERATE_TAX_DRAG", "warning",
            f"세금 drag {inp.tax_drag_pct:.0f}%.",
            inp.tax_drag_pct, 15,
        ))

    # 2. NO_ISA
    if not inp.has_isa and inp.tax_drag_pct > 10:
        dx.append(Diagnosis(
            "NO_ISA", "critical",
            "ISA 계좌 미사용. ISA 추가 시 세금 대폭 절감 가능.",
            0, 0,
        ))

    # 3. EXTREME_MDD
    if inp.mdd < -0.50:
        dx.append(Diagnosis(
            "EXTREME_MDD", "critical",
            f"MDD {inp.mdd:.0%}. 50% 이상 하락은 심리적으로 견디기 매우 어려움.",
            inp.mdd, -0.50,
        ))
    elif inp.mdd < -0.30:
        dx.append(Diagnosis(
            "HIGH_MDD", "warning",
            f"MDD {inp.mdd:.0%}. 30% 이상 하락 경험.",
            inp.mdd, -0.30,
        ))

    # 4. PROGRESSIVE_NOT_MODELED
    if not inp.has_progressive and inp.tax_drag_pct > 15:
        dx.append(Diagnosis(
            "PROGRESSIVE_NOT_MODELED", "warning",
            "누진세 미반영. 실제 drag는 더 높을 수 있음 (flat 22% 가정).",
            0, 0,
        ))

    # 5. LOW_SURVIVAL (Lane D 결과 있을 때)
    if inp.lane_d_survival is not None and inp.lane_d_survival < 0.50:
        dx.append(Diagnosis(
            "LOW_SURVIVAL", "critical",
            f"50년 생존률 {inp.lane_d_survival:.0%}. 장기 구조적 위험.",
            inp.lane_d_survival, 0.50,
        ))

    return dx


# ══════════════════════════════════════════════
# 제안 규칙 (처방) — patch 방식만
# ══════════════════════════════════════════════

def _suggest(inp: AdvisorInput, diagnoses: List[Diagnosis]) -> List[SuggestionPatch]:
    suggestions = []
    codes = {d.code for d in diagnoses}

    # ISA 추가
    if "NO_ISA" in codes:
        suggestions.append(SuggestionPatch(
            "add_isa",
            "ISA 계좌 추가 권장. 월 $1,282 이하면 세금 0 달성 가능.",
            patch={"accounts": [
                {"type": "ISA", "priority": 0},
                {"type": "TAXABLE", "priority": 1},
            ]},
            rationale_codes=["NO_ISA", "HIGH_TAX_DRAG"],
            priority=10,
        ))

    # BAND 리밸런싱
    if "HIGH_TAX_DRAG" in codes and inp.rebalance_mode != "BAND":
        suggestions.append(SuggestionPatch(
            "use_band",
            "BAND 리밸런싱으로 공제 분산 효과. 세금 ~12% 완화 가능.",
            patch={"accounts": [{"rebalance_mode": "BAND", "band_threshold_pct": 0.05}]},
            rationale_codes=["HIGH_TAX_DRAG"],
            priority=20,
        ))

    # 누진세 모델링
    if "PROGRESSIVE_NOT_MODELED" in codes:
        suggestions.append(SuggestionPatch(
            "enable_progressive",
            "누진세 모델링 활성화 권장. 실제 세금 부담을 정확히 확인.",
            patch={"accounts": [{"progressive": True}]},
            rationale_codes=["PROGRESSIVE_NOT_MODELED"],
            priority=30,
        ))

    # baseline 비교 (거의 항상)
    if inp.baseline_mult is None:
        suggestions.append(SuggestionPatch(
            "compare_baseline",
            "SPY 100% B&H와 비교하면 이 전략의 실제 가치를 확인할 수 있습니다.",
            patch={"strategy": {"type": "spy_bnh"}},
            rationale_codes=[],
            priority=90,
        ))

    # dedup by kind + sort by priority + max 3
    seen_kinds = set()
    deduped = []
    for s in sorted(suggestions, key=lambda x: x.priority):
        if s.kind not in seen_kinds:
            seen_kinds.add(s.kind)
            deduped.append(s)
    return deduped[:3]


# ══════════════════════════════════════════════
# 메인 진입점
# ══════════════════════════════════════════════

def run_advisor(inp: AdvisorInput) -> AdvisorReport:
    """Advisor 실행. AdvisorInput만 받음 — raw data 접근 없음.

    시그니처가 이 원칙을 강제한다:
      - EngineResult 못 받음
      - monthly_values 못 받음
      - journal 못 받음
      - positions 못 받음
    """
    diagnoses = _diagnose(inp)
    suggestions = _suggest(inp, diagnoses)

    # 요약
    n_crit = sum(1 for d in diagnoses if d.severity == "critical")
    n_warn = sum(1 for d in diagnoses if d.severity == "warning")

    if n_crit > 0:
        summary = f"주의 필요: {n_crit}개 심각한 문제 발견."
    elif n_warn > 0:
        summary = f"개선 여지: {n_warn}개 권고사항."
    else:
        summary = "양호. 특별한 문제 없음."

    if suggestions:
        summary += f" {len(suggestions)}개 개선안 제안."

    return AdvisorReport(
        diagnoses=diagnoses,
        suggestions=suggestions,
        summary=summary,
    )
