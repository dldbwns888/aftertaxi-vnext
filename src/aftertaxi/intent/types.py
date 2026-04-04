# -*- coding: utf-8 -*-
"""
intent/types.py — 사용자 의도 타입
=================================
Intent는 BacktestConfig이 아니다.
Intent는 애매함을 허용한다. Compile이 결정한다.

규칙:
  - hint 접미사 = 애매함 허용 (str | dict | None)
  - bool = 있다/없다만
  - 구체적 숫자는 Compile이 채운다
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Union

# rebalance_hint 허용값
RebalanceHint = Literal["monthly", "drift_only", "minimal", "auto", None]


@dataclass(frozen=True)
class StrategyIntent:
    """전략 의도. 아직 실행 불가능할 수 있음."""
    description: str = ""                                # 원문 또는 요약
    assets_hint: Optional[List[str]] = None              # ["QQQ", "SSO"]
    weights_hint: Union[str, Dict[str, float], None] = None  # "6:4" 또는 {"QQQ": 0.6}
    strategy_type_hint: Optional[str] = None             # "bnh" | "momentum" | None
    rebalance_hint: RebalanceHint = None              # "drift_only" | "monthly" | "minimal" | "auto"
    leverage_ok: bool = True
    params_hint: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AccountIntent:
    """계좌 의도."""
    monthly_budget_hint: Union[str, float, None] = None  # "$1000" | 1000 | "월급의 30%"
    isa_first: bool = True
    taxable_allowed: bool = True
    progressive_tax: bool = False
    health_insurance: bool = False


@dataclass(frozen=True)
class ResearchIntent:
    """연구 요청."""
    run_validation: bool = False
    run_lane_d: bool = False
    compare_baseline: bool = True       # 거의 항상 True
    ask_for_improvements: bool = False
    check_overfitting: bool = False


@dataclass(frozen=True)
class FullIntent:
    """전체 의도. 파서 출력."""
    strategy: StrategyIntent = field(default_factory=StrategyIntent)
    account: AccountIntent = field(default_factory=AccountIntent)
    research: ResearchIntent = field(default_factory=ResearchIntent)
    raw_input: str = ""                 # 원문 보존
