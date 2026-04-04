# -*- coding: utf-8 -*-
"""
advisor/advisor_v2.py — Advisor 2.0: 종합 판단기
=================================================
"이 전략을 한국 유저가 세후로 써도 되는가?"

KRW attribution + tax interpretation + ISA optimizer + validation을
하나로 묶어서 판단.

사용법:
  from aftertaxi.advisor.advisor_v2 import build_advisor_v2

  report = build_advisor_v2(result, config, ...)
  print(report.summary)
  print(report.overall_grade)  # "strong" | "mixed" | "fragile"
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class AdvisorV2Report:
    """종합 판단 보고서."""
    overall_grade: str       # "strong" | "mixed" | "fragile"
    summary: str
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)
    action_items: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def full_text(self) -> str:
        lines = [f"[{self.overall_grade.upper()}] {self.summary}", ""]
        if self.strengths:
            lines.append("✅ 강점:")
            for s in self.strengths:
                lines.append(f"  · {s}")
        if self.weaknesses:
            lines.append("⚠ 약점:")
            for w in self.weaknesses:
                lines.append(f"  · {w}")
        if self.action_items:
            lines.append("💡 다음 행동:")
            for a in self.action_items:
                lines.append(f"  → {a}")
        if self.warnings:
            lines.append("🔴 경고:")
            for w in self.warnings:
                lines.append(f"  ! {w}")
        return "\n".join(lines)


def build_advisor_v2(
    result,
    config,
    attribution=None,
    krw_report=None,
    tax_report=None,
    isa_report=None,
    validation_report=None,
    baseline_result=None,
) -> AdvisorV2Report:
    """종합 판단 생성.

    각 분석 모듈 결과를 받아서 하나의 판단으로 종합.
    None인 입력은 건너뜀 (graceful degradation).
    """
    strengths = []
    weaknesses = []
    actions = []
    warnings = []
    grade_score = 0  # +1 강점, -1 약점

    # ── 1. 기본 성과 ──
    mult = result.mult_after_tax
    mdd = result.mdd

    if mult > 2.0:
        strengths.append(f"세후 배수 {mult:.2f}x — 장기 복리 효과 강함.")
        grade_score += 1
    elif mult < 1.0:
        weaknesses.append(f"세후 배수 {mult:.2f}x — 원금 미회복.")
        grade_score -= 2

    if mdd > -0.15:
        strengths.append(f"MDD {mdd:.0%} — 낙폭 관리 양호.")
        grade_score += 1
    elif mdd < -0.35:
        weaknesses.append(f"MDD {mdd:.0%} — 심리적 이탈 위험.")
        grade_score -= 1

    # ── 2. baseline 대비 ──
    if baseline_result:
        gap = mult - baseline_result.mult_after_tax
        if gap > 0.1:
            strengths.append(f"SPY B&H 대비 +{gap:.2f}x 우위.")
        elif gap < -0.1:
            weaknesses.append(f"SPY B&H 대비 {gap:.2f}x 열위. 복잡도 대비 이득 불분명.")
            grade_score -= 1

    # ── 3. KRW attribution ──
    if krw_report:
        total_gain = krw_report.asset_gain_krw + krw_report.fx_effect_krw
        if total_gain > 0:
            asset_share = krw_report.asset_gain_krw / total_gain * 100 if total_gain > 0 else 0
            fx_share = krw_report.fx_effect_krw / total_gain * 100 if total_gain > 0 else 0

            if asset_share > 70:
                strengths.append(f"수익의 {asset_share:.0f}%가 자산 성과. 실체 있는 수익.")
                grade_score += 1
            if fx_share > 40:
                weaknesses.append(f"수익의 {fx_share:.0f}%가 환율 효과. 원화 강세 시 반전 위험.")
                actions.append("환율 변동 시나리오 확인 권장.")
                grade_score -= 1

        if krw_report.tax_drag_krw > 5_000_000:
            weaknesses.append(f"세금 손실 ₩{krw_report.tax_drag_krw:,.0f}.")

    # ── 4. 세금 구조 ──
    if tax_report:
        if tax_report.tax_concentration > 50 and tax_report.peak_tax_year:
            weaknesses.append(
                f"{tax_report.peak_tax_year}년에 세금 {tax_report.tax_concentration:.0f}% 집중. "
                f"최종 청산 시 현금 부담.")
            grade_score -= 1

        for finding in tax_report.findings[:2]:
            weaknesses.append(finding)

        for opp in tax_report.opportunities[:2]:
            actions.append(opp)

    # ── 5. ISA 여지 ──
    if isa_report and isa_report.tax_savings_krw > 500_000:
        actions.append(
            f"ISA 비중 {isa_report.best_isa_pct:.0%}로 변경 시 "
            f"₩{isa_report.tax_savings_krw:,.0f} 절세 가능.")
        grade_score += 1

    # ── 6. 검증 ──
    if validation_report:
        n_fail = getattr(validation_report, "n_fail", 0)
        n_warn = getattr(validation_report, "n_warn", 0)
        if n_fail > 0:
            warnings.append(f"검증 실패 {n_fail}건. 실전 전환 보류 권장.")
            grade_score -= 2
        elif n_warn > 1:
            weaknesses.append(f"검증 경고 {n_warn}건. 추가 확인 필요.")
            grade_score -= 1
        else:
            strengths.append("통계 검증 통과.")
            grade_score += 1

    # ── 종합 등급 ──
    if grade_score >= 3:
        grade = "strong"
    elif grade_score >= 0:
        grade = "mixed"
    else:
        grade = "fragile"

    # ── 요약문 ──
    summary_parts = []
    if grade == "strong":
        summary_parts.append("세후 구조가 건강하고 검증도 양호.")
    elif grade == "mixed":
        summary_parts.append("성과는 있지만 구조적 개선 여지 존재.")
    else:
        summary_parts.append("세후 구조 취약. 실전 전환 전 재검토 필요.")

    if actions:
        summary_parts.append(f"개선안 {len(actions)}건.")

    summary = " ".join(summary_parts)

    return AdvisorV2Report(
        overall_grade=grade,
        summary=summary,
        strengths=strengths,
        weaknesses=weaknesses,
        action_items=actions,
        warnings=warnings,
    )
