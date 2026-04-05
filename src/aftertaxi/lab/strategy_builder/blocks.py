# -*- coding: utf-8 -*-
"""
lab/strategy_builder/blocks.py — 규칙 블록 풀
===============================================
전략을 구성하는 원자 단위. 각 블록은 불변(frozen)이고 직렬화 가능.

블록 종류:
  Signal  — 이 시점에서 성장/쉘터 중 어느 쪽인지 판단
  Alloc   — 주어진 자산의 목표 비중 산출
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd


# ══════════════════════════════════════════════
# Signal Blocks
# ══════════════════════════════════════════════

class SignalBlock(ABC):
    """신호 블록 인터페이스. evaluate() → True=성장, False=쉘터."""

    @abstractmethod
    def evaluate(self, prices: pd.DataFrame, step: int) -> bool:
        ...

    @abstractmethod
    def to_dict(self) -> dict:
        ...

    @property
    @abstractmethod
    def label(self) -> str:
        ...


@dataclass(frozen=True)
class AlwaysOn(SignalBlock):
    """항상 성장. B&H 전략의 신호."""

    def evaluate(self, prices: pd.DataFrame, step: int) -> bool:
        return True

    def to_dict(self) -> dict:
        return {"type": "always_on"}

    @property
    def label(self) -> str:
        return "AlwaysOn"


@dataclass(frozen=True)
class AbsMomentum(SignalBlock):
    """절대 모멘텀. asset의 N개월 수익률 > 0이면 성장.

    lookback=9: 대피+1.6x에서 사용된 값.
    """
    asset: str
    lookback: int = 9

    def evaluate(self, prices: pd.DataFrame, step: int) -> bool:
        if self.asset not in prices.columns:
            return True  # 데이터 없으면 성장 유지
        if step < self.lookback:
            return True  # lookback 부족이면 성장 유지
        current = prices.iloc[step][self.asset]
        past = prices.iloc[step - self.lookback][self.asset]
        if past <= 0:
            return True
        return bool((current / past - 1.0) > 0)

    def to_dict(self) -> dict:
        return {"type": "abs_momentum", "asset": self.asset,
                "lookback": self.lookback}

    @property
    def label(self) -> str:
        return f"AbsMom({self.asset},{self.lookback}m)"


@dataclass(frozen=True)
class RelMomentum(SignalBlock):
    """상대 모멘텀. asset_a의 N개월 수익률 > asset_b이면 성장."""
    asset_a: str
    asset_b: str
    lookback: int = 12

    def evaluate(self, prices: pd.DataFrame, step: int) -> bool:
        if step < self.lookback:
            return True
        for a in (self.asset_a, self.asset_b):
            if a not in prices.columns:
                return True
        cur_a = prices.iloc[step][self.asset_a]
        past_a = prices.iloc[step - self.lookback][self.asset_a]
        cur_b = prices.iloc[step][self.asset_b]
        past_b = prices.iloc[step - self.lookback][self.asset_b]
        if past_a <= 0 or past_b <= 0:
            return True
        ret_a = cur_a / past_a - 1.0
        ret_b = cur_b / past_b - 1.0
        return bool(ret_a > ret_b)

    def to_dict(self) -> dict:
        return {"type": "rel_momentum", "asset_a": self.asset_a,
                "asset_b": self.asset_b, "lookback": self.lookback}

    @property
    def label(self) -> str:
        return f"RelMom({self.asset_a}>{self.asset_b},{self.lookback}m)"


@dataclass(frozen=True)
class SMACross(SignalBlock):
    """SMA 크로스오버. asset 가격 > SMA(period)이면 성장."""
    asset: str
    period: int = 10

    def evaluate(self, prices: pd.DataFrame, step: int) -> bool:
        if self.asset not in prices.columns:
            return True
        if step < self.period:
            return True
        window = prices[self.asset].iloc[max(0, step - self.period + 1):step + 1]
        sma = window.mean()
        current = prices.iloc[step][self.asset]
        return bool(current > sma)

    def to_dict(self) -> dict:
        return {"type": "sma_cross", "asset": self.asset,
                "period": self.period}

    @property
    def label(self) -> str:
        return f"SMA({self.asset},{self.period}m)"


# ══════════════════════════════════════════════
# Allocation Blocks
# ══════════════════════════════════════════════

class AllocBlock(ABC):
    """배분 블록 인터페이스. get_weights() → Dict[asset, weight]."""

    @abstractmethod
    def get_weights(self) -> Dict[str, float]:
        ...

    @abstractmethod
    def to_dict(self) -> dict:
        ...

    @property
    @abstractmethod
    def label(self) -> str:
        ...

    @property
    @abstractmethod
    def assets(self) -> Tuple[str, ...]:
        """이 블록이 사용하는 자산 목록."""
        ...


@dataclass(frozen=True)
class StaticWeight(AllocBlock):
    """고정 비중."""
    weights: Dict[str, float] = field(default_factory=lambda: {"SPY": 1.0})

    def get_weights(self) -> Dict[str, float]:
        return dict(self.weights)

    def to_dict(self) -> dict:
        return {"type": "static", "weights": dict(self.weights)}

    @property
    def label(self) -> str:
        parts = [f"{a}{int(w*100)}" for a, w in self.weights.items()]
        return "Static(" + "/".join(parts) + ")"

    @property
    def assets(self) -> Tuple[str, ...]:
        return tuple(self.weights.keys())


@dataclass(frozen=True)
class EqualWeight(AllocBlock):
    """동일 비중."""
    asset_list: Tuple[str, ...] = ("SPY",)

    def get_weights(self) -> Dict[str, float]:
        w = 1.0 / len(self.asset_list)
        return {a: w for a in self.asset_list}

    def to_dict(self) -> dict:
        return {"type": "equal", "assets": list(self.asset_list)}

    @property
    def label(self) -> str:
        return f"Equal({','.join(self.asset_list)})"

    @property
    def assets(self) -> Tuple[str, ...]:
        return self.asset_list


@dataclass(frozen=True)
class CashShelter(AllocBlock):
    """현금성 쉘터 (SGOV, BIL 등)."""
    asset: str = "SGOV"

    def get_weights(self) -> Dict[str, float]:
        return {self.asset: 1.0}

    def to_dict(self) -> dict:
        return {"type": "cash_shelter", "asset": self.asset}

    @property
    def label(self) -> str:
        return f"Cash({self.asset})"

    @property
    def assets(self) -> Tuple[str, ...]:
        return (self.asset,)


@dataclass(frozen=True)
class BondShelter(AllocBlock):
    """채권 쉘터 (TLT, SHY 등)."""
    asset: str = "SHY"

    def get_weights(self) -> Dict[str, float]:
        return {self.asset: 1.0}

    def to_dict(self) -> dict:
        return {"type": "bond_shelter", "asset": self.asset}

    @property
    def label(self) -> str:
        return f"Bond({self.asset})"

    @property
    def assets(self) -> Tuple[str, ...]:
        return (self.asset,)
