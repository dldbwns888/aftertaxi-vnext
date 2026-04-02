# -*- coding: utf-8 -*-
"""
validation/basic.py — 기본 검산
================================
EngineResult를 받아서 "이 결과가 말이 되는지" 체크.
코어를 안 건드리고, 결과만 본다.

체크 항목:
  - tax_drag_sanity: 세금이 0~80% 범위
  - mdd_sanity: MDD가 합리적 범위
  - pretax_geq_posttax: 세전 ≥ 세후 (항상)
  - invested_positive: 투자금 > 0
  - pv_nonnegative: PV ≥ 0
"""
from __future__ import annotations

from typing import List

from aftertaxi.core.contracts import EngineResult
from aftertaxi.validation.reports import CheckResult, Grade


def run_basic_checks(result: EngineResult) -> List[CheckResult]:
    """기본 검산 전체 실행. Returns: list of CheckResult."""
    checks = [
        check_tax_drag(result),
        check_mdd_range(result),
        check_pretax_geq_posttax(result),
        check_invested_positive(result),
        check_pv_nonnegative(result),
    ]
    return checks


def check_tax_drag(result: EngineResult, max_drag: float = 0.80) -> CheckResult:
    """세금 drag가 0~80% 범위인지."""
    if result.gross_pv_krw <= 0:
        return CheckResult(
            name="tax_drag_sanity",
            grade=Grade.WARN,
            value=0.0,
            threshold=max_drag,
            detail="gross_pv_krw ≤ 0, drag 계산 불가",
        )

    drag = result.tax.total_assessed_krw / result.gross_pv_krw
    if drag < 0:
        grade = Grade.FAIL
        detail = "세금이 음수 — 엔진 버그 가능성"
    elif drag > max_drag:
        grade = Grade.FAIL
        detail = f"세금이 PV의 {drag:.0%} — 비정상적으로 높음"
    else:
        grade = Grade.PASS
        detail = f"세금 drag {drag:.2%}"

    return CheckResult(
        name="tax_drag_sanity", grade=grade, value=drag,
        threshold=max_drag, detail=detail,
    )


def check_mdd_range(result: EngineResult, warn_threshold: float = -0.60) -> CheckResult:
    """MDD가 합리적 범위인지."""
    mdd = result.mdd
    if mdd < warn_threshold:
        grade = Grade.WARN
        detail = f"MDD {mdd:.1%} — 극단적 낙폭"
    elif mdd > 0.01:
        grade = Grade.FAIL
        detail = f"MDD {mdd:.1%} — 양수 MDD는 계산 오류"
    else:
        grade = Grade.PASS
        detail = f"MDD {mdd:.1%}"

    return CheckResult(
        name="mdd_range", grade=grade, value=mdd,
        threshold=warn_threshold, detail=detail,
    )


def check_pretax_geq_posttax(result: EngineResult) -> CheckResult:
    """세전 PV ≥ 세후 PV (항상 성립해야)."""
    diff = result.gross_pv_krw - result.net_pv_krw
    if diff < -1.0:  # 1원 허용
        return CheckResult(
            name="pretax_geq_posttax", grade=Grade.FAIL,
            value=diff, threshold=0.0,
            detail=f"세후가 세전보다 {-diff:,.0f} KRW 높음 — 버그",
        )
    return CheckResult(
        name="pretax_geq_posttax", grade=Grade.PASS,
        value=diff, threshold=0.0,
        detail=f"세전-세후 = {diff:,.0f} KRW",
    )


def check_invested_positive(result: EngineResult) -> CheckResult:
    """투자금이 양수."""
    if result.invested_usd <= 0:
        return CheckResult(
            name="invested_positive", grade=Grade.FAIL,
            value=result.invested_usd, threshold=0.0,
            detail="투자금 ≤ 0",
        )
    return CheckResult(
        name="invested_positive", grade=Grade.PASS,
        value=result.invested_usd, threshold=0.0,
    )


def check_pv_nonnegative(result: EngineResult) -> CheckResult:
    """PV가 음수가 아닌지."""
    if result.gross_pv_usd < -1e-6:
        return CheckResult(
            name="pv_nonnegative", grade=Grade.FAIL,
            value=result.gross_pv_usd, threshold=0.0,
            detail="PV 음수 — 엔진 버그",
        )
    return CheckResult(
        name="pv_nonnegative", grade=Grade.PASS,
        value=result.gross_pv_usd, threshold=0.0,
    )
