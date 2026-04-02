# -*- coding: utf-8 -*-
"""
strategies/spec.py — 전략 명세
==============================
StrategyConfig(엔진 입력)보다 풍부한 메타데이터를 가진다.
연구 워크플로에서 "무엇을 시도했고, 왜 이 파라미터인지" 추적.

StrategySpec → StrategyConfig 변환은 to_config()으로.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from aftertaxi.core.contracts import StrategyConfig


@dataclass
class StrategySpec:
    """전략 명세. 엔진 실행 전 단계."""

    # ── 식별 ──
    name: str                              # "Q60S40_CO", "spy_bnh"
    family: str = ""                       # "static_allocation", "momentum", "regime"

    # ── 엔진 입력 ──
    weights: Dict[str, float] = field(default_factory=dict)
    rebalance_every: int = 1               # 리밸 주기 (월)

    # ── 메타데이터 ──
    params: Dict[str, Any] = field(default_factory=dict)
    description: str = ""
    source: str = ""                       # "builder", "json", "gui", "ai"

    def to_config(self) -> StrategyConfig:
        """엔진 실행용 StrategyConfig으로 변환."""
        return StrategyConfig(
            name=self.name,
            weights=self.weights,
            rebalance_every=self.rebalance_every,
        )

    def summary(self) -> str:
        w_str = ", ".join(f"{a}:{w:.0%}" for a, w in self.weights.items())
        return f"[{self.name}] {self.family} | {w_str} | rebal={self.rebalance_every}mo"
