# -*- coding: utf-8 -*-
"""
validation/reports.py — 검증 결과 typed 계약
=============================================
모든 검증 함수의 출력은 여기 정의된 dataclass.
엔진 내부에 의존하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class Grade(str, Enum):
    """검증 등급."""
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True)
class CheckResult:
    """단일 검증 항목 결과."""
    name: str
    grade: Grade
    value: float          # 검증 지표 값
    threshold: float      # 기준값
    detail: str = ""      # 해석 문구


@dataclass
class ValidationReport:
    """전체 검증 리포트."""
    strategy_name: str
    checks: List[CheckResult] = field(default_factory=list)

    @property
    def n_pass(self) -> int:
        return sum(1 for c in self.checks if c.grade == Grade.PASS)

    @property
    def n_warn(self) -> int:
        return sum(1 for c in self.checks if c.grade == Grade.WARN)

    @property
    def n_fail(self) -> int:
        return sum(1 for c in self.checks if c.grade == Grade.FAIL)

    @property
    def overall_grade(self) -> Grade:
        if self.n_fail > 0:
            return Grade.FAIL
        if self.n_warn > 0:
            return Grade.WARN
        return Grade.PASS

    def summary_text(self) -> str:
        lines = [
            f"═══ Validation: {self.strategy_name} ═══",
            f"Overall: {self.overall_grade.value} "
            f"({self.n_pass} pass, {self.n_warn} warn, {self.n_fail} fail)",
            "",
        ]
        for c in self.checks:
            icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}[c.grade.value]
            lines.append(f"  {icon} {c.name}: {c.value:.4f} (threshold: {c.threshold:.4f})")
            if c.detail:
                lines.append(f"     {c.detail}")
        return "\n".join(lines)
