# -*- coding: utf-8 -*-
"""
workbench/interpret.py — 결과 해석 텍스트 자동 생성
===================================================
EngineResult + Attribution → 한국어 해석 문장.

사용법:
  from aftertaxi.workbench.interpret import interpret_result

  text = interpret_result(result, attribution)
  # → "20년 적립 결과 세후 2.45배. 세금이 전체 수익의 12%를 가져갔으며..."
"""
from __future__ import annotations

from typing import List

from aftertaxi.core.contracts import EngineResult
from aftertaxi.core.attribution import ResultAttribution


def interpret_result(
    result: EngineResult,
    attribution: ResultAttribution,
) -> str:
    """결과 해석 텍스트."""
    lines: List[str] = []
    years = result.n_months / 12

    # 핵심 성과
    lines.append(
        f"{years:.0f}년 적립 결과: 세후 {result.mult_after_tax:.2f}배 "
        f"(투입 ${result.invested_usd:,.0f} → 세후 ₩{result.net_pv_krw:,.0f})."
    )

    # 세금 drag
    drag = attribution.tax_drag_pct
    if drag > 15:
        lines.append(f"세금 drag가 {drag:.1f}%로 높습니다. 최종 청산 시 큰 이익이 한번에 과세된 것으로 보입니다.")
    elif drag > 5:
        lines.append(f"세금 drag {drag:.1f}%는 전형적인 수준입니다.")
    elif drag > 0:
        lines.append(f"세금 drag {drag:.1f}%로 매우 효율적입니다.")

    # 세금 분해
    total_tax = result.tax.total_assessed_krw
    if total_tax > 0:
        cgt = sum(a.capital_gains_tax_krw for a in result.accounts)
        div_tax = sum(a.dividend_tax_krw for a in result.accounts)
        hi = result.person.health_insurance_krw

        parts = []
        if cgt > 0:
            pct = cgt / total_tax * 100
            parts.append(f"양도세 {pct:.0f}%")
        if div_tax > 0:
            pct = div_tax / total_tax * 100
            parts.append(f"배당세 {pct:.0f}%")
        if hi > 0:
            pct = hi / total_tax * 100
            parts.append(f"건보료 {pct:.0f}%")

        if parts:
            lines.append(f"세금 구성: {', '.join(parts)}.")

    # 배당
    total_div = attribution.total_dividend_gross_usd
    if total_div > 0:
        div_pct = total_div / result.gross_pv_usd * 100 if result.gross_pv_usd > 0 else 0
        lines.append(f"배당 총액 ${total_div:,.0f} (PV 대비 {div_pct:.1f}%).")

    # MDD
    mdd = result.mdd
    if mdd < -0.30:
        lines.append(f"MDD {mdd:.0%}로 상당히 큰 낙폭을 경험했습니다. 이 수준의 하락을 견딜 심리적 준비가 필요합니다.")
    elif mdd < -0.15:
        lines.append(f"MDD {mdd:.0%}는 레버리지 포트폴리오 기준 중간 수준입니다.")

    # 계좌 수
    if result.n_accounts > 1:
        isa_accounts = [a for a in result.accounts if a.account_type == "ISA"]
        if isa_accounts:
            isa_tax = sum(a.tax_assessed_krw for a in isa_accounts)
            taxable_tax = total_tax - isa_tax
            savings = taxable_tax - total_tax  # ISA가 절세한 만큼
            lines.append(
                f"ISA 계좌 활용으로 세금 구조가 분산되었습니다. "
                f"(TAXABLE 세금 ₩{taxable_tax:,.0f}, ISA 세금 ₩{isa_tax:,.0f})"
            )

    return "\n".join(lines)


def interpret_comparison(
    result1: EngineResult, result2: EngineResult,
    name1: str, name2: str,
) -> str:
    """두 전략 비교 해석."""
    lines = []

    m1, m2 = result1.mult_after_tax, result2.mult_after_tax
    winner = name1 if m1 > m2 else name2
    diff = abs(m1 - m2)

    lines.append(f"세후 기준 {winner}가 {diff:.2f}x 더 좋습니다.")

    # MDD 비교
    mdd1, mdd2 = result1.mdd, result2.mdd
    safer = name1 if mdd1 > mdd2 else name2  # mdd is negative, bigger = safer
    lines.append(f"MDD 기준 {safer}가 더 안정적입니다 ({name1} {mdd1:.0%} vs {name2} {mdd2:.0%}).")

    # 세금 비교
    t1 = result1.tax.total_assessed_krw
    t2 = result2.tax.total_assessed_krw
    cheaper = name1 if t1 < t2 else name2
    lines.append(f"세금 기준 {cheaper}가 더 효율적입니다.")

    return "\n".join(lines)
