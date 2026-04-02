# -*- coding: utf-8 -*-
"""
strategies/registry.py — 전략 등록소
=====================================
전략 추가 = 함수 하나 + @registry.register("key")

사용법:
  from aftertaxi.strategies import registry

  # 등록된 전략 목록
  registry.available()  # ['q60s40', 'spy_bnh', ...]

  # 빌드
  spec = registry.build("q60s40")
  config = spec.to_config()

  # JSON에서 빌드
  spec = registry.build_from_dict({"type": "q60s40", "name": "my_q60"})

  # 여러 개 한번에
  specs = registry.build_many([
      {"type": "q60s40"},
      {"type": "spy_bnh", "params": {"monthly": 500}},
  ])
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from aftertaxi.strategies.spec import StrategySpec


class StrategyRegistry:
    """전략 빌더 등록소.

    @registry.register("key")로 빌더를 등록하면
    registry.build("key", **params)로 StrategySpec을 생성.
    """

    def __init__(self) -> None:
        self._builders: Dict[str, Callable[..., StrategySpec]] = {}

    def register(self, key: str, metadata=None):
        """데코레이터: 빌더 함수를 등록. metadata 있으면 같이 등록."""
        def deco(func: Callable[..., StrategySpec]):
            self._builders[key] = func
            if metadata is not None:
                from aftertaxi.strategies.metadata import register_metadata
                register_metadata(metadata)
            return func
        return deco

    def available(self) -> List[str]:
        """등록된 전략 키 목록."""
        return sorted(self._builders.keys())

    def build(self, key: str, name: Optional[str] = None, **params) -> StrategySpec:
        """키 + 파라미터 → StrategySpec."""
        if key not in self._builders:
            raise KeyError(
                f"Unknown strategy: '{key}'. "
                f"Available: {self.available()}"
            )
        spec = self._builders[key](**params)
        if name:
            spec.name = name
        spec.source = "registry"
        return spec

    def build_from_dict(self, config: dict) -> StrategySpec:
        """dict/JSON → StrategySpec.

        Expected format:
          {"type": "q60s40", "name": "my_strategy", "params": {"monthly": 500}}
        """
        stype = config["type"]
        name = config.get("name")
        params = config.get("params", {})
        spec = self.build(stype, name=name, **params)
        spec.source = "json"
        return spec

    def build_many(self, config_list: List[dict]) -> List[StrategySpec]:
        """여러 전략을 한번에 빌드."""
        return [self.build_from_dict(c) for c in config_list]


# ── 글로벌 레지스트리 ──
registry = StrategyRegistry()
