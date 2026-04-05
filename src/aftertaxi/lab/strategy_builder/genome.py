# -*- coding: utf-8 -*-
"""
lab/strategy_builder/genome.py — 전략 AST + 스케줄 변환
========================================================
StrategyGenome = growth + shelter + signal + rebalance + filter.
규칙 블록의 조합을 하나의 불변 객체로 표현.

genome_to_weight_schedule()로 가격 데이터를 주면
월별 목표 비중 리스트가 나온다 → signal_runner에 전달.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd

from aftertaxi.lab.strategy_builder.blocks import (
    AllocBlock, SignalBlock, AlwaysOn, StaticWeight,
)


@dataclass(frozen=True)
class StrategyGenome:
    """전략 유전자. 블록 조합의 불변 명세.

    growth:    성장 포지션 (신호=True일 때)
    shelter:   방어 포지션 (신호=False일 때)
    signal:    전환 신호 판단
    rebalance: 실행 정책 ("CO" / "FULL" / "BAND")
    filter:    추가 필터 (AND 조건, 없으면 None)
    """
    growth: AllocBlock
    shelter: AllocBlock
    signal: SignalBlock
    rebalance: str = "FULL"
    filter: Optional[SignalBlock] = None

    @property
    def label(self) -> str:
        """사람이 읽을 수 있는 1줄 요약."""
        parts = [
            f"G={self.growth.label}",
            f"S={self.shelter.label}",
            f"Sig={self.signal.label}",
            f"R={self.rebalance}",
        ]
        if self.filter is not None:
            parts.append(f"F={self.filter.label}")
        return " | ".join(parts)

    @property
    def all_assets(self) -> Tuple[str, ...]:
        """이 genome이 사용하는 모든 자산."""
        assets = set(self.growth.assets) | set(self.shelter.assets)
        return tuple(sorted(assets))

    @property
    def is_bnh(self) -> bool:
        """B&H 전략인지 (신호 없음 + 쉘터 없음)."""
        return isinstance(self.signal, AlwaysOn)

    def fingerprint(self) -> str:
        """재현 가능한 구조 해시."""
        d = self.to_dict()
        raw = json.dumps(d, sort_keys=True)
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        """직렬화."""
        d = {
            "growth": self.growth.to_dict(),
            "shelter": self.shelter.to_dict(),
            "signal": self.signal.to_dict(),
            "rebalance": self.rebalance,
        }
        if self.filter is not None:
            d["filter"] = self.filter.to_dict()
        return d


# ══════════════════════════════════════════════
# Genome → Weight Schedule 변환
# ══════════════════════════════════════════════

def genome_to_weight_schedule(
    genome: StrategyGenome,
    prices: pd.DataFrame,
) -> List[Dict[str, float]]:
    """StrategyGenome + 가격 데이터 → 월별 목표비중 리스트.

    각 월에서:
    1. signal.evaluate(prices, step) → True/False
    2. filter가 있으면 AND 적용
    3. True → growth.get_weights()
       False → shelter.get_weights()

    Parameters
    ----------
    genome : 전략 구조
    prices : 월별 가격 DataFrame (runner에 넘길 것과 동일)

    Returns
    -------
    List[Dict[str, float]] : 길이 = len(prices)
    """
    n = len(prices)
    schedule = []

    for step in range(n):
        # 1차 신호
        is_growth = genome.signal.evaluate(prices, step)

        # 2차 필터 (AND)
        if is_growth and genome.filter is not None:
            is_growth = genome.filter.evaluate(prices, step)

        # 비중 결정
        if is_growth:
            weights = genome.growth.get_weights()
        else:
            weights = genome.shelter.get_weights()

        schedule.append(weights)

    return schedule


def count_switches(schedule: List[Dict[str, float]]) -> int:
    """스케줄에서 비중 변경 횟수. turnover 근사."""
    if len(schedule) < 2:
        return 0
    switches = 0
    for i in range(1, len(schedule)):
        if set(schedule[i].keys()) != set(schedule[i - 1].keys()):
            switches += 1
        elif any(abs(schedule[i].get(k, 0) - schedule[i - 1].get(k, 0)) > 0.01
                 for k in set(schedule[i]) | set(schedule[i - 1])):
            switches += 1
    return switches
