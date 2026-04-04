# -*- coding: utf-8 -*-
"""
analysis/tax_interpretation.py — 세금 구조 해석
================================================
"세금이 왜 이렇게 나왔는가?"

숫자 → 원인 → 개선 여지를 설명.

사용법:
  from aftertaxi.analysis.tax_interpretation import interpret_tax_structure

  report = interpret_tax_structure(result)
  print(report.summary_text)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class TaxStructureReport:
    """세금 구조 해석 결과."""
    # 구조 분석
    dominant_tax_type: str          # "capital_gains" | "dividend" | "isa_excess" | "health_insurance"
    cgt_pct: float                  # 양도세 비중 (%)
    dividend_pct: float             # 배당세 비중 (%)
    health_pct: float               # 건보료 비중 (%)
    total_tax_krw: float

    # 시간 분석
    peak_tax_year: Optional[int] = None
    peak_tax_amount: float = 0.0
    tax_concentration: float = 0.0  # 최고 연도가 전체의 몇 %

    # 해석
    findings: List[str] = field(default_factory=list)
    opportunities: List[str] = field(default_factory=list)

    @property
    def summary_text(self) -> str:
        lines = []
        if self.findings:
            lines.append("📊 세금 구조:")
            for f in self.findings:
                lines.append(f"  · {f}")
        if self.opportunities:
            lines.append("💡 개선 여지:")
            for o in self.opportunities:
                lines.append(f"  · {o}")
        return "\n".join(lines) if lines else "세금 구조 특이점 없음."


def interpret_tax_structure(result, config=None) -> TaxStructureReport:
    """EngineResult → 세금 구조 해석."""
    # 세금 항목 합산
    cgt = sum(a.capital_gains_tax_krw for a in result.accounts)
    div = sum(a.dividend_tax_krw for a in result.accounts)
    hi = result.person.health_insurance_krw
    total = cgt + div + hi

    if total < 1:
        return TaxStructureReport(
            dominant_tax_type="none", cgt_pct=0, dividend_pct=0,
            health_pct=0, total_tax_krw=0,
            findings=["세금 0 — ISA 비과세 한도 내이거나 공제 범위 내."],
        )

    cgt_pct = cgt / total * 100
    div_pct = div / total * 100
    hi_pct = hi / total * 100

    # dominant type
    if cgt_pct >= 60:
        dominant = "capital_gains"
    elif div_pct >= 40:
        dominant = "dividend"
    elif hi_pct >= 30:
        dominant = "health_insurance"
    else:
        dominant = "mixed"

    # 연도별 분석
    history = getattr(result, "annual_tax_history", [])
    peak_year, peak_amount, concentration = None, 0.0, 0.0
    if history:
        max_entry = max(history, key=lambda h: h.get("total_krw", 0))
        peak_year = max_entry.get("year")
        peak_amount = max_entry.get("total_krw", 0)
        concentration = (peak_amount / total * 100) if total > 0 else 0

    # 해석 규칙
    findings = []
    opportunities = []

    if cgt_pct > 80:
        findings.append(f"양도세가 전체의 {cgt_pct:.0f}%. 매도 시점에 세금이 집중됩니다.")
    if div_pct > 30:
        findings.append(f"배당세가 전체의 {div_pct:.0f}%. 배당 높은 자산의 세후 효율 확인 필요.")
    if hi_pct > 15:
        findings.append(f"건보료가 전체의 {hi_pct:.0f}%. 배당소득 ₩2,000만 초과 가능성.")
    if concentration > 50 and peak_year:
        findings.append(f"{peak_year}년에 세금의 {concentration:.0f}%가 집중. "
                        f"최종 청산 시 세금 폭탄 주의.")
    if not findings:
        findings.append("세금 구조가 비교적 균형적.")

    # ISA 기회
    has_isa = False
    if config:
        has_isa = any(
            getattr(a, "account_type", "").upper() == "ISA"
            or str(getattr(a, "account_type", "")).upper() == "ACCOUNTTYPE.ISA"
            for a in config.accounts
        )
    if not has_isa and total > 500_000:
        opportunities.append("ISA 계좌 미사용. ISA 활용 시 연 ₩200만 비과세 가능.")
    if cgt > 5_000_000:
        opportunities.append(f"양도세 ₩{cgt:,.0f}. 매도 시점 분산이나 ISA 비중 확대 검토.")
    if div > 2_000_000:
        opportunities.append("배당소득 ₩2,000만 초과 시 종합과세. 배당 낮은 자산 검토.")

    return TaxStructureReport(
        dominant_tax_type=dominant,
        cgt_pct=cgt_pct,
        dividend_pct=div_pct,
        health_pct=hi_pct,
        total_tax_krw=total,
        peak_tax_year=peak_year,
        peak_tax_amount=peak_amount,
        tax_concentration=concentration,
        findings=findings,
        opportunities=opportunities,
    )
