# -*- coding: utf-8 -*-
"""
intent/plan.py — 분석 계획 + 컴파일 추적
==========================================
BacktestConfig와 분리된 연구 실행 계획.

AnalysisPlan: "무슨 분석을 돌릴지"
CompileTrace: "왜 이렇게 컴파일됐는지"
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class AnalysisPlan:
    """실행할 분석 목록. BacktestConfig과 분리."""
    run_backtest: bool = True
    run_attribution: bool = True

    # 검증
    run_validation: bool = False
    validation_tests: List[str] = field(default_factory=list)  # ["dsr", "psr"]

    # Lane D
    run_lane_d: bool = False
    lane_d_paths: int = 50
    lane_d_mode: str = "sign_flip"

    # 비교
    compare_baselines: List[str] = field(default_factory=list)  # ["spy_bnh"]

    # 민감도
    run_sensitivity: bool = False

    # Advisor
    run_advisor: bool = False


@dataclass(frozen=True)
class CompileDecision:
    """하나의 컴파일 결정. 왜 이렇게 됐는지."""
    field: str      # 어떤 필드를
    value: str      # 무엇으로 결정했고
    reason: str     # 왜


@dataclass(frozen=True)
class CompileTrace:
    """컴파일 추적. 디버깅 + 사용자 설명 + 테스트용."""
    input_intent_summary: str
    decisions: List[CompileDecision] = field(default_factory=list)

    def summary_text(self) -> str:
        lines = [f"입력: {self.input_intent_summary}"]
        for d in self.decisions:
            lines.append(f"  {d.field} = {d.value} ← {d.reason}")
        return "\n".join(lines)


@dataclass(frozen=True)
class CompileOutput:
    """compile_intent()의 반환값."""
    # BacktestConfig는 여기서 import하지 않음 — 순환 방지.
    # 실제로는 Tuple[BacktestConfig, AnalysisPlan, CompileTrace]로 반환.
    plan: AnalysisPlan = field(default_factory=AnalysisPlan)
    trace: CompileTrace = field(default_factory=lambda: CompileTrace(""))
