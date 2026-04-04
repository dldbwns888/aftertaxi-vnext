# -*- coding: utf-8 -*-
"""
advisor/types.py — Advisor 타입
===============================
핵심 원칙: Advisor는 계산하지 않고 판단만 한다.

강제 방법: AdvisorInput은 정제된 요약만 담는다.
  - EngineResult 전체를 넘기지 않는다.
  - monthly_values, positions, journal에 접근 못 한다.
  - 숫자를 직접 계산할 재료가 없다.
  - 있는 건 이미 계산된 지표뿐이다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ══════════════════════════════════════════════
# Advisor 입력 — 정제된 지표만
# ══════════════════════════════════════════════

@dataclass(frozen=True)
class AdvisorInput:
    """Advisor가 받을 수 있는 전부.

    EngineResult, ValidationReport, monthly_values 등은
    이 타입으로 변환된 후에만 Advisor에 전달된다.
    이 인터페이스가 "Advisor는 계산 금지"를 강제한다.
    """
    # 성과 지표 (이미 계산됨)
    mult_after_tax: float
    mdd: float
    tax_drag_pct: float
    n_months: int

    # 계좌 구성 (bool만)
    has_isa: bool = False
    has_progressive: bool = False
    n_accounts: int = 1
    rebalance_mode: str = "CONTRIBUTION_ONLY"

    # 검증 결과 (있으면)
    validation_grade: Optional[str] = None
    lane_d_survival: Optional[float] = None

    # 비교 (있으면)
    baseline_mult: Optional[float] = None       # SPY B&H 세후 배수
    baseline_gap_pct: Optional[float] = None    # 전략 - baseline


# ══════════════════════════════════════════════
# 진단 — 증상
# ══════════════════════════════════════════════

@dataclass(frozen=True)
class Diagnosis:
    """하나의 진단. 증상이지 처방이 아니다."""
    code: str           # "HIGH_TAX_DRAG" | "NO_ISA" | ...
    severity: str       # "critical" | "warning" | "info"
    message: str        # 한국어 설명
    metric: float = 0.0     # 관련 수치
    threshold: float = 0.0  # 기준선


# ══════════════════════════════════════════════
# 제안 — 처방
# ══════════════════════════════════════════════

@dataclass(frozen=True)
class SuggestionPatch:
    """하나의 개선 제안. 항상 patch 방식.

    Advisor는 완전한 새 config를 만들지 않는다.
    기존 config에 적용할 patch만 낸다.
    이 patch는 compile의 merge 규칙으로 적용된다.
    """
    kind: str                       # "add_isa" | "use_band" | "compare_baseline" | ...
    message: str                    # 한국어 제안
    patch: Dict = field(default_factory=dict)   # config에 적용할 변경
    rationale_codes: List[str] = field(default_factory=list)  # 근거 진단 코드
    priority: int = 50             # 낮을수록 먼저 (0=최우선, 99=부가)


# ══════════════════════════════════════════════
# Advisor 리포트
# ══════════════════════════════════════════════

@dataclass
class AdvisorReport:
    """Advisor 최종 출력."""
    diagnoses: List[Diagnosis] = field(default_factory=list)
    suggestions: List[SuggestionPatch] = field(default_factory=list)
    summary: str = ""

    @property
    def n_critical(self) -> int:
        return sum(1 for d in self.diagnoses if d.severity == "critical")

    @property
    def auto_experiments(self) -> List[Dict]:
        """자동 실험 configs. 최대 3개."""
        return [s.patch for s in self.suggestions if s.patch][:3]
