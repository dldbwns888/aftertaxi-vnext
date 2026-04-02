# -*- coding: utf-8 -*-
"""
strategies/metadata.py — 전략 메타데이터
========================================
GUI가 전략을 동적으로 폼 생성하려면 이게 필요.

새 전략 추가 = builders.py에 함수 + 여기에 metadata 등록.
GUI 코드를 새로 안 짜도 폼이 자동 생성됨.

사용법:
  from aftertaxi.strategies.metadata import get_metadata, list_metadata

  meta = get_metadata("q60s40")
  meta.label         # "Q60S40"
  meta.params        # [ParamSchema(...), ...]
  meta.category      # "static_allocation"

  all_meta = list_metadata()  # 전체 전략 메타 리스트
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ParamSchema:
    """전략 파라미터 하나의 스키마. GUI 폼 필드 생성용."""
    name: str
    label: str
    type: str = "float"            # "float", "int", "str", "list", "dict"
    default: Any = None
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    choices: Optional[List[str]] = None  # dropdown용
    description: str = ""


@dataclass(frozen=True)
class StrategyMetadata:
    """전략 하나의 메타데이터. GUI 폼 + 카드 렌더용."""
    key: str                        # registry key ("q60s40")
    label: str                      # 표시 이름 ("Q60S40")
    category: str                   # "static_allocation", "benchmark", etc.
    description: str                # 한 줄 설명
    params: List[ParamSchema] = field(default_factory=list)
    default_weights: Dict[str, float] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)  # ["core", "leveraged", "benchmark"]


# ══════════════════════════════════════════════
# 메타데이터 저장소
# ══════════════════════════════════════════════

_METADATA: Dict[str, StrategyMetadata] = {}


def register_metadata(meta: StrategyMetadata) -> None:
    """메타데이터 등록."""
    _METADATA[meta.key] = meta


def get_metadata(key: str) -> StrategyMetadata:
    """키로 메타데이터 조회."""
    if key not in _METADATA:
        raise KeyError(f"Unknown strategy metadata: '{key}'. Available: {list(_METADATA.keys())}")
    return _METADATA[key]


def list_metadata() -> List[StrategyMetadata]:
    """등록된 전체 메타데이터 (카테고리순)."""
    return sorted(_METADATA.values(), key=lambda m: (m.category, m.key))


def list_by_category(category: str) -> List[StrategyMetadata]:
    """카테고리별 필터."""
    return [m for m in _METADATA.values() if m.category == category]


def categories() -> List[str]:
    """등록된 카테고리 목록."""
    return sorted(set(m.category for m in _METADATA.values()))


# ══════════════════════════════════════════════
# 내장 전략 메타데이터 등록
# ══════════════════════════════════════════════

_REBAL_PARAM = ParamSchema(
    "rebalance_every", "리밸 주기 (월)", "int", default=1, min_val=1, max_val=12,
)

register_metadata(StrategyMetadata(
    key="q60s40",
    label="Q60S40",
    category="static_allocation",
    description="QQQ 60% + SSO 40%. aftertaxi 코어 확정 전략.",
    params=[_REBAL_PARAM],
    default_weights={"QQQ": 0.6, "SSO": 0.4},
    tags=["core", "leveraged"],
))

register_metadata(StrategyMetadata(
    key="spy_bnh",
    label="SPY Buy & Hold",
    category="benchmark",
    description="SPY 100% 매수보유. 벤치마크.",
    params=[],
    default_weights={"SPY": 1.0},
    tags=["benchmark"],
))

register_metadata(StrategyMetadata(
    key="qqq_bnh",
    label="QQQ Buy & Hold",
    category="benchmark",
    description="QQQ 100% 매수보유.",
    params=[],
    default_weights={"QQQ": 1.0},
    tags=["benchmark"],
))

register_metadata(StrategyMetadata(
    key="6040",
    label="60/40 전통",
    category="static_allocation",
    description="주식 60% + 채권 40%. 전통 자산배분.",
    params=[
        ParamSchema("stock", "주식 ETF", "str", default="SPY",
                    choices=["SPY", "VOO", "QQQ", "VTI"]),
        ParamSchema("bond", "채권 ETF", "str", default="TLT",
                    choices=["TLT", "AGG", "SGOV", "SHY"]),
        _REBAL_PARAM,
    ],
    default_weights={"SPY": 0.6, "TLT": 0.4},
    tags=["traditional"],
))

register_metadata(StrategyMetadata(
    key="qqq_1.4x",
    label="QQQ 1.4x",
    category="leveraged_single",
    description="나스닥 1.4x 근사. QLD 40% + QQQ 60%.",
    params=[_REBAL_PARAM],
    default_weights={"QLD": 0.4, "QQQ": 0.6},
    tags=["leveraged", "nasdaq"],
))

register_metadata(StrategyMetadata(
    key="equal_weight",
    label="동일 비중",
    category="static_allocation",
    description="N종 동일비중.",
    params=[
        ParamSchema("assets", "자산 리스트", "list", default=["SPY", "QQQ"],
                    description="쉼표로 구분"),
        _REBAL_PARAM,
    ],
    default_weights={"SPY": 0.5, "QQQ": 0.5},
    tags=["equal_weight"],
))

register_metadata(StrategyMetadata(
    key="custom",
    label="사용자 정의",
    category="custom",
    description="자산과 비중을 직접 지정.",
    params=[
        ParamSchema("weights", "자산:비중", "dict", default={"SPY": 1.0},
                    description="예: SPY:0.7, QQQ:0.3"),
        ParamSchema("name", "전략 이름", "str", default="Custom"),
        _REBAL_PARAM,
    ],
    default_weights={"SPY": 1.0},
    tags=["custom"],
))
